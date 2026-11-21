import asyncio
import json

import numpy as np
import pytest
from aiohttp import web

from worker.llm import SecondOpinion, Verdict, parse_verdict

GEMINI_PATH = "/v1beta/models/gemini-3.5-flash-lite:generateContent"


def gemini_reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP", "index": 0}]}


async def with_mock(reply, fn):
    seen = []

    async def handler(request):
        seen.append({"headers": dict(request.headers), "body": await request.json()})
        status, payload = reply()
        return web.json_response(payload, status=status)

    app = web.Application()
    app.router.add_post(GEMINI_PATH, handler)
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


def judge(frame, monkeypatch, reply):
    async def go(url):
        monkeypatch.setenv("GEMINI_BASE_URL", url)
        o = SecondOpinion("gemini-key", "gemini-3.5-flash-lite", 60)
        try:
            return await o.judge(frame, "mod_menu", 0.91)
        finally:
            await o.close()

    return asyncio.run(with_mock(reply, go))


def test_request_shape_and_verdict(frame, monkeypatch):
    verdict = {"verdict": "hack_menu", "confidence": 0.9, "reason": "Toggle list: Aimbot, ESP Box."}
    v, seen = judge(frame, monkeypatch, lambda: (200, gemini_reply(json.dumps(verdict))))
    assert v.verdict == "hack_menu" and v.confidence == pytest.approx(0.9) and not v.dismisses(0.85)
    assert v.text().startswith("hack_menu (90%)")
    assert seen[0]["headers"]["x-goog-api-key"] == "gemini-key"
    parts = seen[0]["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[0]["inline_data"]["data"]
    assert "mod_menu" in parts[1]["text"] and "JSON" in parts[1]["text"]


def test_json_in_a_code_fence_and_dismissal(frame, monkeypatch):
    text = 'Here you go:\n```json\n{"verdict": "normal_gameplay", "confidence": 0.95, "reason": "CODM HUD only."}\n```'
    v, _ = judge(frame, monkeypatch, lambda: (200, gemini_reply(text)))
    assert v.verdict == "normal_gameplay" and v.dismisses(0.85)


def test_blocked_or_empty_is_unclear(frame, monkeypatch):
    v, _ = judge(frame, monkeypatch, lambda: (200, {"candidates": [], "promptFeedback": {"blockReason": "OTHER"}}))
    assert v.verdict == "unclear" and not v.dismisses(0.0)


def test_errors_give_no_verdict(frame, monkeypatch):
    v, _ = judge(frame, monkeypatch, lambda: (429, {"error": {"code": 429, "message": "quota"}}))
    assert v is None
    v, _ = judge(frame, monkeypatch, lambda: (400, {"error": {"code": 400, "message": "API key not valid"}}))
    assert v is None


def test_unparseable_answer_gives_no_verdict(frame, monkeypatch):
    v, _ = judge(frame, monkeypatch, lambda: (200, gemini_reply("I think it is fine.")))
    assert v is None


def test_dismiss_rules():
    assert Verdict("game_menu", 0.9, "").dismisses(0.85)
    assert not Verdict("game_menu", 0.6, "").dismisses(0.85)  # not sure enough
    assert not Verdict("unclear", 0.99, "").dismisses(0.85)
    assert not Verdict("esp_overlay", 0.99, "").dismisses(0.85)
    assert parse_verdict('{"verdict": "made_up", "confidence": 1, "reason": ""}') is None


def test_rate_limit_per_session():
    o = SecondOpinion("k", "gemini-3.5-flash-lite", min_interval_sec=60)
    assert o.allowed(1) and not o.allowed(1)
    assert o.allowed(2)
    o.forget(1)
    assert o.allowed(1)
