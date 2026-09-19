"""server.main 테스트 — TestClient 로 health·settings 마스킹·reports 목록·intake 업로드·runs 유효성·409·SSE·엔진 부재."""
from __future__ import annotations

import json
import queue
import re
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config

RAW_KEY = "sk-or-v1-0123456789abcdefghijklmnopqrstuvwxyz"


# ---------------------------------------------------------------- 픽스처
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """실제 reports/·registry.csv·.env·settings.json 을 건드리지 않도록 임시 폴더·메모리로 돌린다."""
    src_r01 = config.REPORTS_DIR / "R01"
    if not src_r01.is_dir():
        pytest.skip("reports/R01 샘플이 없어 서버 테스트를 건너뜀")
    reports = tmp_path / "reports"
    shutil.copytree(src_r01, reports / "R01")
    registry = tmp_path / "registry.csv"
    if config.REGISTRY_CSV.is_file():
        shutil.copy(config.REGISTRY_CSV, registry)
    else:
        from scripts.registry import upsert
        upsert(registry, {"id": "R01", "title": "샘플", "published": "2023-04", "maturity": "-"})
    monkeypatch.setattr(config, "REPORTS_DIR", reports)
    monkeypatch.setattr(config, "REGISTRY_CSV", registry)
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")

    state = {"env": {"OPENROUTER_API_KEY": RAW_KEY, "LLM_MODEL": "openrouter/auto"},
             "settings": dict(config.DEFAULT_SETTINGS)}

    def load_env():
        return dict(state["env"])

    def save_env_values(values, path=None):
        for k, v in values.items():
            if k not in config.ENV_KEYS:
                raise ValueError(f"허용되지 않은 설정 키: {k}")
            if v is None or str(v).strip() == "":
                state["env"].pop(k, None)
            else:
                state["env"][k] = str(v).strip()
        return dict(state["env"])

    def save_settings(partial):
        state["settings"].update({k: v for k, v in partial.items() if k in config.DEFAULT_SETTINGS})
        return dict(state["settings"])

    monkeypatch.setattr(config, "load_env", load_env)
    monkeypatch.setattr(config, "save_env_values", save_env_values)
    monkeypatch.setattr(config, "load_settings", lambda: dict(state["settings"]))
    monkeypatch.setattr(config, "save_settings", save_settings)
    return {"tmp": tmp_path, "reports": reports, "registry": registry, "state": state}


@pytest.fixture
def main_mod(sandbox):
    from server import main
    main._STORE = None
    main._MODELS_CACHE.update(key=None, at=0.0, items=[])
    yield main
    main._STORE = None


@pytest.fixture
def client(main_mod):
    return TestClient(main_mod.app)


class FakeStore:
    """engine.jobs.JobStore 의 대역."""

    def __init__(self, jobs=None):
        self.jobs = jobs or []
        self.started = []
        self.cancelled = []
        self.queues = {}

    def list(self):
        return list(self.jobs)

    def get(self, job_id):
        return next((j for j in self.jobs if j["job_id"] == job_id), None)

    def start(self, run_config, force_from=None):
        job_id = f"job-{len(self.started) + 1}"
        self.started.append((run_config, force_from))
        self.jobs.append({"job_id": job_id, "report_id": run_config["report_id"], "status": "queued",
                          "started_at": "2026-09-15 10:00", "ended_at": None, "cost_usd": 0.0, "stages": [],
                          "messages": [{"message": f"m{i}"} for i in range(30)]})
        return job_id

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        return True

    def subscribe(self, job_id):
        q = self.queues.get(job_id)
        if q is None:
            q = queue.Queue()
            self.queues[job_id] = q
        return q


VALID_RUN_CONFIG = {
    "report_id": "R01", "layers": ["L0", "L1", "L2"],
    "options": {"blind_rerun": {"enabled": True, "repeats": 1}, "survey_redesign": True, "experiment_plan": True,
                "synthetic_sim": {"enabled": False, "panel_size": 200}, "l0_rewrite_scope": "env_and_desk_updatable"},
    "sources": ["web"], "output": ["html"], "period": {"since": "2023-04-20", "until": "today"},
}


# ---------------------------------------------------------------- 기본
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["version"] == "0.1" and "core_dir" in body


def test_root_serves_placeholder_or_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_settings_masks_secret(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert RAW_KEY not in r.text
    body = r.json()
    masked = body["env"]["OPENROUTER_API_KEY"]
    assert masked.startswith("sk-or") and "…" in masked and masked.endswith(RAW_KEY[-4:])
    assert body["env"]["LLM_MODEL"] == "openrouter/auto"      # 비밀이 아닌 값은 그대로
    assert "OPENROUTER_API_KEY" in body["env_keys"]
    assert body["settings"]["model"] == config.DEFAULT_SETTINGS["model"]


def test_settings_put_saves_and_masks(client, sandbox):
    r = client.put("/api/settings", json={"settings": {"temperature": 0.7, "bogus": 1},
                                          "env": {"TAVILY_API_KEY": "tvly-secret-value-12345", "LLM_MODEL_CHEAP": ""}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["temperature"] == 0.7 and "bogus" not in body["settings"]
    assert "tvly-secret-value-12345" not in r.text
    assert body["env"]["TAVILY_API_KEY"].endswith("2345")
    assert sandbox["state"]["env"]["TAVILY_API_KEY"] == "tvly-secret-value-12345"
    # 허용되지 않은 키 → 400, 본문이 JSON 이 아니면 400
    assert client.put("/api/settings", json={"env": {"EVIL": "x"}}).status_code == 400
    r = client.put("/api/settings", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and "error" in r.json()


# ---------------------------------------------------------------- 보고서
def test_reports_list_has_r01_with_summary(client):
    r = client.get("/api/reports")
    assert r.status_code == 200
    rows = {x["id"]: x for x in r.json()}
    assert "R01" in rows
    r01 = rows["R01"]
    assert r01["published"] == "2023-04" and isinstance(r01["years_since"], int)
    assert isinstance(r01["summary"], dict) and "동일" in r01["summary"]
    assert r01["maturity"]


def test_report_detail_and_sub_json(client):
    r = client.get("/api/reports/R01")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["report_id"] == "R01" and body["has"]["comparison"] is True
    assert any(f["path"] == "01_meta.json" for f in body["files"])
    assert client.get("/api/reports/R01/comparison").json()["report_id"] == "R01"
    assert isinstance(client.get("/api/reports/R01/chains").json(), (dict, list))
    assert isinstance(client.get("/api/reports/R01/events").json(), list)
    r = client.get("/api/reports/R01/blind")
    assert r.status_code in (200, 404)
    assert client.get("/api/reports/R99").status_code == 404
    r = client.get("/api/reports/bad-id")
    assert r.status_code == 400 and "error" in r.json()


def test_report_file_and_traversal_block(client):
    r = client.get("/api/reports/R01/file", params={"path": "01_meta.json"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert json.loads(r.content)["report_id"] == "R01"
    r = client.get("/api/reports/R01/file", params={"path": "07_report/report.html"})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("text/html")
    r = client.get("/api/reports/R01/file", params={"path": "../../registry.csv"})
    assert r.status_code == 403 and "error" in r.json()
    r = client.get("/api/reports/R01/file", params={"path": "없는파일.md"})
    assert r.status_code == 404
    r = client.get("/api/reports/R01/file", params={"path": "01_meta.json", "download": 1})
    assert "attachment" in r.headers.get("content-disposition", "")


def _next_report_id(sandbox) -> str:
    """registry 의 가장 큰 번호 + 1.

    번호를 코드에 박아 두면 사람이 보고서를 하나 접수하는 것만으로 검사가 깨진다
    (실제로 R08 을 접수하자 이 검사가 실패했다). 그래서 그때그때 계산한다.
    """
    text = (sandbox["tmp"] / "registry.csv").read_text(encoding="utf-8-sig")
    nums = [int(m) for m in re.findall(r"^R(\d{2,3})", text, flags=re.M)]
    return "R%02d" % ((max(nums) if nums else 0) + 1)


def test_intake_upload_txt(client, sandbox):
    nid = _next_report_id(sandbox)
    content = "접수 테스트 본문입니다.\n둘째 줄".encode("utf-8")
    files = {"file": ("10_[2022.07]_업로드_테스트.txt", content, "text/plain")}
    r = client.post("/api/reports/intake", files=files, data={"title": "", "published": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_id"] == nid                         # registry 최대 번호 + 1
    meta = body["meta"]
    assert meta["published"] == "2022-07" and meta["title"] == "업로드 테스트"
    assert meta["format"] == "txt" and meta["scanned"] is False and meta["chars"] > 0
    assert (sandbox["reports"] / nid / "00_source" / f"{nid}.md").is_file()
    assert (sandbox["reports"] / nid / "01_meta.json").is_file()
    assert (sandbox["tmp"] / "runs" / "uploads").is_dir()
    assert not (config.APP_DIR.parent / "reports" / nid).exists() or config.REPORTS_DIR != config.APP_DIR.parent / "reports"
    # 레지스트리·목록에 반영
    ids = [x["id"] for x in client.get("/api/reports").json()]
    assert nid in ids
    # 명시 ID·제목·발간연월
    r = client.post("/api/reports/intake", files={"file": ("memo.txt", b"abc", "text/plain")},
                    data={"report_id": "R12", "title": "직접 제목", "published": "2019.12"})
    assert r.status_code == 200 and r.json()["meta"]["title"] == "직접 제목" and r.json()["meta"]["published"] == "2019-12"
    # 잘못된 ID / 형식 / 빈 파일
    assert client.post("/api/reports/intake", files={"file": ("a.txt", b"x", "text/plain")}, data={"report_id": "X1"}).status_code == 400
    r = client.post("/api/reports/intake", files={"file": ("a.xyz", b"x", "application/octet-stream")})
    assert r.status_code == 400 and "파싱 실패" in r.json()["error"]
    assert client.post("/api/reports/intake", files={"file": ("empty.txt", b"", "text/plain")}).status_code == 400


def test_delete_report(client, sandbox):
    client.post("/api/reports/intake", files={"file": ("d.txt", b"x", "text/plain")}, data={"report_id": "R20"})
    assert (sandbox["reports"] / "R20").is_dir()
    r = client.delete("/api/reports/R20")
    assert r.status_code == 200 and not (sandbox["reports"] / "R20").exists()
    assert "R20" not in [x["id"] for x in client.get("/api/reports").json()]
    assert client.delete("/api/reports/R20").status_code == 404


# ---------------------------------------------------------------- 실행
def test_runs_post_validation_errors(client, main_mod):
    main_mod._STORE = FakeStore()
    # 스키마 위반 → 422 (검증은 엔진을 건드리기 전에 수행)
    r = client.post("/api/runs", json={"run_config": {"report_id": "R01", "layers": ["L9"]}})
    assert r.status_code == 422, r.text
    body = r.json()
    assert "error" in body and any("layers" in e for e in body["errors"])
    # report_id 없음 → 400
    r = client.post("/api/runs", json={"run_config": {"layers": ["L0"]}})
    assert r.status_code == 400 and "report_id" in r.json()["error"]
    # JSON 아님 → 400
    r = client.post("/api/runs", content=b"nope", headers={"content-type": "application/json"})
    assert r.status_code == 400
    # 없는 보고서 → 404
    r = client.post("/api/runs", json={"run_config": {**VALID_RUN_CONFIG, "report_id": "R77"}})
    assert r.status_code == 404
    assert main_mod._STORE.started == []


def test_runs_start_then_409_and_status(client, main_mod):
    store = FakeStore()
    main_mod._STORE = store
    r = client.post("/api/runs", json={"run_config": VALID_RUN_CONFIG, "force_from": "delta"})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert store.started[0][1] == "delta" and store.started[0][0]["report_id"] == "R01"
    # 같은 보고서 동시 실행 → 409
    r = client.post("/api/runs", json={"run_config": VALID_RUN_CONFIG})
    assert r.status_code == 409 and "error" in r.json()
    # 실행 중이면 접수·삭제도 409
    assert client.delete("/api/reports/R01").status_code == 409
    # 목록·상세(최근 메시지 20개)
    jobs = client.get("/api/runs").json()
    assert jobs and jobs[0]["job_id"] == job_id
    detail = client.get(f"/api/runs/{job_id}").json()
    assert detail["status"] == "queued" and len(detail["messages"]) == 20
    assert client.get("/api/runs/없음").status_code == 404
    # 취소
    r = client.post(f"/api/runs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["ok"] is True and store.cancelled == [job_id]
    # 실행 중 표시가 보고서 목록에도 나온다
    assert next(x for x in client.get("/api/reports").json() if x["id"] == "R01")["running"] is True


def test_runs_partial_config_gets_defaults(client, main_mod):
    store = FakeStore()
    main_mod._STORE = store
    r = client.post("/api/runs", json={"report_id": "R01", "layers": ["L0"]})   # run_config 를 최상위로 보내도 됨
    assert r.status_code == 200, r.text
    rc = store.started[0][0]
    assert rc["layers"] == ["L0"] and rc["options"]["blind_rerun"]["enabled"] is True
    assert rc["period"]["since"] == "2023-04-01" and rc["period"]["until"] == "today"
    assert rc["output"] and rc["sources"]


def test_runs_sse_stream(client, main_mod):
    store = FakeStore()
    main_mod._STORE = store
    job_id = client.post("/api/runs", json={"run_config": VALID_RUN_CONFIG}).json()["job_id"]
    q = store.subscribe(job_id)
    q.put({"job_id": job_id, "report_id": "R01", "stage": "chains", "status": "running", "step": 1, "message": "시작"})
    q.put({"job_id": job_id, "report_id": "R01", "stage": "pipeline", "status": "done", "message": "끝"})
    q.put(None)
    r = client.get(f"/api/runs/{job_id}/events")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
    payloads = [json.loads(ln[6:]) for ln in lines]
    assert any(p.get("stage") == "chains" for p in payloads)
    assert any(p.get("stage") == "pipeline" and p.get("status") == "done" for p in payloads)
    assert "event: end" in r.text
    assert client.get("/api/runs/없음/events").status_code == 404


# ---------------------------------------------------------------- 진단·모델·KB
def test_doctor_without_key(client, sandbox):
    sandbox["state"]["env"].pop("OPENROUTER_API_KEY")
    r = client.get("/api/doctor")
    assert r.status_code == 200
    body = r.json()
    assert body["llm"]["ok"] is False and body["llm"]["detail"] == "OPENROUTER_API_KEY 없음"
    assert body["search"]["ok"] is False and body["search"]["provider"] == "auto"
    assert isinstance(body["sources"], list) and body["sources"] and "configured" in body["sources"][0]
    assert set(body["parsers"]) >= {"hwp", "docx"}


def test_doctor_with_key_uses_llm_ping(client, main_mod, monkeypatch, sandbox):
    calls = {}

    class FakeLLM:
        def __init__(self, **kw):
            calls.update(kw)

        def ping(self):
            return True, "모델 응답 확인"

        def list_models(self):
            return [{"id": "z/model", "name": "Z", "context_length": 1000, "pricing": {"prompt": "0.001", "completion": "0.002"}},
                    {"id": "a/model", "name": "A", "context_length": 2000, "pricing": {"prompt": "0", "completion": "0"}}]

    import types
    fake_mod = types.ModuleType("engine.llm")
    fake_mod.LLMClient = FakeLLM
    monkeypatch.setitem(sys.modules, "engine.llm", fake_mod)
    sandbox["state"]["env"]["TAVILY_API_KEY"] = "t"
    body = client.get("/api/doctor").json()
    assert body["llm"]["ok"] is True and body["llm"]["detail"] == "모델 응답 확인"
    assert RAW_KEY == calls["api_key"] and RAW_KEY not in json.dumps(body)
    assert body["search"]["provider"] == "tavily" and body["search"]["ok"] is True
    # 모델 목록(정렬·가격 평탄화·캐시)
    models = client.get("/api/models").json()
    assert [m["id"] for m in models] == ["a/model", "z/model"]
    assert models[1]["prompt_price"] == "0.001" and models[1]["completion_price"] == "0.002"
    fake_mod.LLMClient = None  # 캐시가 있으면 다시 만들지 않는다
    assert client.get("/api/models").json() == models


def test_kb_events_from_reports_and_kb_dir(client, sandbox, monkeypatch):
    kb = sandbox["tmp"] / "kb"
    (kb / "events" / "spectrum").mkdir(parents=True)
    (kb / "events" / "spectrum" / "2024-01-01_test.md").write_text(
        "---\nevent_id: E-spectrum-2024-01-md_test\ndate: 2024-01-01\ngrade: B\n---\n# MD 사건\n\n요약 문단입니다. https://example.org/a\n",
        encoding="utf-8")
    (kb / "events" / "spectrum" / "extra.json").write_text(json.dumps([{
        "event_id": "E-spectrum-2024-02-json_test", "domain": "spectrum", "date": "2024-02-01",
        "title": "JSON 사건", "summary": "요약", "grade": "A", "sources": [{"url": "https://example.org/b", "retrieved_at": "2026-09-15"}]}]),
        encoding="utf-8")
    monkeypatch.setattr(config, "KB_DIR", kb)
    r = client.get("/api/kb/events")
    assert r.status_code == 200
    evs = r.json()
    ids = [e["event_id"] for e in evs]
    assert "E-spectrum-2024-01-md_test" in ids and "E-spectrum-2024-02-json_test" in ids
    assert len(evs) > 2                                             # reports/R01/L0/events.json 도 합쳐짐
    md = next(e for e in evs if e["event_id"] == "E-spectrum-2024-01-md_test")
    assert md["title"] == "MD 사건" and md["domain"] == "spectrum" and md["sources"][0]["url"] == "https://example.org/a"
    dates = [e["date"] for e in evs]
    assert dates == sorted(dates, reverse=True)
    only = client.get("/api/kb/events", params={"domain": "spectrum"}).json()
    assert only and all(e["domain"] == "spectrum" for e in only)
    assert client.get("/api/kb/events", params={"domain": "없음"}).json() == []


# ---------------------------------------------------------------- 엔진 부재
def test_server_survives_missing_engine(client, main_mod, monkeypatch):
    for name in ("engine", "engine.jobs", "engine.llm", "engine.search", "engine.parsing"):
        monkeypatch.setitem(sys.modules, name, None)      # import 시 ImportError 발생
    main_mod._STORE = None
    assert client.get("/api/health").status_code == 200 and client.get("/api/health").json()["ok"] is True
    assert client.get("/api/reports").status_code == 200
    r = client.get("/api/runs")
    assert r.status_code == 503 and "engine.jobs" in r.json()["error"]
    r = client.post("/api/runs", json={"run_config": VALID_RUN_CONFIG})
    assert r.status_code == 503
    r = client.get("/api/doctor")
    assert r.status_code == 200 and r.json()["llm"]["ok"] is False and r.json()["search"]["ok"] is False
    r = client.post("/api/reports/intake", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 503 and "error" in r.json()
