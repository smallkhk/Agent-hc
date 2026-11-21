import asyncio
import json

import numpy as np
import pytest
from aiohttp import web

from worker.llm import GeminiOpinion, SecondOpinion, Verdict, parse_verdict


def message(text=None, stop_reason="end_turn"):
    content = [{"type": "text", "text": text}] if text is not None else []
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


async def with_mock(reply, fn, path="/v1/messages"):
    seen = []

    async def handler(request):
        seen.append({"headers": dict(request.headers), "body": await request.json()})
        status, payload = reply()
        return web.json_response(payload, status=status)

    app = web.Application()
    app.router.add_post(path, handler)
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


# --- Gemini ------------------------------------------------------------------------------------

GEMINI_PATH = "/v1beta/models/gemini-3.5-flash-lite:generateContent"


def gemini_reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP", "index": 0}]}


def gemini(base_url, monkeypatch):
    monkeypatch.setenv("GEMINI_BASE_URL", base_url)
    return GeminiOpinion("gemini-key", "gemini-3.5-flash-lite", 60)


def run_gemini(frame, monkeypatch, reply):
    async def go(url):
        o = gemini(url, monkeypatch)
        try:
            return await o.judge(frame, "mod_menu", 0.91)
        finally:
            await o.http.close()

    return asyncio.run(with_mock(reply, go, GEMINI_PATH))


def test_gemini_request_shape_and_verdict(frame, monkeypatch):
    verdict = {"verdict": "hack_menu", "confidence": 0.9, "reason": "Toggle list: Aimbot, ESP Box."}
    v, seen = run_gemini(frame, monkeypatch, lambda: (200, gemini_reply(json.dumps(verdict))))
    assert v.verdict == "hack_menu" and not v.dismisses(0.85)
    assert seen[0]["headers"]["x-goog-api-key"] == "gemini-key"
    parts = seen[0]["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[0]["inline_data"]["data"]
    assert "mod_menu" in parts[1]["text"] and "JSON" in parts[1]["text"]


def test_gemini_json_in_a_code_fence_and_dismissal(frame, monkeypatch):
    text = 'Here you go:\n```json\n{"verdict": "normal_gameplay", "confidence": 0.95, "reason": "CODM HUD only."}\n```'
    v, _ = run_gemini(frame, monkeypatch, lambda: (200, gemini_reply(text)))
    assert v.verdict == "normal_gameplay" and v.dismisses(0.85)


def test_gemini_blocked_or_empty_is_unclear(frame, monkeypatch):
    v, _ = run_gemini(frame, monkeypatch, lambda: (200, {"candidates": [], "promptFeedback": {"blockReason": "OTHER"}}))
    assert v.verdict == "unclear" and not v.dismisses(0.0)


def test_gemini_errors_give_no_verdict(frame, monkeypatch):
    v, _ = run_gemini(frame, monkeypatch, lambda: (429, {"error": {"code": 429, "message": "quota"}}))
    assert v is None
    v, _ = run_gemini(frame, monkeypatch, lambda: (400, {"error": {"code": 400, "message": "API key not valid"}}))
    assert v is None


def test_dismiss_rules():
    assert Verdict("game_menu", 0.9, "").dismisses(0.85)
    assert not Verdict("game_menu", 0.6, "").dismisses(0.85)  # not sure enough
    assert not Verdict("unclear", 0.99, "").dismisses(0.85)
    assert not Verdict("esp_overlay", 0.99, "").dismisses(0.85)
    assert parse_verdict('{"verdict": "made_up", "confidence": 1, "reason": ""}') is None
