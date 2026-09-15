"""engine.llm 테스트 — requests.post mock 으로 chat 파싱·재시도·json_mode·키 비노출을 확인한다."""
from __future__ import annotations
import json

import pytest
import requests

from engine import llm as llm_mod
from engine.llm import LLMClient, LLMError

KEY = "sk-or-v1-SECRETSECRETSECRET0000"


class FakeResp:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text if text else (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def ok_payload(content="안녕", tool_calls=None, usage=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"id": "x", "model": "test/model", "choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": usage or {"prompt_tokens": 12, "completion_tokens": 3, "cost": 0.00042}}


@pytest.fixture
def client(monkeypatch):
    c = LLMClient(base_url="https://example.test/api/v1", api_key=KEY, model="test/model", temperature=0.1)
    c.backoff_base = 0
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    return c


def test_chat_parses_content_usage_cost(monkeypatch, client):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update({"url": url, "headers": headers, "body": json, "timeout": timeout})
        return FakeResp(200, ok_payload("결과 문장"))

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    r = client.chat([{"role": "user", "content": "hi"}])
    assert r.content == "결과 문장"
    assert r.tool_calls == []
    assert r.tokens_in == 12 and r.tokens_out == 3
    assert r.cost_usd == pytest.approx(0.00042)
    assert sent["url"] == "https://example.test/api/v1/chat/completions"
    assert sent["headers"]["Authorization"] == f"Bearer {KEY}"
    assert sent["headers"]["HTTP-Referer"] and sent["headers"]["X-Title"]
    body = sent["body"]
    assert body["model"] == "test/model" and body["temperature"] == 0.1
    assert body["usage"] == {"include": True}
    assert "tools" not in body and "response_format" not in body


def test_chat_tools_json_mode_extra(monkeypatch, client):
    sent = {}
    tc = [{"id": "call_1", "type": "function", "function": {"name": "web_search", "arguments": "{\"query\": \"q\"}"}}]

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["body"] = json
        return FakeResp(200, ok_payload(None, tool_calls=tc))

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    tools = [{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object"}}}]
    r = client.chat([{"role": "user", "content": "x"}], tools=tools, json_mode=True, model="other/model",
                    extra={"plugins": [{"id": "web"}]})
    assert r.content == ""  # None → 빈 문자열
    assert r.tool_calls == tc
    b = sent["body"]
    assert b["tools"] == tools and b["tool_choice"] == "auto"
    assert b["response_format"] == {"type": "json_object"}
    assert b["model"] == "other/model"
    assert b["plugins"] == [{"id": "web"}]


def test_retry_on_429_then_success(monkeypatch, client):
    seq = [FakeResp(429, text="rate limited"), FakeResp(503, text="busy"), FakeResp(200, ok_payload("ok"))]
    n = {"calls": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        n["calls"] += 1
        return seq.pop(0)

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    assert client.chat([{"role": "user", "content": "x"}]).content == "ok"
    assert n["calls"] == 3


def test_retry_exhausted_raises_without_key(monkeypatch, client):
    n = {"calls": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        n["calls"] += 1
        return FakeResp(500, text=f"server error echo {KEY}")

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "x"}])
    assert n["calls"] == llm_mod.MAX_RETRIES + 1
    assert KEY not in str(ei.value)


def test_4xx_no_retry_and_key_scrubbed(monkeypatch, client):
    n = {"calls": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        n["calls"] += 1
        return FakeResp(401, text=f"invalid key {KEY}")

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "x"}])
    assert n["calls"] == 1
    assert "401" in str(ei.value) and KEY not in str(ei.value)


def test_network_error_is_llmerror(monkeypatch, client):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.ConnectionError(f"boom {KEY}")

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "x"}])
    assert KEY not in str(ei.value)


def test_error_body_without_choices(monkeypatch, client):
    monkeypatch.setattr(llm_mod.requests, "post",
                        lambda *a, **k: FakeResp(200, {"error": {"message": "model not found"}}))
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "x"}])
    assert "model not found" in str(ei.value)


def test_list_models_and_ping(monkeypatch, client):
    monkeypatch.setattr(llm_mod.requests, "get", lambda *a, **k: FakeResp(200, {"data": [
        {"id": "a/b", "name": "AB", "context_length": 128000, "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]}))
    models = client.list_models()
    assert models == [{"id": "a/b", "name": "AB", "context_length": 128000,
                       "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["body"] = json
        return FakeResp(200, ok_payload("p"))

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    ok, detail = client.ping()
    assert ok and "test/model" in detail
    assert sent["body"]["max_tokens"] == 1
    empty = LLMClient(base_url="https://x", api_key="", model="m")
    assert empty.ping()[0] is False
