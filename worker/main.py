"""Vision worker: one asyncio task per live session. Run: python -m worker.main"""

from __future__ import annotations

import asyncio
import logging
import signal

from worker import config as config_mod
from worker.api_client import ApiClient
from worker.detect.menu import MenuClassifier
from worker.llm import SecondOpinion
from worker.session import SessionWatcher

log = logging.getLogger("worker")


class Supervisor:
    def __init__(self) -> None:
        self.cfg = config_mod.load()
        self.client = ApiClient(self.cfg)
        self.menu = MenuClassifier.load(self.cfg.menu_model)  # one ONNX session for every watcher
        self.llm = (
            SecondOpinion(self.cfg.llm_api_key, self.cfg.llm_model, self.cfg.llm_min_interval_sec)
            if self.cfg.llm_enabled else None
        )
        self.watchers: dict[int, tuple[SessionWatcher, asyncio.Task[None]]] = {}
        self.stopping = asyncio.Event()

    async def sync_sessions(self) -> None:
        """Start watchers for live sessions, stop ones that ended. Also how sessions resume after a restart."""
        index, count = self.cfg.shard
        sessions = {s["id"]: s for s in await self.client.active_sessions() if s["id"] % count == index}
        for sid, info in sessions.items():
            entry = self.watchers.get(sid)
            if entry and not entry[1].done():
                entry[0].update_thresholds(info["thresholds"])
                continue
            watcher = SessionWatcher(info, self.cfg, self.client, self.menu, self.llm)
            task = asyncio.create_task(watcher.run(), name=f"session-{sid}")
            task.add_done_callback(lambda t, sid=sid: self._on_done(sid, t))
            self.watchers[sid] = (watcher, task)
        for sid in list(self.watchers):
            if sid not in sessions:
                self.watchers[sid][0].stop()

    def _on_done(self, sid: int, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception():
            log.error("session %s watcher crashed: %r (will retry)", sid, task.exception())
        entry = self.watchers.get(sid)
        if entry and entry[1] is task:
            del self.watchers[sid]

    async def heartbeat(self) -> None:
        beats = [w.take_heartbeat() for w, _ in self.watchers.values()]
        await self.client.heartbeat(beats)

    async def _every(self, seconds: float, fn) -> None:  # type: ignore[no-untyped-def]
        while not self.stopping.is_set():
            try:
                await fn()
            except Exception as err:  # noqa: BLE001 - API may be restarting; keep going
                log.warning("%s failed: %s", fn.__name__, err)
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stopping.set)
        log.info("worker %d/%d started (%.1f fps sampling)", *self.cfg.shard, self.cfg.sample_fps)
        await asyncio.gather(self._every(self.cfg.poll_sec, self.sync_sessions),
                             self._every(self.cfg.heartbeat_sec, self.heartbeat))
        for watcher, _ in self.watchers.values():
            watcher.stop()
        await asyncio.gather(*(t for _, t in self.watchers.values()), return_exceptions=True)
        await self.client.close()


async def _amain() -> None:
    await Supervisor().run()  # built inside the loop: aiohttp needs a running loop


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
