"""Synthetic hand cam frames: a phone/iPad (bezel + game screen) on a desk, seen at an angle."""

from __future__ import annotations

import cv2
import numpy as np

W, H = 854, 480


def desk(rng: np.random.Generator, level: int = 70) -> np.ndarray:
    base = rng.normal(level, 12, (H // 8, W // 8, 3)).clip(0, 255).astype(np.uint8)
    img = cv2.resize(base, (W, H), interpolation=cv2.INTER_CUBIC)
    return cv2.add(img, rng.normal(0, 4, img.shape).astype(np.int16).clip(0, 255).astype(np.uint8))


def game_screen(rng: np.random.Generator, w: int = 800, h: int = 370, brightness: int = 130) -> np.ndarray:
    img = np.full((h, w, 3), brightness, np.uint8)
    img[:] = (brightness * 0.8, brightness, brightness * 1.1)
    for _ in range(40):
        color = tuple(int(c) for c in rng.integers(max(0, brightness - 70), min(255, brightness + 90), 3))
        center = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.circle(img, center, int(rng.integers(8, 60)), color, -1)
    cv2.rectangle(img, (20, 20), (180, 60), (230, 230, 230), -1)  # HUD element
    return img


def device(screen: np.ndarray, bezel: int = 18) -> np.ndarray:
    h, w = screen.shape[:2]
    out = np.full((h + 2 * bezel, w + 2 * bezel, 3), 12, np.uint8)
    out[bezel:bezel + h, bezel:bezel + w] = screen
    return out


def place(scene: np.ndarray, obj: np.ndarray, quad: np.ndarray) -> np.ndarray:
    h, w = obj.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    m = cv2.getPerspectiveTransform(src, np.float32(quad))
    warped = cv2.warpPerspective(obj, m, (scene.shape[1], scene.shape[0]))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (scene.shape[1], scene.shape[0]))
    out = scene.copy()
    out[mask > 0] = warped[mask > 0]
    return out


def thumbs(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Skin-coloured thumbs pressing on the left and right screen edges."""
    out = img.copy()
    tl, tr, br, bl = quad
    k = np.linalg.norm(tl - bl) / 335  # thumb size follows the device size in frame
    for a, b in ((tl, bl), (tr, br)):
        mid = (a * 0.4 + b * 0.6).astype(int)
        axes = (int(45 * k), int(28 * k))
        cv2.ellipse(out, tuple(int(v) for v in mid), axes, 20, 0, 360, (120, 150, 200), -1)
    return out


def scene(
    quad,
    *,
    seed: int = 1,
    brightness: int = 130,
    glare: bool = False,
    with_thumbs: bool = True,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    quad = np.float32(quad)
    screen = game_screen(rng, brightness=brightness)
    if glare:
        cv2.ellipse(screen, (420, 170), (260, 120), 0, 0, 360, (255, 255, 255), -1)
    img = place(desk(rng), device(screen), quad)
    if with_thumbs:
        img = thumbs(img, quad)
    return cv2.GaussianBlur(img, (3, 3), 0)


# A device filling most of the frame, slightly tilted (camera above, looking down).
GOOD = [[110, 70], [750, 85], [770, 420], [90, 405]]
