"""Rule: cheat text on screen, read with an offline OCR model (RapidOCR, ONNX, no network).

Cheat menus and loaders write words no CODM screen has (Aimbot, ESP Box, Hit Magic, Key remaining,
a cheat's brand watermark such as a standalone "CLOUD"), and sideloaded builds show up as TestFlight or
a second Call of Duty app on the home screen. Reading takes ~1-2 s on one CPU core, so the session
reads a screen every few seconds, and only one read runs at a time on the whole worker.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("worker.text")

CHEAT_TEXT = "cheat_text"
TESTFLIGHT = "testflight"
DUPLICATE_CODM = "duplicate_codm"

# Matched against each text item lowercased with spaces and punctuation removed ("Enable AimBot" → "enableaimbot").
# Words a legit CODM screen also uses are left out: "aim assist", "auto fire", "fov" on its own, "skins".
CHEAT_WORDS = [
    "aimbot", "silentaim", "aimlock", "triggerbot", "wallhack", "chams", "norecoil", "nospread",
    "magicbullet", "hitmagic", "bullettrack", "speedhack", "flyhack", "radarhack", "antiban",
    "injector", "injected", "modmenu", "cheatmenu", "hackmenu", "keyremaining", "enterkey",
    "aimfov", "sizefov", "drawfov", "closeaimfov", "smoothaim", "smoothlock", "distanceaim",
    "espbox", "espline", "espname", "espskeleton", "espdistance", "esphealth",
]
# Brand watermarks: only as the whole text item, so CODM's own "Cloud Sensitivity Management" never matches.
CHEAT_BRANDS = {"cloud", "cloudengine"}
CODM_APP = re.compile(r"callofduty|codmobile|^codm$")
MIN_CONFIDENCE = 0.6


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Finding:
    type: str  # CHEAT_TEXT | TESTFLIGHT | DUPLICATE_CODM
    words: tuple[str, ...]  # what was read, as shown to admins

    def detail(self) -> str:
        return "Text on screen: " + ", ".join(f'"{w}"' for w in self.words)[:280]


def classify(texts: list[str]) -> list[Finding]:
    cheat: list[str] = []
    testflight: list[str] = []
    codm_apps: list[str] = []
    for text in texts:
        n = _norm(text)
        if not n:
            continue
        if any(w in n for w in CHEAT_WORDS) or n in CHEAT_BRANDS or (n == "esp" and text.strip().isupper()):
            cheat.append(text.strip())
        if "testflight" in n:
            testflight.append(text.strip())
        if CODM_APP.search(n):
            codm_apps.append(text.strip())
    findings = []
    if cheat:
        findings.append(Finding(CHEAT_TEXT, tuple(dict.fromkeys(cheat))))
    if testflight:
        findings.append(Finding(TESTFLIGHT, tuple(dict.fromkeys(testflight))))
    if len(codm_apps) >= 2:  # two app labels: a second (cloned or modded) CODM install
        findings.append(Finding(DUPLICATE_CODM, tuple(codm_apps)))
    return findings


class TextReader:
    """One shared OCR model; reads one screen at a time for the whole worker."""

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # optional dependency: rule off without it

        self.ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self._lock = threading.Lock()

    @classmethod
    def load(cls) -> TextReader | None:
        try:
            reader = cls()
        except Exception as err:  # noqa: BLE001 - a missing/broken OCR package turns the rule off
            log.warning("text reading off: %s", err)
            return None
        log.info("text reading on (offline OCR)")
        return reader

    def busy(self) -> bool:
        return self._lock.locked()

    def read(self, flat_bgr: np.ndarray) -> list[str] | None:
        """Text items on the screen, or None if another read is running (skip this one)."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            result, _ = self.ocr(flat_bgr)
        finally:
            self._lock.release()
        return [item[1] for item in (result or []) if item[2] >= MIN_CONFIDENCE]
