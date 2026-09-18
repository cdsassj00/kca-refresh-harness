"""독립 프로그램 설정·경로. DESIGN.md 1절의 계약을 구현한다.

- 공통 핵심(prompts/templates/kb/scripts/reports)은 CORE_DIR(기본 app/..)에서 참조한다.
- 키는 app/.env 에만 있다. 값은 로그·응답에 마스킹해서만 노출한다.
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path
from typing import Mapping

APP_DIR = Path(__file__).resolve().parent
CORE_DIR = Path(os.environ.get("KCA_CORE_DIR", APP_DIR.parent)).resolve()
REPORTS_DIR = CORE_DIR / "reports"
PROMPTS_DIR = CORE_DIR / "prompts"
TEMPLATES_DIR = CORE_DIR / "templates"
KB_DIR = CORE_DIR / "kb"
SCRIPTS_DIR = CORE_DIR / "scripts"
REGISTRY_CSV = CORE_DIR / "registry.csv"
RUNS_DIR = CORE_DIR / "runs"
ENV_PATH = APP_DIR / ".env"
SETTINGS_PATH = APP_DIR / "settings.json"

if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

DEFAULT_SETTINGS = {
    "model": "openrouter/auto",
    "model_cheap": "",
    "temperature": 0.2,
    "max_steps": 25,
    "search_provider": "auto",
    "max_source_chars": 120000,
    "language": "ko",
}

# .env 에 저장을 허용하는 키 이름 (UI에서 수정 가능). 값 검증은 하지 않되 이름은 이 목록만.
ENV_KEYS_APP = [
    "OPENROUTER_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_MODEL_CHEAP", "SEARCH_PROVIDER",
    "TAVILY_API_KEY", "EXA_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "NAVER_API_STYLE",
]
ENV_KEYS_SOURCES = [
    "OPENALEX_MAILTO", "CROSSREF_MAILTO", "S2_API_KEY", "DATA_GO_KR_API_KEY", "KOSIS_API_KEY", "LAW_GO_KR_OC",
    "ASSEMBLY_API_KEY", "ECOS_API_KEY", "KCI_API_KEY", "NANET_API_KEY", "SCIENCEON_API_KEY", "IEEE_API_KEY",
    "CORE_API_KEY", "SPRINGER_API_KEY", "LENS_API_TOKEN", "ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN", "WOS_API_KEY",
    "DIMENSIONS_API_KEY", "PERPLEXITY_API_KEY", "SERPAPI_API_KEY", "DBPIA_API_KEY", "BIGKINDS_API_KEY",
]
ENV_KEYS = ENV_KEYS_APP + ENV_KEYS_SOURCES

# 공공데이터포털(data.go.kr)은 API(데이터셋)마다 인증키가 따로 나오는 경우가 많다.
# 그래서 `DATA_GO_KR_KEY_<이름>` 형태의 변수를 자유롭게 추가할 수 있게 한다.
# 예: DATA_GO_KR_KEY_KCI, DATA_GO_KR_KEY_PRISM
# `DATA_GO_KR_API_KEY` 는 데이터셋 전용 키가 없을 때 쓰는 기본값이다.
ENV_KEY_PREFIXES = ("DATA_GO_KR_KEY_",)


def is_allowed_env_key(name: str) -> bool:
    """`.env` 에 저장을 허용하는 이름인지. 고정 목록이거나 허용 접두사로 시작하면 참."""
    if name in ENV_KEYS:
        return True
    return any(name.startswith(p) and len(name) > len(p) for p in ENV_KEY_PREFIXES)


def data_go_kr_keys(env: Mapping[str, str] | None = None) -> dict:
    """공공데이터포털 키를 {짧은이름: 값} 으로 모은다. 기본키는 '_default' 로 담는다."""
    env = env if env is not None else load_env()
    out = {}
    for k, v in env.items():
        if k.startswith("DATA_GO_KR_KEY_") and v:
            out[k[len("DATA_GO_KR_KEY_"):].lower()] = v
    if env.get("DATA_GO_KR_API_KEY"):
        out["_default"] = env["DATA_GO_KR_API_KEY"]
    return out


SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "_OC")


def _read_env_file(path: Path = ENV_PATH) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_env() -> dict:
    """app/.env + OS 환경변수(허용 키만). 값이 빈 것은 제외."""
    env = _read_env_file()
    for k in ENV_KEYS:
        if k not in env and os.environ.get(k):
            env[k] = os.environ[k]
    for k, v in os.environ.items():           # DATA_GO_KR_KEY_* 처럼 접두사로 허용한 것
        if k not in env and v and is_allowed_env_key(k):
            env[k] = v
    return {k: v for k, v in env.items() if v}


def save_env_values(values: Mapping[str, str], path: Path = ENV_PATH) -> dict:
    """허용 목록의 키만 .env 에 반영. 빈 문자열이면 삭제. 나머지 줄은 보존."""
    current = _read_env_file(path)
    for k, v in values.items():
        if not is_allowed_env_key(k):
            raise ValueError(f"허용되지 않은 설정 키: {k}")
        if v is None or str(v).strip() == "":
            current.pop(k, None)
        else:
            current[k] = str(v).strip()
    lines = ["# 독립 프로그램 설정. 이 파일은 git에 올라가지 않는다. 키 값은 화면·로그에 마스킹된다."]
    for k in ENV_KEYS:
        if k in current:
            lines.append(f"{k}={current[k]}")
    for k in sorted(k for k in current if k not in ENV_KEYS and is_allowed_env_key(k)):
        lines.append(f"{k}={current[k]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load_env()


def mask(value: str | None) -> str:
    if not value:
        return ""
    v = str(value)
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:5]}…{v[-4:]}"


def masked_env() -> dict:
    env = load_env()
    return {k: (mask(v) if any(h in k for h in SECRET_HINTS) else v) for k, v in env.items()}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    env = load_env()
    # .env 의 모델·공급자 지정이 있으면 settings.json 이 비어 있을 때의 기본값으로 쓴다
    if env.get("LLM_MODEL") and not SETTINGS_PATH.exists():
        s["model"] = env["LLM_MODEL"]
    if env.get("LLM_MODEL_CHEAP") and not s.get("model_cheap"):
        s["model_cheap"] = env["LLM_MODEL_CHEAP"]
    if env.get("SEARCH_PROVIDER") and s.get("search_provider") == "auto":
        s["search_provider"] = env["SEARCH_PROVIDER"]
    return s


def save_settings(partial: Mapping) -> dict:
    s = load_settings()
    for k, v in partial.items():
        if k in DEFAULT_SETTINGS:
            s[k] = v
    SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def llm_base_url() -> str:
    return load_env().get("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")


def report_dir(report_id: str) -> Path:
    if not re.fullmatch(r"R\d{2,3}", report_id or ""):
        raise ValueError(f"보고서 ID 형식 오류: {report_id}")
    return REPORTS_DIR / report_id


def safe_join(base: Path, relpath: str) -> Path:
    """base 아래로만 경로를 허용한다(.. 탈출 금지)."""
    p = (base / relpath).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise PermissionError(f"허용되지 않은 경로: {relpath}")
    return p
