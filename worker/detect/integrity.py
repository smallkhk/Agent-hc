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


FEED_LOOPED = "FEED_LOOPED"
SCENE_CHANGED = "SCENE_CHANGED"

_THUMB = (32, 18)


def phash(gray: np.ndarray) -> int:
    """64-bit perceptual hash: low-frequency DCT signs. Robust to noise and re-encoding."""
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    low = cv2.dct(small)[:8, :8].ravel()
    bits = low > np.median(low[1:])
    return int.from_bytes(np.packbits(bits).tobytes(), "big")


def hamming(a: np.ndarray | int, b: int) -> np.ndarray:
    return np.bitwise_count(np.bitwise_xor(np.asarray(a, dtype=np.uint64), np.uint64(b)))


class LoopDetector:
    """Replayed / looped footage: a run of consecutive samples matching an earlier run in order.

    Ring buffer of ~10 min of pHashes (+ tiny thumbnails to confirm a match at pixel level).
    A run must contain motion, so a static scene (paused lobby, phone asleep) never counts.
    """

    def __init__(self, capacity: int, match_run: int = 20, max_bits: int = 6, max_thumb_diff: float = 8.0,
                 motion_bits: int = 4, hold: int = 60) -> None:
        self.capacity = capacity
        self.match_run = match_run
        self.max_bits = max_bits
        self.max_thumb_diff = max_thumb_diff
        self.motion_bits = motion_bits
        self.hold = hold  # samples the "looping" state persists after the last match
        self.hashes = np.zeros(capacity, dtype=np.uint64)
        self.thumbs = np.zeros((capacity, _THUMB[1], _THUMB[0]), dtype=np.uint8)
        self.count = 0  # samples seen
        self.runs: dict[int, tuple[int, int]] = {}  # offset -> (run length, motion steps)
        self.last_hit = -10**9
        self.prev_hash: int | None = None

    def update(self, frame_bgr: np.ndarray) -> bool:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        h = phash(gray)
        thumb = cv2.resize(gray, _THUMB, interpolation=cv2.INTER_AREA)
        t = self.count
        moving = self.prev_hash is not None and int(hamming(h, self.prev_hash)) > self.motion_bits
        self.prev_hash = h

        # Candidates: older than one run (the recent past always looks alike) and still in the buffer.
        oldest = max(0, t - self.capacity)
        newest = t - self.match_run
        new_runs: dict[int, tuple[int, int]] = {}
        if newest > oldest:
            ages = np.arange(oldest, newest)
            slots = ages % self.capacity
            close = hamming(self.hashes[slots], h) <= self.max_bits
            for age, slot in zip(ages[close], slots[close]):
                diff = float(np.abs(self.thumbs[slot].astype(np.int16) - thumb).mean())
                if diff > self.max_thumb_diff:
                    continue
                offset = t - int(age)
                # sampling jitter: a replay can drift by one sample against the original
                prev = max((self.runs.get(o, (0, 0)) for o in (offset - 1, offset, offset + 1)), key=lambda r: r[0])
                run = (prev[0] + 1, prev[1] + int(moving))
                if run[0] > new_runs.get(offset, (0, 0))[0]:
                    new_runs[offset] = run
        self.runs = new_runs
        if any(n >= self.match_run and m >= self.match_run // 3 for n, m in new_runs.values()):
            self.last_hit = t

        slot = t % self.capacity
        self.hashes[slot] = h
        self.thumbs[slot] = thumb
        self.count += 1
        return t - self.last_hit < self.hold


class SceneChangeDetector:
    """Sudden change of everything around the screen (other room, other device), confirmed over a few samples.

    Slow drift (light changing, camera nudged) follows the reference instead of firing.
    """

    def __init__(self, max_bits: int = 22, confirm: int = 4) -> None:
        self.max_bits = max_bits
        self.confirm = confirm
        self.ref: int | None = None
        self.pending = 0

    @staticmethod
    def background(frame_bgr: np.ndarray, corners: np.ndarray | None) -> np.ndarray:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if corners is not None:  # the game screen changes all the time: hide it
            cv2.fillConvexPoly(gray, corners.astype(np.int32), int(gray.mean()))
        return gray

    def update(self, frame_bgr: np.ndarray, corners: np.ndarray | None) -> bool:
        h = phash(self.background(frame_bgr, corners))
        if self.ref is None or int(hamming(h, self.ref)) <= self.max_bits:
            self.ref, self.pending = h, 0
            return False
        self.pending += 1
        if self.pending >= self.confirm:
            self.ref, self.pending = h, 0
            return True
        return False
