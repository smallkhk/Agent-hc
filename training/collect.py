"""Builds training/dataset/<class>/ from footage, screenshots and admin-labelled alerts.

    python -m training.collect video  --label normal_gameplay a.mp4 b.mp4 [--every 1.0]
    python -m training.collect images --label mod_menu shots/ [--raw]
    python -m training.collect db     [--storage /var/handcam/recordings]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import cv2
import numpy as np

from worker.detect.integrity import hamming, phash
from worker.detect.menu import SUSPICIOUS_DEFAULT, flatten_screen
from worker.detect.screen import ScreenParams, detect_screen

CLASSES = ("normal_gameplay", "codm_menu_ui", "mod_menu", "esp_overlay", "unknown_overlay")
SIZE = (448, 224)
DEDUP_BITS = 4  # consecutive near-identical crops add nothing
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Footage for training can be framed a little looser than the live rule requires.
PARAMS = ScreenParams(edge_margin_px=2, min_area=0.08, aspect_min=1.15, aspect_max=2.4)


class Writer:
    def __init__(self, root: Path, label: str) -> None:
        self.dir = root / label
        self.dir.mkdir(parents=True, exist_ok=True)
        self.last: int | None = None
        self.saved = 0

    def add(self, flat: np.ndarray, name: str) -> bool:
        h = phash(cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY))
        if self.last is not None and int(hamming(h, self.last)) <= DEDUP_BITS:
            return False
        self.last = h
        cv2.imwrite(str(self.dir / f"{name}.jpg"), flat, [cv2.IMWRITE_JPEG_QUALITY, 92])
        self.saved += 1
        return True


def crop(frame: np.ndarray) -> np.ndarray | None:
    r = detect_screen(frame, PARAMS)
    return flatten_screen(frame, r.corners, SIZE) if r.ok and r.corners is not None else None


def from_videos(files: list[Path], out: Writer, every: float) -> None:
    for f in files:
        cap = cv2.VideoCapture(str(f))
        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        step = max(1, round(fps * every))
        i = found = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                _, frame = cap.retrieve()
                flat = crop(frame)
                if flat is not None and out.add(flat, f"{f.stem}_{i:06d}"):
                    found += 1
            i += 1
        cap.release()
        print(f"{f}: {found} crops from {i} frames")


def from_images(paths: list[Path], out: Writer, raw: bool) -> None:
    files = [p for d in paths for p in (sorted(d.rglob("*")) if d.is_dir() else [d]) if p.suffix.lower() in IMAGE_EXT]
    for f in files:
        img = cv2.imread(str(f))
        if img is None:
            continue
        flat = cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA) if raw else crop(img)
        if flat is None:
            print(f"{f}: no screen found (use --raw for plain screenshots)")
            continue
        out.add(flat, f.stem)
    print(f"{out.saved} images → {out.dir}")


def from_db(root: Path, storage: Path) -> None:
    import mysql.connector

    url = urlparse(os.environ["MYSQL_URL"])
    db = mysql.connector.connect(
        host=url.hostname, port=url.port or 3306, user=unquote(url.username or ""),
        password=unquote(url.password or ""), database=url.path.lstrip("/"),
    )
    cur = db.cursor()
    cur.execute(
        """SELECT t.id, t.image_path, e.type, e.admin_action FROM training_samples t
           JOIN events e ON e.id = t.event_id WHERE t.source = 'admin'"""
    )
    counts: dict[str, int] = {}
    for sample_id, image_path, event_type, action in cur.fetchall():
        if event_type not in CLASSES:
            continue  # screen / integrity rules don't train the menu model
        if action == "confirmed":
            label = event_type
        elif event_type in SUSPICIOUS_DEFAULT:
            label = "_review"  # not a hack menu; gameplay or CODM menu: sort by hand
        else:
            continue
        src = storage / image_path
        if not src.exists():
            continue
        dst = root / label / f"admin_{sample_id}.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            img = cv2.imread(str(src))
            if img is not None and img.shape[1::-1] != SIZE:
                img = cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(dst), img)
            else:
                shutil.copyfile(src, dst)
            counts[label] = counts.get(label, 0) + 1
    print("new samples:", counts or "none")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=Path("training/dataset"))
    sub = ap.add_subparsers(dest="mode", required=True)
    v = sub.add_parser("video")
    v.add_argument("--label", required=True, choices=CLASSES)
    v.add_argument("--every", type=float, default=1.0, help="seconds between samples")
    v.add_argument("files", type=Path, nargs="+")
    im = sub.add_parser("images")
    im.add_argument("--label", required=True, choices=CLASSES)
    im.add_argument("--raw", action="store_true", help="images are screenshots, not camera photos")
    im.add_argument("paths", type=Path, nargs="+")
    d = sub.add_parser("db")
    d.add_argument("--storage", type=Path, default=Path(os.environ.get("STORAGE_DIR", "/var/handcam/recordings")))
    args = ap.parse_args(argv)

    if args.mode == "video":
        from_videos(args.files, Writer(args.dataset, args.label), args.every)
    elif args.mode == "images":
        from_images(args.paths, Writer(args.dataset, args.label), args.raw)
    else:
        from_db(args.dataset, args.storage)


if __name__ == "__main__":
    sys.exit(main())
