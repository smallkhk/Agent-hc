"""Worker settings, from env only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from worker.detect.screen import ScreenParams


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        raise RuntimeError(f"missing env: {name}")
    return value


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


@dataclass(frozen=True)
class Config:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    api_url: str
    worker_secret: str
    storage_dir: Path
    sample_fps: float
    record_fps: float
    freeze_diff: float
    loop_match_run: int
    screen: ScreenParams
    poll_sec: float = 5.0
    heartbeat_sec: float = 10.0


def load() -> Config:
    return Config(
        # Same host as LiveKit: skip Nginx/TLS.
        livekit_url=_env("LIVEKIT_INTERNAL_URL", "ws://127.0.0.1:7880"),
        livekit_api_key=_env("LIVEKIT_API_KEY"),
        livekit_api_secret=_env("LIVEKIT_API_SECRET"),
        api_url=_env("API_INTERNAL_URL", f"http://127.0.0.1:{os.environ.get('PORT') or 3000}").rstrip("/"),
        worker_secret=_env("WORKER_SECRET"),
        storage_dir=Path(_env("STORAGE_DIR")),
        sample_fps=_float("SAMPLE_FPS", 2),
        record_fps=_float("RECORD_FPS", 15),
        freeze_diff=_float("FREEZE_DIFF", 0.3),
        loop_match_run=int(_float("LOOP_MATCH_RUN", 20)),
        screen=ScreenParams(
            edge_margin_px=int(_float("EDGE_MARGIN_PX", 8)),
            min_area=_float("MIN_SCREEN_AREA", 0.15),
            aspect_min=_float("SCREEN_ASPECT_MIN", 1.3),
            aspect_max=_float("SCREEN_ASPECT_MAX", 2.3),
            min_brightness=_float("MIN_BRIGHTNESS", 40),
        ),
    )
