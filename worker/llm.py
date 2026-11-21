"""Optional second opinion on hack-menu flags from Gemini (vision).

Off unless LLM_SECOND_OPINION=true. Only flagged frames are sent (the flattened game screen), at most
one request per session every LLM_MIN_INTERVAL_SEC, through the Gemini API (generateContent; the
Flash-Lite models have a free tier with an AI Studio key). The verdict is attached to the alert. With
LLM_AUTO_DISMISS, a confident "not a cheat" verdict also marks the alert a false positive; admins can
still overrule it, and it never becomes a training label.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import aiohttp
import cv2
import numpy as np

log = logging.getLogger("worker.llm")

VERDICTS = ["hack_menu", "esp_overlay", "other_overlay", "normal_gameplay", "game_menu", "unclear"]
NOT_A_CHEAT = ("normal_gameplay", "game_menu")

PROMPT = """This is a photo of a Call of Duty: Mobile game screen, taken by a second camera and flattened.
An automatic classifier flagged it as possibly showing "{flag}" (confidence {score:.2f}).

Judge only what is visible on the game screen:
- hack_menu: a third-party mod/cheat menu (toggle lists like aimbot, wallhack, ESP, speed, "key remaining")
- esp_overlay: boxes, lines, names or distances drawn over enemies by a cheat; also a cheat's brand watermark
  (e.g. a small red "CLOUD" at the top) or a thin aim circle (FOV) drawn over the game or its menus
- other_overlay: some other non-game overlay (screen recorder bubble, chat head, notification)
- normal_gameplay: ordinary CODM gameplay HUD
- game_menu: CODM's own menus (lobby, loadout, settings, scoreboard; CODM's own "Cloud Sensitivity" screen is a game menu)
- unclear: too blurry, dark or obstructed to tell

Hands, glare and camera blur are expected. Give a short reason naming what you see.

Reply with only a JSON object, no other text:
{{"verdict": one of {verdicts}, "confidence": a number from 0 to 1, "reason": "short reason"}}"""


@dataclass(frozen=True)
class Verdict:
    verdict: str
    confidence: float
    reason: str

    def text(self) -> str:
        return f"{self.verdict} ({self.confidence:.0%}): {self.reason}"

    def dismisses(self, min_confidence: float) -> bool:
        """Confident that the flagged frame shows no cheat."""
        return self.verdict in NOT_A_CHEAT and self.confidence >= min_confidence


def parse_verdict(text: str) -> Verdict | None:
    """The verdict JSON, also when the model wraps it in prose or a code fence."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0) if match else text)
        verdict = str(data["verdict"])
        if verdict not in VERDICTS:
            return None
        return Verdict(verdict, max(0.0, min(1.0, float(data["confidence"]))), str(data["reason"])[:300])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


class SecondOpinion:
    def __init__(self, api_key: str | None, model: str, min_interval_sec: float) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.min_interval = min_interval_sec
        self.last_call: dict[int, float] = {}
        self.base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
        self.http: aiohttp.ClientSession | None = None

    def allowed(self, session_id: int) -> bool:
        """Per-session rate limit; claims the slot when allowed."""
        now = time.monotonic()
        if now - self.last_call.get(session_id, -1e9) < self.min_interval:
            return False
        self.last_call[session_id] = now
        return True

    def forget(self, session_id: int) -> None:
        self.last_call.pop(session_id, None)

    async def close(self) -> None:
        if self.http:
            await self.http.close()

    async def judge(self, flat_bgr: np.ndarray, flag: str, score: float) -> Verdict | None:
        ok, jpg = cv2.imencode(".jpg", flat_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        self.http = self.http or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        body = {"contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.standard_b64encode(jpg.tobytes()).decode()}},
            {"text": PROMPT.format(flag=flag, score=score, verdicts=json.dumps(VERDICTS))},
        ]}]}
        url = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
        try:
            async with self.http.post(url, json=body, headers={"x-goog-api-key": self.api_key}) as r:
                data = await r.json(content_type=None)
                if r.status == 429:
                    log.warning("second opinion rate limited (Gemini free-tier quota?); skipping")
                    return None
                if r.status >= 400:
                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    log.error("second opinion failed (%s): %s", r.status, str(error.get("message", ""))[:200])
                    return None
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            log.error("second opinion unreachable: %s", err)
            return None

        candidates = data.get("candidates") or [] if isinstance(data, dict) else []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text:  # blocked or empty: say so rather than guess
            return Verdict("unclear", 0.0, "the model gave no answer for this image")
        verdict = parse_verdict(text)
        if verdict is None:
            log.error("second opinion: unexpected output: %s", text[:200])
        return verdict
