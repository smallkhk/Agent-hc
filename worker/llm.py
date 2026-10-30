"""Optional second opinion on hack-menu flags from Claude (vision).

Off unless LLM_SECOND_OPINION=true. Only flagged frames are sent (the flattened game screen),
at most one request per session every LLM_MIN_INTERVAL_SEC. The verdict is attached to the
alert; it never decides anything on its own.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass

import anthropic
import cv2
import numpy as np

log = logging.getLogger("worker.llm")

VERDICTS = ["hack_menu", "esp_overlay", "other_overlay", "normal_gameplay", "game_menu", "unclear"]

PROMPT = """This is a photo of a Call of Duty: Mobile game screen, taken by a second camera and flattened.
An automatic classifier flagged it as possibly showing "{flag}" (confidence {score:.2f}).

Judge only what is visible on the game screen:
- hack_menu: a third-party mod/cheat menu (toggle lists like aimbot, wallhack, ESP, speed)
- esp_overlay: boxes, lines, names or distances drawn over enemies by a cheat
- other_overlay: some other non-game overlay (screen recorder bubble, chat head, notification)
- normal_gameplay: ordinary CODM gameplay HUD
- game_menu: CODM's own menus (lobby, loadout, settings, scoreboard)
- unclear: too blurry, dark or obstructed to tell

Hands, glare and camera blur are expected. Give a short reason naming what you see."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Verdict:
    verdict: str
    confidence: float
    reason: str

    def text(self) -> str:
        return f"{self.verdict} ({self.confidence:.0%}): {self.reason}"


class SecondOpinion:
    def __init__(self, api_key: str | None, model: str, min_interval_sec: float) -> None:
        # No key in env → the SDK's own credential resolution (ANTHROPIC_API_KEY, `ant auth login`, ...).
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()
        self.model = model
        self.min_interval = min_interval_sec
        self.last_call: dict[int, float] = {}

    def allowed(self, session_id: int) -> bool:
        """Per-session rate limit; claims the slot when allowed."""
        now = time.monotonic()
        if now - self.last_call.get(session_id, -1e9) < self.min_interval:
            return False
        self.last_call[session_id] = now
        return True

    def forget(self, session_id: int) -> None:
        self.last_call.pop(session_id, None)

    async def judge(self, flat_bgr: np.ndarray, flag: str, score: float) -> Verdict | None:
        ok, jpg = cv2.imencode(".jpg", flat_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=4096,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                # A declined request is re-run on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.standard_b64encode(jpg.tobytes()).decode()}},
                        {"type": "text", "text": PROMPT.format(flag=flag, score=score)},
                    ],
                }],
            )
        except anthropic.RateLimitError:
            log.warning("second opinion rate limited; skipping")
            return None
        except anthropic.APIStatusError as err:
            log.error("second opinion failed (%s): %s", err.status_code, err.message)
            return None
        except anthropic.APIConnectionError as err:
            log.error("second opinion unreachable: %s", err)
            return None

        if response.stop_reason == "refusal":
            return Verdict("unclear", 0.0, "the model declined to judge this image")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
            return Verdict(data["verdict"], float(data["confidence"]), data["reason"][:300])
        except (ValueError, KeyError, TypeError):
            log.error("second opinion: unexpected output (stop_reason=%s)", response.stop_reason)
            return None
