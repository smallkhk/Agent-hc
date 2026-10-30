"""Trains the hack-menu classifier and exports it to ONNX for the worker.

    python -m training.train --data training/dataset --out worker/models [--arch mobilenet_v3_large] [--epochs 15]

Outputs menu_classifier.onnx, labels.json (classes + preprocessing the worker must match) and
metrics.json (per-class precision / recall on a held-out split).
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import models

from training.collect import CLASSES, IMAGE_EXT, SIZE

MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
SUSPICIOUS = ["mod_menu", "esp_overlay", "unknown_overlay"]


# --- augmentation (numpy / OpenCV, BGR uint8) ---------------------------------------------
# Mimics what a phone camera filming a screen does to the flattened crop.

def perspective(img: np.ndarray, rng: random.Random, amount: float = 0.06) -> np.ndarray:
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = np.float32([[rng.uniform(-amount, amount) * w, rng.uniform(-amount, amount) * h] for _ in range(4)])
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, src + jitter), (w, h), borderMode=cv2.BORDER_REFLECT)


def glare(img: np.ndarray, rng: random.Random) -> np.ndarray:
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.float32)
    center = (rng.randint(0, w), rng.randint(0, h))
    axes = (rng.randint(w // 10, w // 3), rng.randint(h // 10, h // 3))
    cv2.ellipse(mask, center, axes, rng.uniform(0, 180), 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), max(axes) / 2) * rng.uniform(0.3, 0.8)
    return (img * (1 - mask[..., None]) + 255 * mask[..., None]).astype(np.uint8)


def color(img: np.ndarray, rng: random.Random) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + rng.uniform(-6, 6)) % 180
    hsv[..., 1] *= rng.uniform(0.7, 1.3)
    hsv[..., 2] *= rng.uniform(0.6, 1.3)
    return cv2.cvtColor(hsv.clip(0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)


def jpeg(img: np.ndarray, rng: random.Random) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(25, 85)])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img


SKIN = [(45, 60, 95), (60, 85, 130), (80, 110, 160), (110, 145, 200), (140, 175, 225)]  # BGR, dark to light


def fingers(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Thumbs and fingers over the screen: every real hand cam has them, whatever the class."""
    h, w = img.shape[:2]
    out = img.copy()
    for _ in range(rng.randint(1, 3)):
        side = rng.choice(["bottom", "left", "right", "top"])
        thick = rng.randint(h // 9, h // 5)
        start = {"bottom": (rng.randint(0, w), h + thick), "top": (rng.randint(0, w), -thick),
                 "left": (-thick, rng.randint(0, h)), "right": (w + thick, rng.randint(0, h))}[side]
        tip = (rng.randint(w // 8, w * 7 // 8), rng.randint(h // 6, h * 5 // 6))
        tone = np.array(rng.choice(SKIN), np.float32) * rng.uniform(0.8, 1.15)
        mask = np.zeros((h, w), np.uint8)
        cv2.line(mask, start, tip, 255, thick)
        cv2.circle(mask, tip, thick // 2, 255, -1)
        m = cv2.GaussianBlur(mask, (0, 0), thick / 6).astype(np.float32)[..., None] / 255
        shade = 1 - 0.35 * np.linspace(0, 1, w, dtype=np.float32)[None, :, None] * rng.random()
        out = (out * (1 - m) + tone.clip(0, 255) * shade * m).astype(np.uint8)
    return out


def wash(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Camera filming a bright screen: low contrast, lifted blacks, warm or cool cast."""
    cast = np.array([rng.uniform(170, 235), rng.uniform(170, 235), rng.uniform(170, 235)], np.float32)
    a = rng.uniform(0.15, 0.45)
    return (img.astype(np.float32) * (1 - a) + cast * a).clip(0, 255).astype(np.uint8)


def augment(img: np.ndarray, rng: random.Random) -> np.ndarray:
    if rng.random() < 0.6:
        img = fingers(img, rng)
    if rng.random() < 0.5:
        img = wash(img, rng)
    if rng.random() < 0.7:
        img = perspective(img, rng)
    if rng.random() < 0.3:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.5, 1.8))
    if rng.random() < 0.3:
        img = glare(img, rng)
    if rng.random() < 0.8:
        img = color(img, rng)
    if rng.random() < 0.5:
        img = jpeg(img, rng)
    return img


def to_tensor(img: np.ndarray) -> torch.Tensor:
    img = cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA)
    x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1) / 255.0
    x = (x - np.array(MEAN, np.float32)[:, None, None]) / np.array(STD, np.float32)[:, None, None]
    return torch.from_numpy(x)


class Crops(Dataset):
    def __init__(self, items: list[tuple[Path, int]], train: bool, seed: int) -> None:
        self.items = items
        self.train = train
        self.seed = seed
        self.epoch = 0

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int) -> tuple[torch.Tensor, int]:
        path, label = self.items[i]
        img = cv2.imread(str(path))
        if self.train:
            img = augment(img, random.Random(hash((self.seed, self.epoch, i))))
        return to_tensor(img), label


# --- data ------------------------------------------------------------------------------------

def load_items(root: Path) -> tuple[list[str], list[tuple[Path, int]]]:
    dirs = sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith("_"))
    classes = [c for c in CLASSES if c in dirs] + [d for d in dirs if d not in CLASSES]
    items = [(p, i) for i, c in enumerate(classes) for p in sorted((root / c).iterdir()) if p.suffix.lower() in IMAGE_EXT]
    return classes, items


def split(items: list[tuple[Path, int]], val_frac: float, seed: int) -> tuple[list, list]:
    """Stratified split so every class appears in validation."""
    rng = random.Random(seed)
    train, val = [], []
    for label in sorted({l for _, l in items}):
        group = [it for it in items if it[1] == label]
        rng.shuffle(group)
        n_val = max(1, round(len(group) * val_frac)) if len(group) > 1 else 0
        val += group[:n_val]
        train += group[n_val:]
    return train, val


def build_model(arch: str, n_classes: int, pretrained: bool) -> nn.Module:
    if arch.startswith("mobilenet_v3"):
        model = getattr(models, arch)(weights="DEFAULT" if pretrained else None)
        model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, n_classes)
    elif arch == "efficientnet_b0":
        model = models.efficientnet_b0(weights="DEFAULT" if pretrained else None)
        model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, n_classes)
    else:
        raise SystemExit(f"unknown --arch {arch}")
    return model


def evaluate(model: nn.Module, loader: DataLoader, n: int) -> tuple[np.ndarray, float]:
    model.eval()
    confusion = np.zeros((n, n), dtype=np.int64)
    with torch.no_grad():
        for x, y in loader:
            pred = model(x).argmax(1)
            for t, p in zip(y.tolist(), pred.tolist()):
                confusion[t, p] += 1
    recall = np.diag(confusion) / np.maximum(confusion.sum(1), 1)
    precision = np.diag(confusion) / np.maximum(confusion.sum(0), 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-9)
    return confusion, float(f1[confusion.sum(1) > 0].mean())


def export_onnx(model: nn.Module, path: Path) -> None:
    model.eval()
    dummy = torch.randn(1, 3, SIZE[1], SIZE[0])
    torch.onnx.export(
        model, dummy, str(path), input_names=["image"], output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}}, opset_version=17, dynamo=False,
    )
    # The worker runs onnxruntime: make sure it agrees with PyTorch.
    import onnxruntime as ort

    ref = model(dummy).detach().numpy()
    got = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]).run(None, {"image": dummy.numpy()})[0]
    if not np.allclose(ref, got, atol=1e-3):
        raise SystemExit(f"ONNX output differs from PyTorch (max diff {np.abs(ref - got).max():.4f})")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path("training/dataset"))
    ap.add_argument("--out", type=Path, default=Path("worker/models"))
    ap.add_argument("--arch", default="mobilenet_v3_large", choices=["mobilenet_v3_large", "mobilenet_v3_small", "efficientnet_b0"])
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-pretrained", action="store_true", help="train from scratch (no ImageNet weights)")
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    classes, items = load_items(args.data)
    if len(classes) < 2:
        raise SystemExit(f"need at least 2 classes in {args.data}, found {classes}")
    train_items, val_items = split(items, args.val, args.seed)
    counts = Counter(l for _, l in train_items)
    print("train:", {classes[k]: v for k, v in sorted(counts.items())}, "val:", len(val_items))

    train_ds = Crops(train_items, train=True, seed=args.seed)
    # Class-balanced: each class is drawn equally often whatever its size.
    weights = [1.0 / counts[l] for _, l in train_items]
    sampler = WeightedRandomSampler(weights, num_samples=len(train_items), replacement=True)
    train_dl = DataLoader(train_ds, batch_size=args.batch, sampler=sampler, num_workers=args.workers)
    val_dl = DataLoader(Crops(val_items, train=False, seed=0), batch_size=args.batch, num_workers=args.workers)

    model = build_model(args.arch, len(classes), pretrained=not args.no_pretrained)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * len(train_dl))
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.05)

    best_f1, best_state, best_conf = -1.0, None, None
    for epoch in range(args.epochs):
        train_ds.epoch = epoch
        model.train()
        started, total = time.time(), 0.0
        for x, y in train_dl:
            opt.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            opt.step()
            sched.step()
            total += loss.item() * len(y)
        confusion, f1 = evaluate(model, val_dl, len(classes))
        print(f"epoch {epoch + 1}/{args.epochs}  loss {total / len(train_items):.3f}  val macro-F1 {f1:.3f}  ({time.time() - started:.0f}s)")
        if f1 > best_f1:
            best_f1, best_conf = f1, confusion
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    args.out.mkdir(parents=True, exist_ok=True)
    export_onnx(model, args.out / "menu_classifier.onnx")
    (args.out / "labels.json").write_text(json.dumps({
        "classes": classes,
        "suspicious": [c for c in SUSPICIOUS if c in classes],
        "input": {"width": SIZE[0], "height": SIZE[1]},
        "mean": MEAN,
        "std": STD,
        "arch": args.arch,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2))
    per_class = {
        c: {
            "precision": round(float(best_conf[i, i] / max(best_conf[:, i].sum(), 1)), 3),
            "recall": round(float(best_conf[i, i] / max(best_conf[i].sum(), 1)), 3),
            "support": int(best_conf[i].sum()),
        }
        for i, c in enumerate(classes)
    }
    (args.out / "metrics.json").write_text(json.dumps({
        "macro_f1": round(best_f1, 3), "per_class": per_class, "confusion": best_conf.tolist(),
        "classes": classes, "train_counts": {classes[k]: v for k, v in counts.items()},
    }, indent=2))
    print(f"saved {args.out / 'menu_classifier.onnx'}  macro-F1 {best_f1:.3f}")
    for c, m in per_class.items():
        print(f"  {c:18s} precision {m['precision']:.2f}  recall {m['recall']:.2f}  (n={m['support']})")


if __name__ == "__main__":
    main()
