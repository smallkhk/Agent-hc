"""Rule: cheat text on screen, read with an offline OCR model (RapidOCR, ONNX, no network).

Cheat menus and loaders write words no CODM screen has (Aimbot, ESP Box, Hit Magic, Key remaining,
a cheat's brand watermark such as a standalone "CLOUD"), and modded builds come through sideloading or
modding apps (TestFlight, ESign, GBox, Lucky Patcher, ...) or show as a second Call of Duty app.
Reading takes ~1-2 s on one CPU core, so the session reads a screen every few seconds, and only one
read runs at a time on the whole worker.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("worker.text")

CHEAT_TEXT = "cheat_text"
SIDELOAD_APP = "sideload_app"
DUPLICATE_CODM = "duplicate_codm"

# Matched against each text item lowercased with spaces and punctuation removed ("Enable AimBot" → "enableaimbot").
# Left out on purpose because CODM itself uses them: "aim assist", "auto fire", "fov" on its own, "recoil",
# "rapid fire" and "one shot one kill" (game modes), "fast reload", "radar", "unlock", "skins", "speed",
# and power-up / mode words such as "infinite ammo", "instant kill", "teleport".
CHEAT_WORDS = [
    # aim
    "aimbot", "silentaim", "aimlock", "headlock", "autoheadshot", "autoaim", "aimkey", "aimfov",
    "sizefov", "drawfov", "closeaimfov", "fovcircle", "smoothaim", "aimsmooth", "smoothlock", "distanceaim",
    "aimdistance", "aimbone", "targetbone", "bonetarget", "aimtarget", "aimprediction", "aimmagnet", "bulletmagnet",
    "magicbullet", "hitmagic", "bullettrack", "bullettracking", "triggerbot", "autoshoot", "ignoreknocked",
    # visuals
    "wallhack", "chams", "espbox", "espline", "espname", "espskeleton", "espdistance", "esphealth", "espweapon",
    "espitem", "esploot", "espvehicle", "espgrenade", "espteam", "espenemy", "enableesp", "espenabled", "boxesp",
    "lineesp", "skeletonesp", "nameesp", "healthesp", "distanceesp", "itemesp", "radarhack", 
    "seethroughwall",
    # weapon and movement
    "norecoil", "nospread", "noreload", "godmode", "damagehack",
    "speedhack", "flyhack", "superjump", "noclip", "wallclimb", "undergroundmode",
    # loaders, keys, menus
    "injector", "injected", "injectsuccess", "keyremaining", "enterkey", "keyexpired", "licensekey", "activationkey",
    "keysystem", "vipkey", "antiban", "antireport", "anticheatbypass", "modmenu", "cheatmenu", "hackmenu",
    # cheat tools
    "gameguardian",
]
# Brand watermarks: only as the whole text item, so CODM's own "Cloud Sensitivity Management" never matches.
CHEAT_BRANDS = {"cloud", "cloudengine"}
# Sideloading / modding apps: a modded build is installed or run through these (warning, not proof).
SIDELOAD_WORDS = ["testflight", "altstore", "trollstore", "sideloadly", "ksign", "gbox", "appdb",
                  "luckypatcher", "parallelspace", "virtualspace", "vmos", "magisk", "lsposed", "xposed"]
SIDELOAD_LABELS = {"esign", "scarlet", "feather"}  # only as a whole app label ("esign" hides in "design")
CODM_APP = re.compile(r"callofduty|codmobile|^codm$")
MIN_CONFIDENCE = 0.6


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Finding:
    type: str  # CHEAT_TEXT | SIDELOAD_APP | DUPLICATE_CODM
    words: tuple[str, ...]  # what was read, as shown to admins

    def detail(self) -> str:
        return "Text on screen: " + ", ".join(f'"{w}"' for w in self.words)[:280]


def classify(texts: list[str]) -> list[Finding]:
    cheat: list[str] = []
    sideload: list[str] = []
    codm_apps: list[str] = []
    for text in texts:
        n = _norm(text)
        if not n:
            continue
        if any(w in n for w in CHEAT_WORDS) or n in CHEAT_BRANDS or (n == "esp" and text.strip().isupper()):
            cheat.append(text.strip())
        if any(w in n for w in SIDELOAD_WORDS) or n in SIDELOAD_LABELS:
            sideload.append(text.strip())
        if CODM_APP.search(n):
            codm_apps.append(text.strip())
    findings = []
    if cheat:
        findings.append(Finding(CHEAT_TEXT, tuple(dict.fromkeys(cheat))))
    if sideload:
        findings.append(Finding(SIDELOAD_APP, tuple(dict.fromkeys(sideload))))
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
