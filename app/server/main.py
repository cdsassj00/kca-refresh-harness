"""FastAPI 서버 — 정적 UI + /api/*. DESIGN.md 7절의 계약을 구현한다.

- 엔진(engine.llm / engine.jobs / engine.search / engine.parsing)은 지연 import 한다.
  엔진 모듈이 아직 없거나 깨져 있어도 서버는 뜨고, 해당 기능만 503 `{"error": …}` 로 답한다.
- 모든 오류 응답은 `{"error": "한국어 메시지"}` 형태(필요하면 "errors" 목록 추가).
- 키 값은 응답·로그에 마스킹해서만 노출한다(config.masked_env).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import mimetypes
import queue
import re
import shutil
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import config

VERSION = "0.1"
UI_DIR = config.APP_DIR / "ui"
MODELS_CACHE_TTL = 600  # 10분
_ACTIVE_STATUSES = ("queued", "pending", "running", "starting")
_TERMINAL_STATUSES = ("done", "failed", "cancelled", "canceled", "error")

app = FastAPI(title="KCA 연구보고서 결론 재도출·현행화", version=VERSION, docs_url="/api/docs", redoc_url=None)

_STORE = None                     # engine.jobs.JobStore 단일 인스턴스(지연 생성)
_STORE_LOCK = threading.Lock()
_MODELS_CACHE: dict[str, Any] = {"key": None, "at": 0.0, "items": []}


# ================================================================ 공통 도우미
def _err(status: int, message: str, **extra) -> HTTPException:
    detail: Any = {"error": message, **extra} if extra else message
    return HTTPException(status_code=status, detail=detail)


def _engine(name: str):
    """engine.<name> 모듈을 지연 import. 실패하면 503."""
    try:
        return importlib.import_module(f"engine.{name}")
    except Exception as e:  # ImportError 뿐 아니라 모듈 안의 오류도 503 으로
        raise _err(503, f"엔진 모듈(engine.{name})을 불러올 수 없음: {type(e).__name__}: {e}")


def _engine_ready(name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(f"engine.{name}")
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _job_store():
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            mod = _engine("jobs")
            _STORE = mod.JobStore()
        return _STORE


def _llm_client(settings: Optional[dict] = None, env: Optional[dict] = None):
    settings = settings or config.load_settings()
    env = env or config.load_env()
    mod = _engine("llm")
    return mod.LLMClient(base_url=config.llm_base_url(), api_key=env.get("OPENROUTER_API_KEY", ""),
                         model=settings.get("model") or "openrouter/auto",
                         temperature=float(settings.get("temperature", 0.2)))


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _report_dir_or_404(report_id: str) -> Path:
    try:
        d = config.report_dir(report_id)
    except ValueError as e:
        raise _err(400, str(e))
    if not d.is_dir():
        raise _err(404, f"보고서 서랍이 없습니다: {report_id}")
    return d


def _registry_rows() -> list[dict]:
    from scripts.registry import load_registry
    return load_registry(config.REGISTRY_CSV)


def _int_or_none(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _next_report_id() -> str:
    nums = [0]
    for r in _registry_rows():
        m = re.fullmatch(r"R(\d{2,3})", r.get("id", ""))
        if m:
            nums.append(int(m.group(1)))
    if config.REPORTS_DIR.is_dir():
        for p in config.REPORTS_DIR.iterdir():
            m = re.fullmatch(r"R(\d{2,3})", p.name)
            if m and p.is_dir():
                nums.append(int(m.group(1)))
    return f"R{max(nums) + 1:02d}"


def _rel(p: Path) -> str:
    """CORE_DIR 기준 상대경로(밖이면 절대경로) 문자열."""
    try:
        return p.relative_to(config.CORE_DIR).as_posix()
    except ValueError:
        return str(p)


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _active_job_for(report_id: str) -> Optional[dict]:
    try:
        store = _job_store()
    except HTTPException:
        return None
    try:
        jobs = store.list() or []
    except Exception:
        return None
    for j in jobs:
        j = _to_jsonable(j)
        if isinstance(j, dict) and j.get("report_id") == report_id and str(j.get("status", "")).lower() in _ACTIVE_STATUSES:
            return j
    return None


# ================================================================ 오류 응답 통일
@app.exception_handler(StarletteHTTPException)
async def _http_exc(_: Request, exc: StarletteHTTPException):
    detail = exc.detail
    body = detail if isinstance(detail, dict) and "error" in detail else {"error": str(detail)}
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_exc(_: Request, exc: RequestValidationError):
    errs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
        errs.append(f"{loc or '(body)'}: {e.get('msg', '')}")
    return JSONResponse({"error": "요청 형식 오류", "errors": errs}, status_code=422)


@app.exception_handler(Exception)
async def _any_exc(_: Request, exc: Exception):
    return JSONResponse({"error": f"서버 내부 오류: {type(exc).__name__}: {exc}"}, status_code=500)


# ================================================================ 기본·설정·진단
@app.get("/api/health")
def health():
    ok_engine, _ = _engine_ready("jobs")
    return {"ok": True, "version": VERSION, "core_dir": str(config.CORE_DIR), "engine_ready": ok_engine}


def _settings_payload() -> dict:
    return {"settings": config.load_settings(), "env": config.masked_env(), "env_keys": list(config.ENV_KEYS)}


@app.get("/api/settings")
def get_settings():
    return _settings_payload()


@app.put("/api/settings")
async def put_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise _err(400, "요청 본문이 JSON 이 아닙니다")
    if not isinstance(body, dict):
        raise _err(400, "요청 본문은 {\"settings\": {...}, \"env\": {...}} 형태여야 합니다")
    settings = body.get("settings")
    env = body.get("env")
    if settings is not None:
        if not isinstance(settings, dict):
            raise _err(400, "settings 는 객체여야 합니다")
        for field, label in (("model", "현재 모델"), ("model_cheap", "저렴 모델")):
            mid = str(settings.get(field) or "")
            if _is_batch_only(mid):
                raise _err(400, f"{label} '{mid}' 는 배치 전용이라 이 프로그램에서 쓸 수 없습니다. "
                                f"뒤의 ':batch' 를 뗀 '{mid.rsplit(':', 1)[0]}' 를 고르세요")
        config.save_settings(settings)
    if env is not None:
        if not isinstance(env, dict):
            raise _err(400, "env 는 객체여야 합니다")
        try:
            config.save_env_values({k: ("" if v is None else str(v)) for k, v in env.items()})
        except ValueError as e:
            raise _err(400, str(e))
        _MODELS_CACHE.update(key=None, at=0.0, items=[])  # 키·주소가 바뀌었을 수 있으니 모델 캐시 비움
    return _settings_payload()


def _resolve_search_provider(settings: dict, env: dict) -> tuple[str, bool, str]:
    """(provider, ok, detail). auto 는 tavily → exa → naver → openrouter_online 순으로 키가 있는 첫 공급자."""
    need = {
        "tavily": ["TAVILY_API_KEY"], "exa": ["EXA_API_KEY"],
        "naver": ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"], "openrouter_online": ["OPENROUTER_API_KEY"],
    }
    want = str(settings.get("search_provider") or "auto").lower()
    if want == "auto":
        for name in ("tavily", "exa", "naver", "openrouter_online"):
            if all(env.get(k) for k in need[name]):
                return name, True, f"auto → {name} (키 확인됨)"
        return "auto", False, "검색 키가 없음: TAVILY_API_KEY / EXA_API_KEY / NAVER_CLIENT_ID+SECRET / OPENROUTER_API_KEY 중 하나 필요"
    if want not in need:
        return want, False, f"알 수 없는 검색 공급자: {want}"
    missing = [k for k in need[want] if not env.get(k)]
    if missing:
        return want, False, "키 없음: " + ", ".join(missing)
    return want, True, "키 확인됨"


@app.get("/api/doctor")
def doctor(deep: int = 0):
    settings = config.load_settings()
    env = config.load_env()
    model = settings.get("model") or "openrouter/auto"

    # LLM
    if not env.get("OPENROUTER_API_KEY"):
        llm = {"ok": False, "model": model, "detail": "OPENROUTER_API_KEY 없음"}
    else:
        try:
            ok, detail = _llm_client(settings, env).ping()
            llm = {"ok": bool(ok), "model": model, "detail": str(detail)}
        except HTTPException as e:
            llm = {"ok": False, "model": model, "detail": e.detail if isinstance(e.detail, str) else e.detail.get("error", "")}
        except Exception as e:
            llm = {"ok": False, "model": model, "detail": f"연결 실패: {type(e).__name__}: {e}"}

    # 검색
    provider, ok, detail = _resolve_search_provider(settings, env)
    ready, why = _engine_ready("search")
    if not ready:
        ok, detail = False, f"{detail}; 검색 모듈 없음({why})"
    elif ok and deep:
        try:
            mod = importlib.import_module("engine.search")
            res = mod.search("한국방송통신전파진흥원", max_results=1)
            n = len(res) if isinstance(res, list) else 0
            detail = f"{detail}; 시험 검색 {n}건"
            ok = n > 0
        except Exception as e:
            ok, detail = False, f"{detail}; 시험 검색 실패: {type(e).__name__}: {e}"
    search = {"provider": provider, "ok": ok, "detail": detail}

    # 근거 소스(T0~T3 커넥터)
    try:
        from scripts.sources import source_statuses
        sources = [_to_jsonable(s) for s in source_statuses(env, http=None, do_ping=False)]
    except Exception as e:
        sources = [{"name": "(오류)", "tier": "", "kind": "", "env_vars": [], "configured": False,
                    "implemented": False, "ok": False, "detail": f"소스 목록 조회 실패: {type(e).__name__}: {e}"}]

    # 파서
    def _has(mod: str) -> bool:
        return importlib.util.find_spec(mod) is not None
    hwp = bool(shutil.which("hwp5txt")) or _has("hwp5")
    parsers = {"hwp": hwp, "docx": _has("markitdown") or _has("docx"), "pdf": _has("pypdf"), "hwpx": _has("defusedxml")}
    return {"llm": llm, "search": search, "sources": sources, "parsers": parsers}


# OpenRouter 모델 이름 뒤에 붙는 꼬리표 중, 실시간 호출(chat/completions)이 아예 안 되는 것.
# 목록에는 나오지만 고르면 404 가 난다.
#   "This model is only available through the Batch API. Use the /api/v1/batches endpoint instead."
# 사람이 고를 수 없게 목록에서 뺀다. 이 프로그램은 배치 API 를 쓰지 않는다.
BATCH_ONLY_SUFFIXES = (":batch",)


def _is_batch_only(model_id: str) -> bool:
    return str(model_id or "").endswith(BATCH_ONLY_SUFFIXES)


@app.get("/api/models")
def list_models(refresh: int = 0):
    env = config.load_env()
    cache_key = f"{config.llm_base_url()}|{config.mask(env.get('OPENROUTER_API_KEY'))}"
    now = time.time()
    if not refresh and _MODELS_CACHE["key"] == cache_key and now - _MODELS_CACHE["at"] < MODELS_CACHE_TTL:
        return _MODELS_CACHE["items"]
    try:
        raw = _llm_client(env=env).list_models()
    except HTTPException:
        raise
    except Exception as e:
        raise _err(502, f"모델 목록 조회 실패: {type(e).__name__}: {e}")
    items = []
    for m in raw or []:
        mid = str(m.get("id") or "")
        if _is_batch_only(mid):
            continue        # 고를 수는 있는데 절대 안 도는 모델은 아예 보여 주지 않는다
        pricing = m.get("pricing") or {}
        items.append({
            "id": m.get("id"), "name": m.get("name") or m.get("id"),
            "context_length": m.get("context_length"),
            "prompt_price": pricing.get("prompt", m.get("prompt_price")),
            "completion_price": pricing.get("completion", m.get("completion_price")),
        })
    items.sort(key=lambda x: str(x.get("id") or ""))
    _MODELS_CACHE.update(key=cache_key, at=now, items=items)
    return items


# ================================================================ 보고서
@app.get("/api/reports")
def list_reports():
    from scripts.registry import years_since
    rows = {r["id"]: dict(r) for r in _registry_rows() if r.get("id")}
    # 레지스트리에 없지만 서랍이 있는 보고서도 보여 준다
    if config.REPORTS_DIR.is_dir():
        for p in sorted(config.REPORTS_DIR.iterdir()):
            if p.is_dir() and re.fullmatch(r"R\d{2,3}", p.name) and p.name not in rows:
                meta = _read_json(p / "01_meta.json", {}) or {}
                rows[p.name] = {"id": p.name, "title": meta.get("title", p.name), "published": meta.get("published", ""),
                                "domain": "", "types": "", "maturity": "-", "updated_at": "", "source_pdf": meta.get("source_pdf", "")}
    out = []
    for rid in sorted(rows):
        r = rows[rid]
        table = _read_json(config.REPORTS_DIR / rid / "comparison_table.json")
        summary = table.get("summary") if isinstance(table, dict) else None
        maturity = r.get("maturity") or "-"
        if (maturity in ("", "-")) and isinstance(table, dict) and table.get("maturity"):
            maturity = table["maturity"]
        published = r.get("published") or ""
        out.append({
            "id": rid, "title": r.get("title", ""), "published": published,
            "years_since": _int_or_none(r.get("years_since")) if r.get("years_since") else years_since(published),
            "domain": r.get("domain", ""), "types": r.get("types", ""), "maturity": maturity,
            "updated_at": r.get("updated_at", ""), "source_pdf": r.get("source_pdf", ""),
            "summary": summary, "running": _active_job_for(rid) is not None,
        })
    return out


@app.post("/api/reports/intake")
async def intake_report(file: UploadFile = File(...), report_id: Optional[str] = Form(None),
                        title: Optional[str] = Form(None), published: Optional[str] = Form(None)):
    parsing = _engine("parsing")
    fname = Path(file.filename or "upload.bin").name
    if not fname or fname in (".", ".."):
        raise _err(400, "파일 이름이 없습니다")
    rid = (report_id or "").strip().upper() or _next_report_id()
    try:
        config.report_dir(rid)
    except ValueError as e:
        raise _err(400, str(e))
    if _active_job_for(rid):
        raise _err(409, f"{rid} 는 실행 중이라 접수할 수 없습니다")

    up_dir = config.RUNS_DIR / "uploads" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    up_dir.mkdir(parents=True, exist_ok=True)
    dest = up_dir / fname
    size = 0
    with dest.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)
    if size == 0:
        raise _err(400, "빈 파일입니다")
    try:
        meta = parsing.intake(rid, dest, title=(title or None), published=(published or None))
    except parsing.ParseError as e:
        raise _err(400, f"파싱 실패: {e}")
    except ValueError as e:
        raise _err(400, str(e))
    meta = dict(meta)
    meta["upload_path"] = _rel(dest)
    return {"report_id": rid, "meta": meta}


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    d = _report_dir_or_404(report_id)
    meta = _read_json(d / "01_meta.json", {}) or {}
    classification = _read_json(d / "02_classification.json")
    table = _read_json(d / "comparison_table.json")
    reg = next((r for r in _registry_rows() if r.get("id") == report_id), None)
    maturity = (reg or {}).get("maturity") or "-"
    if maturity in ("", "-") and isinstance(table, dict) and table.get("maturity"):
        maturity = table["maturity"]
    files = []
    for p in sorted(d.rglob("*")):
        if p.is_file():
            st = p.stat()
            files.append({"path": p.relative_to(d).as_posix(), "size": st.st_size,
                          "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    has = {
        "source": (d / "00_source" / f"{report_id}.md").is_file(),
        "classification": (d / "02_classification.json").is_file(),
        "chains": (d / "03_argument_chains.json").is_file(),
        "events": (d / "L0" / "events.json").is_file(),
        "provisional": (d / "L0" / "provisional_verdicts.json").is_file(),
        "verdicts": (d / "L1" / "verdicts.json").is_file(),
        "brief": (d / "L2" / "blind_input" / "brief.md").is_file(),
        "blind": (d / "L2" / "blind_output" / "blind_conclusions.json").is_file(),
        "comparison": (d / "comparison_table.json").is_file(),
        "report": (d / "07_report" / "report.html").is_file() or (d / "07_report" / "report.md").is_file(),
        "critic": (d / "07_report" / "critic_notes.md").is_file(),
    }
    job = _active_job_for(report_id)
    return {"report_id": report_id, "meta": meta, "classification": classification, "maturity": maturity,
            "summary": table.get("summary") if isinstance(table, dict) else None,
            "registry": reg, "files": files, "has": has, "running_job": job}


_JSON_FILES = {
    "comparison": "comparison_table.json",
    "chains": "03_argument_chains.json",
    "events": "L0/events.json",
    "verdicts": "L1/verdicts.json",
    "blind": "L2/blind_output/blind_conclusions.json",
    "provisional": "L0/provisional_verdicts.json",
    "classification": "02_classification.json",
    "meta": "01_meta.json",
}


def _report_json(report_id: str, key: str):
    d = _report_dir_or_404(report_id)
    rel = _JSON_FILES[key]
    p = d / rel
    if not p.is_file():
        raise _err(404, f"아직 없는 산출물입니다: {rel}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise _err(500, f"JSON 이 깨져 있습니다: {rel} ({e})")


@app.get("/api/reports/{report_id}/comparison")
def report_comparison(report_id: str):
    return _report_json(report_id, "comparison")


@app.get("/api/reports/{report_id}/chains")
def report_chains(report_id: str):
    return _report_json(report_id, "chains")


@app.get("/api/reports/{report_id}/events")
def report_events(report_id: str):
    return _report_json(report_id, "events")


@app.get("/api/reports/{report_id}/verdicts")
def report_verdicts(report_id: str):
    return _report_json(report_id, "verdicts")


@app.get("/api/reports/{report_id}/blind")
def report_blind(report_id: str):
    return _report_json(report_id, "blind")


@app.get("/api/reports/{report_id}/provisional")
def report_provisional(report_id: str):
    return _report_json(report_id, "provisional")


@app.get("/api/reports/{report_id}/classification")
def report_classification(report_id: str):
    return _report_json(report_id, "classification")


_MIME = {
    ".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain", ".jsonl": "application/x-ndjson",
    ".json": "application/json", ".html": "text/html", ".htm": "text/html", ".csv": "text/csv",
    ".yaml": "text/yaml", ".yml": "text/yaml", ".pdf": "application/pdf",
    ".hwpx": "application/vnd.hancom.hwpx", ".hwp": "application/x-hwp", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
}
_TEXT_TYPES = ("text/", "application/json", "application/x-ndjson", "image/svg+xml")


def _guess_mime(p: Path) -> str:
    mt = _MIME.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    if mt.startswith(_TEXT_TYPES) and "charset" not in mt:
        mt += "; charset=utf-8"
    return mt


@app.get("/api/reports/{report_id}/file")
def report_file(report_id: str, path: str, download: int = 0):
    d = _report_dir_or_404(report_id)
    if not path or path.strip() == "":
        raise _err(400, "path 가 필요합니다")
    try:
        p = config.safe_join(d, path.replace("\\", "/"))
    except PermissionError as e:
        raise _err(403, str(e))
    if not p.is_file():
        raise _err(404, f"파일이 없습니다: {path}")
    headers = {"Content-Disposition": f'attachment; filename="{p.name}"'} if download else None
    return FileResponse(str(p), media_type=_guess_mime(p), headers=headers)


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str):
    d = _report_dir_or_404(report_id)
    if _active_job_for(report_id):
        raise _err(409, f"{report_id} 는 실행 중이라 삭제할 수 없습니다. 먼저 취소하세요")
    shutil.rmtree(d)
    from scripts.registry import load_registry, save_registry
    rows = [r for r in load_registry(config.REGISTRY_CSV) if r.get("id") != report_id]
    if config.REGISTRY_CSV.exists():
        save_registry(rows, config.REGISTRY_CSV)
    return {"ok": True, "report_id": report_id}


# ================================================================ 실행(작업)
_DEFAULT_OPTIONS = {
    "blind_rerun": {"enabled": True, "repeats": 1},
    "survey_redesign": True, "experiment_plan": True,
    "synthetic_sim": {"enabled": False, "panel_size": 200},
    "l0_rewrite_scope": "env_and_desk_updatable",
}


def _fill_run_config(rc: dict) -> dict:
    """UI 가 일부만 보내도 되도록 빠진 키를 기본값으로 채운다(스키마 검증은 그 뒤에)."""
    rc = dict(rc)
    rc.setdefault("layers", ["L0", "L1", "L2"])
    opts = dict(_DEFAULT_OPTIONS)
    user_opts = rc.get("options") if isinstance(rc.get("options"), dict) else {}
    for k, v in user_opts.items():
        if isinstance(v, dict) and isinstance(opts.get(k), dict):
            opts[k] = {**opts[k], **v}
        else:
            opts[k] = v
    rc["options"] = opts
    rc.setdefault("sources", ["web"])
    rc.setdefault("output", ["html"])
    if not isinstance(rc.get("period"), dict):
        since = None
        rid = rc.get("report_id")
        if isinstance(rid, str) and re.fullmatch(r"R\d{2,3}", rid):
            meta = _read_json(config.REPORTS_DIR / rid / "01_meta.json", {}) or {}
            pub = meta.get("published")
            if isinstance(pub, str) and re.fullmatch(r"\d{4}-\d{2}", pub):
                since = f"{pub}-01"
        rc["period"] = {"since": since or "2015-01-01", "until": "today"}
    else:
        rc["period"] = {"since": rc["period"].get("since") or "2015-01-01", "until": rc["period"].get("until") or "today"}
    return rc


@app.get("/api/runs")
def list_runs():
    store = _job_store()
    jobs = [_to_jsonable(j) for j in (store.list() or [])]
    for j in jobs:
        if isinstance(j, dict) and isinstance(j.get("messages"), list):
            j["messages"] = j["messages"][-5:]
    return jobs


@app.post("/api/runs")
async def start_run(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise _err(400, "요청 본문이 JSON 이 아닙니다")
    if not isinstance(body, dict):
        raise _err(400, "요청 본문은 객체여야 합니다")
    if isinstance(body.get("run_config"), dict):
        rc = body["run_config"]
        force_from = body.get("force_from")
    else:
        rc = {k: v for k, v in body.items() if k != "force_from"}
        force_from = body.get("force_from")
    rid = rc.get("report_id")
    if not rid or not isinstance(rid, str):
        raise _err(400, "run_config.report_id 는 필수입니다")
    rc = _fill_run_config(rc)
    from scripts.validate import validate_obj
    errors = validate_obj(rc, "run_config")
    if errors:
        raise _err(422, "run_config 가 스키마에 맞지 않습니다", errors=errors)
    _report_dir_or_404(rid)
    if force_from is not None and (not isinstance(force_from, str) or not force_from.strip()):
        force_from = None
    store = _job_store()
    if _active_job_for(rid):
        raise _err(409, f"{rid} 는 이미 실행 중입니다. 끝나거나 취소한 뒤 다시 실행하세요")
    try:
        job_id = store.start(rc, force_from)
    except RuntimeError as e:
        raise _err(409, str(e) or f"{rid} 는 이미 실행 중입니다")
    except (ValueError, KeyError) as e:
        raise _err(400, f"실행 설정 오류: {e}")
    return {"job_id": job_id, "report_id": rid, "run_config": rc, "force_from": force_from}


def _job_or_404(job_id: str) -> dict:
    store = _job_store()
    job = store.get(job_id)
    if job is None:
        raise _err(404, f"작업이 없습니다: {job_id}")
    return _to_jsonable(job)


@app.get("/api/runs/{job_id}")
def get_run(job_id: str):
    job = _job_or_404(job_id)
    if isinstance(job, dict):
        for key in ("messages", "events", "log"):
            if isinstance(job.get(key), list):
                job[key] = job[key][-20:]
    return job


@app.post("/api/runs/{job_id}/cancel")
def cancel_run(job_id: str):
    store = _job_store()
    _job_or_404(job_id)
    try:
        store.cancel(job_id)
    except Exception as e:
        raise _err(500, f"취소 실패: {type(e).__name__}: {e}")
    return {"ok": True, "job_id": job_id}


def _is_terminal_event(ev: Any) -> bool:
    if not isinstance(ev, dict):
        return False
    if ev.get("final") is True:
        return True
    stage = str(ev.get("stage") or "").lower()
    status = str(ev.get("status") or "").lower()
    return stage in ("pipeline", "job", "run", "") and status in _TERMINAL_STATUSES


def _job_is_terminal(store, job_id: str) -> bool:
    try:
        job = _to_jsonable(store.get(job_id))
    except Exception:
        return True
    if not isinstance(job, dict):
        return True
    return str(job.get("status", "")).lower() not in _ACTIVE_STATUSES


@app.get("/api/runs/{job_id}/events")
def run_events(job_id: str):
    store = _job_store()
    _job_or_404(job_id)
    q = store.subscribe(job_id)

    def gen():
        try:
            # 시작 직후 현재 상태 한 번
            try:
                snap = _to_jsonable(store.get(job_id))
                if isinstance(snap, dict):
                    yield "event: snapshot\ndata: " + json.dumps(snap, ensure_ascii=False, default=str) + "\n\n"
            except Exception:
                pass
            while True:
                try:
                    ev = q.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
                    if _job_is_terminal(store, job_id) and q.empty():
                        break
                    continue
                if ev is None:
                    break
                yield "data: " + json.dumps(_to_jsonable(ev), ensure_ascii=False, default=str) + "\n\n"
                if _is_terminal_event(ev):
                    break
            # 종료 이벤트에 최종 상태를 실어 보낸다(UI 는 status 가 있으면 재조회 없이 종료 처리)
            try:
                fin = _to_jsonable(store.get(job_id))
                end_payload = {"job_id": job_id, "status": fin.get("status"), "cost_usd": fin.get("cost_usd"),
                               "ended_at": fin.get("ended_at")} if isinstance(fin, dict) else {"job_id": job_id}
            except Exception:
                end_payload = {"job_id": job_id}
            yield "event: end\ndata: " + json.dumps(end_payload, ensure_ascii=False, default=str) + "\n\n"
        finally:
            unsub = getattr(store, "unsubscribe", None)
            if callable(unsub):
                try:
                    unsub(job_id, q)
                except Exception:
                    pass

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


# ================================================================ 지식베이스
_MD_DATE = re.compile(r"(\d{4}-\d{2}(?:-\d{2})?)")


def _event_from_md(p: Path, domain_hint: str) -> Optional[dict]:
    try:
        txt = p.read_text(encoding="utf-8")
    except OSError:
        return None
    fm: dict = {}
    body = txt
    if txt.startswith("---"):
        parts = txt.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"').strip("'")
            body = parts[2]
    title = fm.get("title")
    if not title:
        m = re.search(r"^#\s+(.+)$", body, re.M)
        title = m.group(1).strip() if m else p.stem
    date = fm.get("date") or (_MD_DATE.search(p.stem).group(1) if _MD_DATE.search(p.stem) else "")
    summary = fm.get("summary")
    if not summary:
        paras = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip() and not b.strip().startswith("#")]
        summary = paras[0][:600] if paras else ""
    sources = []
    for u in re.findall(r"https?://[^\s)>\]]+", body):
        if u not in [s["url"] for s in sources]:
            sources.append({"url": u})
    return {"event_id": fm.get("event_id") or p.stem, "domain": fm.get("domain") or domain_hint, "date": date,
            "title": title, "summary": summary, "grade": fm.get("grade", ""), "sources": sources,
            "origin": _rel(p)}


def _norm_event(e: dict, origin: str, domain_hint: str = "") -> dict:
    return {"event_id": e.get("event_id") or e.get("id") or "", "domain": e.get("domain") or domain_hint,
            "date": e.get("date", ""), "title": e.get("title", ""), "summary": e.get("summary", ""),
            "grade": e.get("grade", ""), "sources": e.get("sources", []),
            "affected_indicators": e.get("affected_indicators", []), "origin": origin}


@app.get("/api/kb/events")
def kb_events(domain: Optional[str] = None):
    seen: dict[str, dict] = {}

    def _add(ev: Optional[dict]):
        if not ev:
            return
        key = ev.get("event_id") or f"{ev.get('domain')}|{ev.get('date')}|{ev.get('title')}"
        if key not in seen:
            seen[key] = ev

    ev_dir = config.KB_DIR / "events"
    if ev_dir.is_dir():
        for p in sorted(ev_dir.rglob("*")):
            if not p.is_file():
                continue
            dom = p.parent.name if p.parent != ev_dir else ""
            if p.suffix.lower() == ".json":
                data = _read_json(p)
                items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
                origin = _rel(p)
                for e in items:
                    if isinstance(e, dict):
                        _add(_norm_event(e, origin, dom))
            elif p.suffix.lower() == ".md":
                _add(_event_from_md(p, dom))
    # 보고서 서랍의 L0/events.json 도 타임라인에 합친다
    if config.REPORTS_DIR.is_dir():
        for ej in sorted(config.REPORTS_DIR.glob("R*/L0/events.json")):
            data = _read_json(ej)
            if isinstance(data, list):
                origin = _rel(ej)
                for e in data:
                    if isinstance(e, dict):
                        _add(_norm_event(e, origin))
    out = list(seen.values())
    if domain:
        out = [e for e in out if e.get("domain") == domain]
    out.sort(key=lambda e: (str(e.get("date") or ""), str(e.get("event_id") or "")), reverse=True)
    return out


# ================================================================ 정적 UI
_UI_PLACEHOLDER = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>KCA 현행화 — UI 준비 중</title>
<style>body{font-family:system-ui,sans-serif;background:#F4F6F9;color:#1A2330;margin:0;padding:48px}
.card{max-width:640px;margin:0 auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
code{background:#eef2f6;padding:2px 6px;border-radius:4px}</style></head><body><div class="card">
<h1>UI 준비 중</h1><p>서버는 떠 있지만 <code>app/ui/index.html</code> 이 아직 없습니다.</p>
<p>API 는 바로 쓸 수 있습니다: <a href="/api/health">/api/health</a> · <a href="/api/reports">/api/reports</a> · <a href="/api/doctor">/api/doctor</a> · <a href="/api/docs">/api/docs</a></p>
</div></body></html>"""


@app.get("/", include_in_schema=False)
def index():
    idx = UI_DIR / "index.html"
    if idx.is_file():
        return FileResponse(str(idx), media_type="text/html; charset=utf-8")
    return HTMLResponse(_UI_PLACEHOLDER)


if UI_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")
    # index.html 이 ./style.css, ./app.js 처럼 상대경로로 참조하므로 루트에서도 같은 파일을 서빙한다(API 라우트 뒤에 마운트)
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui-root")
