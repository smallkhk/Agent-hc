"""Rule 3: stream integrity. Freeze detection here; drops are tracked by the session loop
(it knows when the player's track is missing), loop detection comes in Phase 6."""

from __future__ import annotations

import cv2
import numpy as np

FEED_FROZEN = "FEED_FROZEN"
STREAM_DROPPED = "STREAM_DROPPED"
STREAM_RECONNECTED = "STREAM_RECONNECTED"


class FreezeDetector:
    """Mean absolute difference between consecutive samples on a small grayscale copy.

    A live camera always has some sensor noise and motion; a frozen or replayed-still feed
    (or a camera covered by a hand) is almost perfectly static.
    """

    SIZE = (160, 90)

    def __init__(self, diff_threshold: float) -> None:
        self.diff_threshold = diff_threshold
        self.prev: np.ndarray | None = None

    def update(self, frame_bgr: np.ndarray) -> float:
        small = cv2.cvtColor(cv2.resize(frame_bgr, self.SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        small = small.astype(np.int16)
        diff = 255.0 if self.prev is None else float(np.abs(small - self.prev).mean())
        self.prev = small
        return diff

    def is_static(self, diff: float) -> bool:
        return diff < self.diff_threshold

    def reset(self) -> None:
        self.prev = None
