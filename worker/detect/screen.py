"""Rule 1: is the whole game screen inside the camera frame?

Finds the largest bright quadrilateral (Canny + contours + approxPolyDP, with an Otsu
threshold fallback) and checks its corners, size, aspect ratio, brightness and glare.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

WORK_WIDTH = 640  # detection runs on a downscaled copy

NOT_FOUND = "SCREEN_NOT_FOUND"
CUT_OFF = "SCREEN_CUT_OFF"
TOO_SMALL = "SCREEN_TOO_SMALL"
DARK = "SCREEN_DARK"
GLARE = "GLARE"


@dataclass(frozen=True)
class ScreenParams:
    edge_margin_px: int = 8  # in source-frame pixels
    min_area: float = 0.15  # fraction of the frame
    aspect_min: float = 1.3
    aspect_max: float = 2.3
    min_brightness: float = 40.0  # mean gray inside the screen, 0-255
    glare_level: int = 250
    glare_frac: float = 0.12  # fraction of saturated pixels that counts as glare


@dataclass
class ScreenResult:
    ok: bool
    reason: str | None
    corners: np.ndarray | None  # 4x2 float32 in source pixels, TL, TR, BR, BL
    area_frac: float = 0.0
    aspect: float = 0.0
    brightness: float = 0.0
    glare_frac: float = 0.0


def order_corners(pts: np.ndarray) -> np.ndarray:
    """TL, TR, BR, BL."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def quad_aspect(c: np.ndarray) -> float:
    w = (np.linalg.norm(c[0] - c[1]) + np.linalg.norm(c[3] - c[2])) / 2
    h = (np.linalg.norm(c[0] - c[3]) + np.linalg.norm(c[1] - c[2])) / 2
    lo, hi = sorted((w, h))
    return float(hi / lo) if lo > 0 else 0.0


def _to_quad(contour: np.ndarray) -> np.ndarray | None:
    # Hull first: thumbs on the screen edges make the outline concave.
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03, 0.05, 0.08):  # rounded phone corners need a looser fit
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return order_corners(approx)
    # Still not 4 points: accept the min-area rectangle if the hull is close to one.
    rect = cv2.minAreaRect(hull)
    rect_area = rect[1][0] * rect[1][1]
    if rect_area > 0 and cv2.contourArea(hull) / rect_area > 0.85:
        return order_corners(cv2.boxPoints(rect))
    return None


def _candidate_contours(gray: np.ndarray) -> list[np.ndarray]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    by_edges, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    by_brightness, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    contours = list(by_edges) + list(by_brightness)
    contours.sort(key=cv2.contourArea, reverse=True)
    return contours[:12]


def _touches_border(contour: np.ndarray, w: int, h: int, margin: float) -> bool:
    x, y, cw, ch = cv2.boundingRect(contour)
    return x <= margin or y <= margin or x + cw >= w - margin or y + ch >= h - margin


def detect_screen(frame_bgr: np.ndarray, p: ScreenParams = ScreenParams()) -> ScreenResult:
    src_h, src_w = frame_bgr.shape[:2]
    scale = WORK_WIDTH / src_w if src_w > WORK_WIDTH else 1.0
    small = cv2.resize(frame_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1 else frame_bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    frame_area = float(w * h)
    margin = p.edge_margin_px * scale

    best_inside: tuple[np.ndarray, float, float] | None = None  # (quad, area_frac, aspect)
    cut_off = False
    for contour in _candidate_contours(gray):
        area_frac = cv2.contourArea(cv2.convexHull(contour)) / frame_area
        if area_frac < 0.03:
            break  # sorted by area; the rest are smaller
        if area_frac > 0.97:
            continue  # the whole frame, not a screen
        quad = _to_quad(contour)
        touches = _touches_border(contour, w, h, margin)
        if quad is None:
            cut_off |= touches and area_frac >= p.min_area / 2
            continue
        aspect = quad_aspect(quad)
        inside = bool(np.all((quad[:, 0] >= margin) & (quad[:, 0] <= w - 1 - margin)
                             & (quad[:, 1] >= margin) & (quad[:, 1] <= h - 1 - margin)))
        if not inside or touches:
            # A big screen-like blob running off the frame edge.
            cut_off |= area_frac >= p.min_area / 2
            continue
        if not (p.aspect_min <= aspect <= p.aspect_max):
            continue
        quad_area = cv2.contourArea(quad) / frame_area
        if best_inside is None or quad_area > best_inside[1]:
            best_inside = (quad, quad_area, aspect)

    if best_inside is None:
        return ScreenResult(False, CUT_OFF if cut_off else NOT_FOUND, None)

    quad, area_frac, aspect = best_inside
    corners = quad / scale
    if cut_off and area_frac < p.min_area:
        # The real screen runs off the edge; what's inside is a smaller rectangle on it.
        return ScreenResult(False, CUT_OFF, corners, area_frac, aspect)
    if area_frac < p.min_area:
        return ScreenResult(False, TOO_SMALL, corners, area_frac, aspect)

    mask = np.zeros_like(gray)
    cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
    pixels = gray[mask > 0]
    brightness = float(pixels.mean())
    glare = float((pixels >= p.glare_level).mean())
    if brightness < p.min_brightness:
        return ScreenResult(False, DARK, corners, area_frac, aspect, brightness, glare)
    if glare > p.glare_frac:
        return ScreenResult(False, GLARE, corners, area_frac, aspect, brightness, glare)
    return ScreenResult(True, None, corners, area_frac, aspect, brightness, glare)


class CornerSmoother:
    """EMA over corners so the overlay/warp doesn't flicker; resets on a big jump."""

    def __init__(self, alpha: float = 0.5, reset_px: float = 60.0) -> None:
        self.alpha = alpha
        self.reset_px = reset_px
        self.corners: np.ndarray | None = None

    def update(self, corners: np.ndarray | None) -> np.ndarray | None:
        if corners is None:
            self.corners = None
        elif self.corners is None or np.abs(corners - self.corners).max() > self.reset_px:
            self.corners = corners.copy()
        else:
            self.corners = self.alpha * corners + (1 - self.alpha) * self.corners
        return self.corners
