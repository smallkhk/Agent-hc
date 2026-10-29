"""HTTP client for the Node API's /internal endpoints."""

from __future__ import annotations

from typing import Any

import aiohttp

from worker.config import Config


class ApiClient:
    def __init__(self, cfg: Config) -> None:
        self.base = cfg.api_url
        self.http = aiohttp.ClientSession(
            headers={"authorization": f"Bearer {cfg.worker_secret}"},
            timeout=aiohttp.ClientTimeout(total=10),
        )

    async def _request(self, method: str, path: str, body: Any = None) -> Any:
        async with self.http.request(method, f"{self.base}{path}", json=body) as res:
            res.raise_for_status()
            return await res.json() if res.status != 204 else None

    async def active_sessions(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/internal/sessions"))["sessions"]

    async def heartbeat(self, sessions: list[dict[str, Any]]) -> None:
        await self._request("POST", "/internal/heartbeat", {"sessions": sessions})

    async def event(self, body: dict[str, Any]) -> None:
        await self._request("POST", "/internal/events", body)

    async def close(self) -> None:
        await self.http.close()
