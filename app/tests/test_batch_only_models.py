"""배치 전용 모델을 고를 수 없게 막았는지 검사한다.

OpenRouter 모델 목록에는 이름 뒤에 `:batch` 가 붙은 항목이 섞여 있다. 목록에 나오니
고를 수는 있는데, 실시간 호출(`/chat/completions`)을 하면 이렇게 거절한다.

    404 This model is only available through the Batch API.
        Use the /api/v1/batches endpoint instead.

실제로 이것 때문에 실행이 계속 실패했다(`openai/gpt-5.4-nano:batch` 로 설정돼 있었다).
이 프로그램은 배치 API 를 쓰지 않으므로 **목록에서 빼고, 설정으로 들어와도 거절한다.**
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from server import main as srv


@pytest.fixture
def client(monkeypatch):
    """설정 저장만 메모리로 돌리는 가벼운 클라이언트. 실제 .env·settings.json 은 건드리지 않는다."""
    state = {"settings": dict(config.DEFAULT_SETTINGS), "env": {"OPENROUTER_API_KEY": "sk-or-test"}}
    monkeypatch.setattr(config, "load_settings", lambda: dict(state["settings"]))
    monkeypatch.setattr(config, "save_settings",
                        lambda partial: state["settings"].update(
                            {k: v for k, v in partial.items() if k in config.DEFAULT_SETTINGS}))
    monkeypatch.setattr(config, "load_env", lambda: dict(state["env"]))
    monkeypatch.setattr(config, "save_env_values", lambda values, path=None: dict(state["env"]))
    with TestClient(srv.app) as c:
        yield c


@pytest.mark.parametrize("mid,expected", [
    ("openai/gpt-5.4-nano:batch", True),
    ("anthropic/claude-sonnet-5:batch", True),
    ("openai/gpt-5.4-nano", False),
    ("meta-llama/llama-3.1-8b-instruct:free", False),   # 무료는 실시간으로 잘 된다
    ("openrouter/auto", False),
    ("", False),
    (None, False),
])
def test_is_batch_only(mid, expected):
    assert srv._is_batch_only(mid) is expected


def test_model_list_drops_batch_only(monkeypatch):
    """목록 조회에서 `:batch` 항목이 빠져야 한다."""
    raw = [
        {"id": "openai/gpt-5.4-nano", "name": "나노", "pricing": {"prompt": "0.1"}},
        {"id": "openai/gpt-5.4-nano:batch", "name": "나노(배치)", "pricing": {"prompt": "0.05"}},
        {"id": "openrouter/auto", "name": "자동"},
    ]

    class FakeClient:
        def list_models(self):
            return raw

    monkeypatch.setattr(srv, "_llm_client", lambda **kw: FakeClient())
    srv._MODELS_CACHE.update(key=None, at=0.0, items=[])
    ids = [m["id"] for m in srv.list_models(refresh=1)]
    assert "openai/gpt-5.4-nano" in ids
    assert "openrouter/auto" in ids
    assert "openai/gpt-5.4-nano:batch" not in ids
    srv._MODELS_CACHE.update(key=None, at=0.0, items=[])


def test_saving_a_batch_only_model_is_refused(client):
    """설정으로 들어와도 막고, 무엇을 고르라고 알려 준다."""
    r = client.put("/api/settings", json={"settings": {"model": "openai/gpt-5.4-nano:batch"}})
    assert r.status_code == 400
    msg = r.json()["error"]
    assert "배치 전용" in msg
    assert "openai/gpt-5.4-nano" in msg      # 대신 고를 이름을 알려 준다


def test_saving_a_batch_only_cheap_model_is_refused(client):
    r = client.put("/api/settings", json={"settings": {"model": "openai/gpt-5.4-nano",
                                                       "model_cheap": "openai/gpt-5.4-nano:batch"}})
    assert r.status_code == 400 and "저렴 모델" in r.json()["error"]


def test_normal_model_still_saves(client):
    r = client.put("/api/settings", json={"settings": {"model": "openai/gpt-5.4-nano"}})
    assert r.status_code == 200
    assert r.json()["settings"]["model"] == "openai/gpt-5.4-nano"
