"""pytest 공통 설정.

- 실제 reports/·kb/·registry.csv 를 건드리지 않도록 KCA_CORE_DIR 를 임시 폴더로 바꾼다.
  prompts/templates/scripts 는 실제 경로에서 복사(심볼릭 링크 대신)하고, reports/R01 샘플이 있으면 함께 복사한다.
  scripts.validate·render_table 은 자기 파일 위치(ROOT)를 기준으로 templates/·reports/ 를 찾으므로 복사가 필요하다.
- sys.path 에 app/ 와 임시 core 를 넣는다(config 가 CORE_DIR 를 sys.path[0] 에 넣는다).
- MockLLM: 정해진 응답 순서를 돌려주는 가짜 클라이언트(네트워크 없음).
"""
from __future__ import annotations
import atexit
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
REAL_CORE = APP_DIR.parent


def _mk_tmp_core() -> Path:
    """임시 core 폴더. TMP 가 쓰기 불가한 PC 가 있어 후보를 차례로 시도한다(KCA_TEST_TMP 우선)."""
    cands = [os.environ.get("KCA_TEST_TMP"), None, str(APP_DIR / ".pytest_tmp")]
    last = None
    for base in cands:
        try:
            if base:
                Path(base).mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="kca_core_", dir=base)).resolve()
        except OSError as e:
            last = e
    raise RuntimeError(f"임시 폴더를 만들 수 없습니다: {last}")


TMP_CORE = _mk_tmp_core()


def _build_tmp_core() -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.bak.*", "logs")
    for name in ("prompts", "templates", "scripts"):
        shutil.copytree(REAL_CORE / name, TMP_CORE / name, ignore=ignore)
    (TMP_CORE / "kb").mkdir()
    for sub in ("events", "evidence", "cache"):
        (TMP_CORE / "kb" / sub).mkdir()
    if (REAL_CORE / "kb" / "domains").is_dir():
        shutil.copytree(REAL_CORE / "kb" / "domains", TMP_CORE / "kb" / "domains", ignore=ignore)
    if (REAL_CORE / "kb" / "sources.md").is_file():
        shutil.copy2(REAL_CORE / "kb" / "sources.md", TMP_CORE / "kb" / "sources.md")
    (TMP_CORE / "reports").mkdir()
    if (REAL_CORE / "reports" / "R01").is_dir():
        shutil.copytree(REAL_CORE / "reports" / "R01", TMP_CORE / "reports" / "R01", ignore=ignore)
    (TMP_CORE / "runs").mkdir()
    if (REAL_CORE / "registry.csv").is_file():
        shutil.copy2(REAL_CORE / "registry.csv", TMP_CORE / "registry.csv")
    else:
        (TMP_CORE / "registry.csv").write_text(
            "id,title,published,years_since,domain,types,maturity,updated_at,source_pdf\n", encoding="utf-8-sig")
    # 엔진의 system_prompt 는 app/engine 에 있으므로 복사 불필요


_build_tmp_core()
os.environ["KCA_CORE_DIR"] = str(TMP_CORE)
for _p in (str(TMP_CORE), str(APP_DIR)):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
# 실제 core 의 scripts 가 먼저 import 되어 있으면 걷어낸다(임시 core 의 것을 쓰게)
for _m in [m for m in list(sys.modules) if m == "scripts" or m.startswith("scripts.")]:
    del sys.modules[_m]

import config  # noqa: E402  (KCA_CORE_DIR 설정 후 import)

assert config.CORE_DIR == TMP_CORE.resolve(), f"임시 core 가 적용되지 않음: {config.CORE_DIR}"
atexit.register(lambda: shutil.rmtree(TMP_CORE, ignore_errors=True))

from engine.llm import LLMError, LLMResult  # noqa: E402


def pytest_configure(config):
    """--basetemp 가 없으면 tmp_path 기반 폴더를 임시 core 아래에 둔다.
    (TMP 가 권한 없는 폴더를 가리키는 PC 에서 pytest-of-<user> 접근 오류를 피한다.)"""
    if getattr(config.option, "basetemp", None):
        return
    base = TMP_CORE / "pytest_basetemp"
    config.option.basetemp = str(base)
    try:  # tmpdir 플러그인이 먼저 초기화됐으면 팩토리를 새 경로로 바꾼다
        from _pytest.tmpdir import TempPathFactory
        if getattr(config, "_tmp_path_factory", None) is not None:
            config._tmp_path_factory = TempPathFactory.from_config(config, _ispytest=True)
    except Exception:
        pass


# ---------------------------------------------------------------- 설정 격리
@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """실제 app/.env·settings.json 을 읽지 않는다(키 노출·실제 검색 방지)."""
    monkeypatch.setattr(config, "load_env", lambda: {})
    monkeypatch.setattr(config, "load_settings", lambda: dict(config.DEFAULT_SETTINGS))
    yield


@pytest.fixture
def core_dir() -> Path:
    return TMP_CORE


@pytest.fixture
def settings() -> dict:
    s = dict(config.DEFAULT_SETTINGS)
    s.update({"model": "mock/main", "model_cheap": "mock/cheap", "max_steps": 8, "max_source_chars": 5000})
    return s


# ---------------------------------------------------------------- 가짜 보고서
@pytest.fixture
def make_report(monkeypatch):
    """make_report("R90", source_text=..., meta=...) → reports/R90 경로. 기존 서랍은 지운다.
    레지스트리는 테스트별 사본(registry_test.csv)을 쓰게 해 다른 테스트(다음 ID 계산 등)에 흔적을 남기지 않는다."""
    created = []
    reg_copy = TMP_CORE / "registry_test.csv"
    shutil.copy2(TMP_CORE / "registry.csv", reg_copy)
    monkeypatch.setattr(config, "REGISTRY_CSV", reg_copy)

    def _make(report_id: str, source_text: str = "<!-- page 1 -->\n본문", meta: dict | None = None,
              files: dict | None = None) -> Path:
        rd = config.report_dir(report_id)
        if rd.exists():
            shutil.rmtree(rd, ignore_errors=True)
        (rd / "00_source").mkdir(parents=True)
        (rd / "00_source" / f"{report_id}.md").write_text(source_text, encoding="utf-8")
        m = {"report_id": report_id, "source_pdf": f"{report_id}.pdf", "pages": 3, "chars": len(source_text),
             "published": "2023-04", "title": f"테스트 보고서 {report_id}"}
        m.update(meta or {})
        (rd / "01_meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        for rel, val in (files or {}).items():
            p = rd / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, indent=1), encoding="utf-8")
        created.append(rd)
        return rd

    yield _make
    for rd in created:
        shutil.rmtree(rd, ignore_errors=True)
    reg_copy.unlink(missing_ok=True)


# ---------------------------------------------------------------- MockLLM
USAGE = {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.001}


def final(obj) -> LLMResult:
    """최종 응답(JSON 객체를 문자열로)."""
    content = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return LLMResult(content=content, tool_calls=[], usage=dict(USAGE), cost_usd=USAGE["cost"], raw={})


def tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def calls(*tcs: dict) -> LLMResult:
    """도구 호출 응답."""
    return LLMResult(content="", tool_calls=list(tcs), usage=dict(USAGE), cost_usd=USAGE["cost"], raw={})


class MockLLM:
    """정해진 응답 순서를 돌려주는 가짜 LLM. 응답이 callable 이면 messages 를 받아 LLMResult 를 만든다."""
    model = "mock/main"

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls: list = []

    def add(self, *responses) -> "MockLLM":
        self.responses.extend(responses)
        return self

    def chat(self, messages, tools=None, json_mode=False, model=None, extra=None) -> LLMResult:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools), "json_mode": json_mode,
                           "model": model, "extra": extra})
        if not self.responses:
            raise LLMError("MockLLM: 준비된 응답이 없습니다")
        r = self.responses.pop(0)
        if callable(r) and not isinstance(r, LLMResult):
            r = r(messages)
        if isinstance(r, LLMResult):
            return r
        return final(r)

    def list_models(self) -> list:
        return [{"id": "mock/main", "name": "Mock", "context_length": 8000, "pricing": {"prompt": "0", "completion": "0"}}]

    def ping(self) -> tuple:
        return True, "mock"


def all_text(call: dict) -> str:
    """한 호출의 메시지(system·user·assistant·tool) 전체를 한 문자열로."""
    parts = []
    for m in call["messages"]:
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.append(json.dumps(c, ensure_ascii=False))
        if m.get("tool_calls"):
            parts.append(json.dumps(m["tool_calls"], ensure_ascii=False))
    parts.append(json.dumps(call.get("tools") or [], ensure_ascii=False))
    return "\n".join(parts)
