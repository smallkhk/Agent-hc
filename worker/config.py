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
    menu_model: Path
    menu_shadow: bool
    llm_enabled: bool
    llm_api_key: str | None
    llm_model: str
    llm_min_interval_sec: float
    screen: ScreenParams
    shard: tuple[int, int] = (0, 1)  # (index, count): this worker watches sessions with id % count == index
    poll_sec: float = 5.0
    heartbeat_sec: float = 10.0


def _shard() -> tuple[int, int]:
    raw = os.environ.get("WORKER_SHARD") or "0/1"
    index, count = (int(x) for x in raw.split("/"))
    if not 0 <= index < count:
        raise RuntimeError(f"WORKER_SHARD must be i/N with 0 <= i < N, got {raw}")
    return index, count


def load() -> Config:
    return Config(
        shard=_shard(),
        # LiveKit Cloud: the same wss:// URL players use. Self-hosted on this box: set
        # LIVEKIT_INTERNAL_URL=ws://127.0.0.1:7880 to skip Nginx/TLS.
        livekit_url=_env("LIVEKIT_INTERNAL_URL", os.environ.get("LIVEKIT_URL")),
        livekit_api_key=_env("LIVEKIT_API_KEY"),
        livekit_api_secret=_env("LIVEKIT_API_SECRET"),
        api_url=_env("API_INTERNAL_URL", f"http://127.0.0.1:{os.environ.get('PORT') or 3000}").rstrip("/"),
        worker_secret=_env("WORKER_SECRET"),
        storage_dir=Path(_env("STORAGE_DIR")),
        sample_fps=_float("SAMPLE_FPS", 2),
        record_fps=_float("RECORD_FPS", 15),
        freeze_diff=_float("FREEZE_DIFF", 0.3),
        loop_match_run=int(_float("LOOP_MATCH_RUN", 20)),
        menu_model=Path(_env("MENU_MODEL", str(Path(__file__).parent / "models" / "menu_classifier.onnx"))),
        # Shadow mode: menu flags are stored as info events (no alert) until the model is trusted.
        menu_shadow=_env("MENU_SHADOW", "true").lower() != "false",
        llm_enabled=_env("LLM_SECOND_OPINION", "false").lower() == "true",
        llm_api_key=os.environ.get("LLM_API_KEY") or None,
        llm_model=_env("LLM_MODEL", "claude-opus-5-5"),
        llm_min_interval_sec=_float("LLM_MIN_INTERVAL_SEC", 60),
        screen=ScreenParams(
            edge_margin_px=int(_float("EDGE_MARGIN_PX", 8)),
            min_area=_float("MIN_SCREEN_AREA", 0.15),
            aspect_min=_float("SCREEN_ASPECT_MIN", 1.3),
            aspect_max=_float("SCREEN_ASPECT_MAX", 2.3),
            min_brightness=_float("MIN_BRIGHTNESS", 40),
        ),
    )
