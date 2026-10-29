"""One watcher per live session: joins the LiveKit room, samples the player's camera and runs the rules."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from livekit import api, rtc

from worker.api_client import ApiClient
from worker.config import Config
from worker.detect import integrity
from worker.detect import screen as screen_mod
from worker.rules import EscalatingRule, Event

log = logging.getLogger("worker.session")

PLAYER = "player"
SCREEN_TOPIC = "handcam.screen"
STATUS_EVERY_SEC = 3.0
RECONNECT_LOG_AFTER_SEC = 2.0

# Shown on the player's cam page under the guide box.
PLAYER_HINTS = {
    screen_mod.NOT_FOUND: "Can't see your screen. Fit it inside the box",
    screen_mod.CUT_OFF: "Part of your screen is outside the frame",
    screen_mod.TOO_SMALL: "Move the camera closer to your screen",
    screen_mod.DARK: "Your screen is too dark. Turn up the brightness",
    screen_mod.GLARE: "Glare on the screen. Tilt the camera or move the light",
}


def frame_to_bgr(frame: rtc.VideoFrame) -> np.ndarray:
    rgb = frame.convert(rtc.VideoBufferType.RGB24)
    arr = np.frombuffer(rgb.data, dtype=np.uint8).reshape(rgb.height, rgb.width, 3)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


class SessionWatcher:
    def __init__(self, info: dict[str, Any], cfg: Config, client: ApiClient) -> None:
        self.id: int = info["id"]
        self.room_name: str = info["room"]
        self.cfg = cfg
        self.client = client
        t = info["thresholds"]
        self.screen_rule = EscalatingRule(t["graceSec"], t["violationSec"])
        self.glare_rule = EscalatingRule(t["graceSec"], None)  # glare only ever warns
        self.freeze_rule = EscalatingRule(None, t["freezeSec"])
        self.drop_rule = EscalatingRule(None, t["dropSec"])
        self.freeze = integrity.FreezeDetector(cfg.freeze_diff)
        self.smoother = screen_mod.CornerSmoother()

        self.room = rtc.Room()
        self.frame: rtc.VideoFrame | None = None
        self.frame_seq = 0
        self.track_present = False
        self.track_lost_at: float | None = None
        self.uptime_delta = 0.0
        self.last_hint: tuple[bool, str | None] | None = None
        self.last_hint_at = 0.0
        self._stop = asyncio.Event()
        self._reader: asyncio.Task[None] | None = None

    # --- lifecycle -------------------------------------------------------------------

    def update_thresholds(self, t: dict[str, Any]) -> None:
        self.screen_rule.warn_sec, self.screen_rule.violation_sec = t["graceSec"], t["violationSec"]
        self.glare_rule.warn_sec = t["graceSec"]
        self.freeze_rule.violation_sec = t["freezeSec"]
        self.drop_rule.violation_sec = t["dropSec"]

    def stop(self) -> None:
        self._stop.set()

    def take_heartbeat(self) -> dict[str, Any]:
        delta, self.uptime_delta = self.uptime_delta, 0.0
        return {"id": self.id, "connected": self.track_present, "uptimeDeltaSec": round(delta, 1)}

    async def run(self) -> None:
        token = (
            api.AccessToken(self.cfg.livekit_api_key, self.cfg.livekit_api_secret)
            .with_identity(f"worker-{self.id}")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self.room_name,
                    hidden=True,
                    can_publish=False,
                    can_publish_data=True,  # guide box feedback to the player
                    can_subscribe=True,
                )
            )
            .to_jwt()
        )
        self.room.on("track_subscribed", self._on_track_subscribed)
        self.room.on("track_unsubscribed", self._on_track_gone)
        self.room.on("participant_disconnected", lambda p: p.identity == PLAYER and self._on_track_gone())
        # LiveKit creates the room on join; the worker may get there before the player.
        await self.room.connect(self.cfg.livekit_url, token, rtc.RoomOptions(auto_subscribe=True))
        log.info("session %s: watching %s", self.id, self.room_name)
        try:
            await self._loop()
        finally:
            if self._reader:
                self._reader.cancel()
            await self.room.disconnect()
            log.info("session %s: stopped", self.id)

    # --- LiveKit callbacks -------------------------------------------------------------

    def _on_track_subscribed(self, track: rtc.Track, _pub: Any, participant: rtc.RemoteParticipant) -> None:
        if participant.identity != PLAYER or track.kind != rtc.TrackKind.KIND_VIDEO:
            return
        if self._reader:
            self._reader.cancel()
        self._reader = asyncio.create_task(self._read_frames(track))
        if self.track_lost_at is not None and time.monotonic() - self.track_lost_at >= RECONNECT_LOG_AFTER_SEC:
            asyncio.create_task(self._emit([Event(integrity.STREAM_RECONNECTED, "info")], None))
        self.track_present = True
        self.track_lost_at = None
        self.freeze.reset()

    def _on_track_gone(self, *_: Any) -> None:
        if self.track_present:
            self.track_present = False
            self.track_lost_at = time.monotonic()
            self.frame = None
            self.smoother.update(None)

    async def _read_frames(self, track: rtc.Track) -> None:
        # capacity=1: keep only the newest frame; we sample far below the stream's fps.
        stream = rtc.VideoStream(track, capacity=1)
        try:
            async for ev in stream:
                self.frame = ev.frame
                self.frame_seq += 1
        finally:
            await stream.aclose()

    # --- sampling loop -------------------------------------------------------------------

    async def _loop(self) -> None:
        period = 1.0 / self.cfg.sample_fps
        seen_seq = 0
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            started = time.monotonic()
            events: list[Event] = []
            snapshot: np.ndarray | None = None

            events += self.drop_rule.update(not self.track_present, started, integrity.STREAM_DROPPED)
            if self.track_present:
                frame, seq = self.frame, self.frame_seq
                if frame is not None and seq != seen_seq:
                    seen_seq = seq
                    snapshot = await loop.run_in_executor(None, frame_to_bgr, frame)
                    result, diff = await loop.run_in_executor(None, self._analyse, snapshot)
                    static = self.freeze.is_static(diff)
                    self.uptime_delta += period
                    events += self._screen_events(result, started)
                    await self._send_hint(result, started)
                else:
                    static = True  # no new frame since the last sample: the feed stalled
                events += self.freeze_rule.update(static, started, integrity.FEED_FROZEN)

            if events:
                await self._emit(events, snapshot)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, period - (time.monotonic() - started)))
            except asyncio.TimeoutError:
                pass

    def _analyse(self, bgr: np.ndarray) -> tuple[screen_mod.ScreenResult, float]:
        result = screen_mod.detect_screen(bgr, self.cfg.screen)
        self.smoother.update(result.corners)
        return result, self.freeze.update(bgr)

    def _screen_events(self, r: screen_mod.ScreenResult, now: float) -> list[Event]:
        glare = r.reason == screen_mod.GLARE
        screen_failing = not r.ok and not glare
        score = round(r.area_frac, 3) if r.corners is not None else None
        return self.screen_rule.update(screen_failing, now, r.reason or "", score) + self.glare_rule.update(
            glare, now, screen_mod.GLARE, round(r.glare_frac, 3)
        )

    async def _send_hint(self, r: screen_mod.ScreenResult, now: float) -> None:
        hint = (r.ok, r.reason)
        if hint == self.last_hint and now - self.last_hint_at < STATUS_EVERY_SEC:
            return
        self.last_hint, self.last_hint_at = hint, now
        payload = json.dumps({"ok": r.ok, "reason": PLAYER_HINTS.get(r.reason or "")})
        try:
            await self.room.local_participant.publish_data(
                payload, reliable=True, topic=SCREEN_TOPIC, destination_identities=[PLAYER]
            )
        except Exception as err:  # noqa: BLE001 - feedback is best effort
            log.debug("session %s: hint not sent: %s", self.id, err)

    async def _emit(self, events: list[Event], snapshot: np.ndarray | None) -> None:
        ts_ms = int(time.time() * 1000)
        frame_path = None
        if snapshot is not None and any(e.severity != "info" for e in events):
            frame_path = await asyncio.get_running_loop().run_in_executor(
                None, self._save_frame, snapshot, ts_ms, events[0].type
            )
        for e in events:
            body = {"sessionId": self.id, "type": e.type, "severity": e.severity, "score": e.score,
                    "ts": ts_ms, "framePath": frame_path}
            log.info("session %s: %s %s", self.id, e.severity, e.type)
            try:
                await self.client.event(body)
            except Exception as err:  # noqa: BLE001
                log.error("session %s: event %s not delivered: %s", self.id, e.type, err)

    def _save_frame(self, bgr: np.ndarray, ts_ms: int, event_type: str) -> str:
        rel = Path("frames") / str(self.id) / f"{ts_ms}_{event_type}.jpg"
        path = self.cfg.storage_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        img = bgr.copy()
        corners = self.smoother.corners
        if corners is not None:
            cv2.polylines(img, [corners.astype(np.int32)], True, (0, 200, 0), 2)
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return rel.as_posix()
