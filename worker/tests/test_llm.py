import asyncio
import json

import numpy as np
import pytest
from aiohttp import web

from worker.llm import SecondOpinion


def message(text=None, stop_reason="end_turn"):
    content = [{"type": "text", "text": text}] if text is not None else []
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


async def with_mock(reply, fn):
    seen = []

    async def handler(request):
        seen.append({"headers": dict(request.headers), "body": await request.json()})
        status, payload = reply()
        return web.json_response(payload, status=status)

    app = web.Application()
    app.router.add_post("/v1/messages", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        return await fn(f"http://127.0.0.1:{port}"), seen
    finally:
        await runner.cleanup()


@pytest.fixture
def frame():
    img = np.zeros((224, 448, 3), np.uint8)
    img[:, :150] = (30, 30, 30)
    return img


def opinion(base_url, monkeypatch, interval=60):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)
    return SecondOpinion("test-key", "claude-opus-5-5", interval)


def test_verdict_and_request_shape(frame, monkeypatch):
    verdict = {"verdict": "hack_menu", "confidence": 0.93, "reason": "Toggle list with aimbot and ESP entries."}

    async def go(url):
        return await opinion(url, monkeypatch).judge(frame, "mod_menu", 0.91)

    v, seen = asyncio.run(with_mock(lambda: (200, message(json.dumps(verdict))), go))
    assert v.verdict == "hack_menu" and v.confidence == pytest.approx(0.93)
    assert v.text().startswith("hack_menu (93%)")
    body, headers = seen[0]["body"], seen[0]["headers"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    image = body["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert "mod_menu" in body["messages"][0]["content"][1]["text"]


def test_refusal_is_reported_as_unclear(frame, monkeypatch):
    async def go(url):
        return await opinion(url, monkeypatch).judge(frame, "mod_menu", 0.9)

    v, _ = asyncio.run(with_mock(lambda: (200, message(stop_reason="refusal")), go))
    assert v.verdict == "unclear"


def test_api_error_gives_no_verdict(frame, monkeypatch):
    async def go(url):
        o = opinion(url, monkeypatch)
        o.client = o.client.with_options(max_retries=0)
        return await o.judge(frame, "mod_menu", 0.9)

    err = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    v, _ = asyncio.run(with_mock(lambda: (400, err), go))
    assert v is None


def test_rate_limit_per_session(monkeypatch):
    o = SecondOpinion("k", "claude-opus-5-5", min_interval_sec=60)
    assert o.allowed(1) and not o.allowed(1)
    assert o.allowed(2)
    o.forget(1)
    assert o.allowed(1)
