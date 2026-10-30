"""Rule 2: hack / mod menus and overlays on the game screen.

The detected screen is perspective-warped to a flat 448x224 image and classified by an
ONNX model (MobileNetV3 / EfficientNet-B0 trained by training/train.py). One ONNX session
is shared by every session watcher. No model file → the rule is off.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("worker.menu")

SUSPICIOUS_DEFAULT = ("mod_menu", "esp_overlay", "unknown_overlay")


def flatten_screen(frame_bgr: np.ndarray, corners: np.ndarray, size: tuple[int, int] = (448, 224)) -> np.ndarray:
    """Warp the screen quad (TL, TR, BR, BL) to a flat landscape image."""
    c = corners.astype(np.float32)
    width = (np.linalg.norm(c[0] - c[1]) + np.linalg.norm(c[3] - c[2])) / 2
    height = (np.linalg.norm(c[0] - c[3]) + np.linalg.norm(c[1] - c[2])) / 2
    if height > width:  # camera held sideways: rotate so the game is landscape
        c = np.roll(c, -1, axis=0)
    w, h = size
    dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    return cv2.warpPerspective(frame_bgr, cv2.getPerspectiveTransform(c, dst), size)


@dataclass(frozen=True)
class Prediction:
    top: str  # most likely class
    top_score: float
    label: str | None  # most likely suspicious class (what a flag reports)
    score: float  # its probability: the rule compares this with MENU_THRESHOLD


class MenuClassifier:
    """Thread-safe wrapper around one shared onnxruntime session."""

    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort  # optional dependency: only needed once a model exists

        meta = json.loads(model_path.with_name("labels.json").read_text())
        self.classes: list[str] = meta["classes"]
        self.suspicious = set(meta.get("suspicious", SUSPICIOUS_DEFAULT))
        self.size = (meta["input"]["width"], meta["input"]["height"])
        self.mean = np.array(meta.get("mean", [0.485, 0.456, 0.406]), np.float32).reshape(3, 1, 1)
        self.std = np.array(meta.get("std", [0.229, 0.224, 0.225]), np.float32).reshape(3, 1, 1)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2  # many sessions share the box; keep each inference small
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self._lock = threading.Lock()

    @classmethod
    def load(cls, model_path: Path) -> MenuClassifier | None:
        if not model_path.exists():
            log.info("no menu model at %s: hack-menu rule off", model_path)
            return None
        clf = cls(model_path)
        log.info("menu model loaded: %s", ", ".join(clf.classes))
        return clf

    def predict(self, flat_bgr: np.ndarray) -> Prediction:
        img = cv2.resize(flat_bgr, self.size, interpolation=cv2.INTER_AREA)
        x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1) / 255.0
        x = ((x - self.mean) / self.std)[None]
        with self._lock:
            logits = self.session.run(None, {self.input_name: x})[0][0]
        p = np.exp(logits - logits.max())
        p /= p.sum()
        i = int(p.argmax())
        sus = max(((float(p[j]), c) for j, c in enumerate(self.classes) if c in self.suspicious), default=(0.0, None))
        return Prediction(self.classes[i], float(p[i]), sus[1], sus[0])


class MenuRule:
    """Flag when a suspicious class scores ≥ threshold on 2 of the last 3 samples; once per episode."""

    def __init__(self, threshold: float, window: int = 3, needed: int = 2) -> None:
        self.threshold = threshold
        self.needed = needed
        self.recent: deque[Prediction | None] = deque(maxlen=window)
        self.flagged = False

    def update(self, pred: Prediction | None) -> Prediction | None:
        self.recent.append(pred)
        hits = [p for p in self.recent if p and p.label and p.score >= self.threshold]
        if len(hits) >= self.needed:
            if self.flagged:
                return None
            self.flagged = True
            return max(hits, key=lambda p: p.score)
        if not hits:
            self.flagged = False  # the menu is gone: a new one flags again
        return None
