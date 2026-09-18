# P0 골격·근거 소스·문서 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 결론 재도출 하네스의 뼈대(폴더·규칙·스키마·레지스트리)와 근거 소스 계층(`evidence.py` T0 커넥터 + `doctor`)을 만들어, 키 없이도 논문 검색이 되고 사용자가 키를 넣으면 `doctor`가 상태를 보여주는 상태까지 도달한다.

**Architecture:** 파일 기반 상태(JSON/JSONL/CSV/YAML)를 프로젝트 루트 아래 고정 경로에 두고, 파이썬 스크립트가 결정적 작업(HTTP 수집·캐시·스키마 검증·레지스트리)을 맡는다. 모든 근거 소스는 `scripts/sources/<name>.py` 한 파일에 `BaseSource`를 상속한 클래스 하나로 구현되고, `catalog.py`가 소스 이름·등급·환경변수·구현 여부를 한 곳에 선언한다. LLM 판단이 필요한 단계(분류·논증 사슬·재도출)는 이후 계획(P1~P5)에서 스킬·에이전트로 붙인다.

**Tech Stack:** Python 3.11+, requests, jsonschema, PyYAML, python-dotenv, pytest; Claude Code CLI 2.1.x(헤드리스 실행은 P3에서 사용)

**Spec:** `docs/superpowers/specs/2026-09-15-kca-refresh-harness-design.md` (v4 확정) — 이 계획은 스펙 5절(근거 소스), 6절(kb·도메인), 8절(골격), 11절 P0 행을 구현한다. P1~P6은 각각 별도 계획으로 작성한다.

## Global Constraints

- 모든 문서·주석·CLI 출력은 한국어. 코드 식별자는 영어.
- 파일 인코딩 UTF-8, JSON은 `ensure_ascii=False`, CSV는 `utf-8-sig`(엑셀 호환).
- 키는 `.env`에만. `.env`는 `.gitignore`. 코드·문서·로그에 키 값이 찍히면 안 된다(`doctor`는 존재 여부만 표시).
- 증거 등급 값은 정확히 `"A" | "B" | "C"`. 근거 레코드 필드명은 스펙 5절과 동일: `source, id, url, title, date, snippet, grade, retrieved_at, query`.
- 소스 이름(식별자)은 소문자 스네이크: `openalex, crossref, semantic_scholar, arxiv, data_go_kr, kosis, law_go_kr, assembly, naver_news, ecos, kci, nanet, scienceon, ieee, core, springer, lens, scopus, wos, dimensions, exa, tavily, perplexity, serpapi_scholar, dbpia, bigkinds`.
- 환경변수 이름은 `docs/api_keys_guide.md` 4절과 동일해야 하며, 테스트가 이를 검사한다.
- 도메인 6개 식별자: `spectrum, emf_inspection, broadcast_media, network_5g6g, ict_qualification, kca_management`.
- 보고서 ID는 `R01`~`R07`(reports/ PDF 번호 순: 01→R01 … 예비06→R06, 예비07→R07).
- 캐시는 `kb/cache/`, 기본 TTL 7일. 네트워크 테스트는 모두 mock. 실제 호출은 마지막 스모크 태스크에서만.
- 작업 디렉터리: `<저장소 루트>` (아래 `$ROOT`).

---

## File Structure (P0에서 생성)

```
$ROOT/
├─ CLAUDE.md                          # 하네스 규칙(층·등급·kb 선독후기·작성자≠검토자)
├─ .gitignore  .env.example  requirements.txt  pytest.ini
├─ .claude/settings.json              # 헤드리스 허용 규칙
├─ registry.csv                       # 보고서 레지스트리
├─ templates/
│  ├─ taxonomy.yaml                   # 유형 7종 + 전략 + 재수행 등급
│  ├─ verdict_rules.yaml              # 판정 7종 수치 규칙
│  └─ schemas/ evidence_record.schema.json, conclusion.schema.json, chain.schema.json,
│              claim.schema.json, verdict.schema.json, event.schema.json,
│              comparison_row.schema.json, run_config.schema.json
├─ scripts/
│  ├─ __init__.py
│  ├─ evidence.py                     # CLI: papers, doctor  (stats/law/bills/news는 P4)
│  ├─ validate.py                     # 스키마 검증 CLI/함수
│  ├─ registry.py                     # 레지스트리 read/upsert CLI/함수
│  └─ sources/
│     ├─ __init__.py                  # load_sources(), get_source()
│     ├─ base.py                      # EvidenceRecord, HttpClient(캐시), BaseSource, SourceStatus
│     ├─ catalog.py                   # CATALOG: 소스 26개 선언(등급·kind·env·구현 클래스)
│     ├─ openalex.py  crossref.py  semantic_scholar.py  arxiv_src.py
├─ kb/  events/.gitkeep  evidence/.gitkeep  cache/.gitkeep  sources.md  domains/*.yaml(6)
├─ reports/  (기존 PDF 7편)   runs/.gitkeep
├─ tests/  conftest.py, test_base.py, test_catalog.py, test_openalex.py, test_other_sources.py,
│          test_evidence_cli.py, test_validate.py, test_registry.py, test_templates.py, test_guide_sync.py
└─ docs/  api_keys_guide.md(검증본), p0_smoke.md
```

---

### Task 0: 저장소·골격·규칙 파일

**Files:**
- Create: `.gitignore`, `requirements.txt`, `pytest.ini`, `scripts/__init__.py`, `scripts/sources/__init__.py`(빈 파일로 시작), `tests/conftest.py`, `.claude/settings.json`, `CLAUDE.md`, `.env.example`, `kb/events/.gitkeep`, `kb/evidence/.gitkeep`, `kb/cache/.gitkeep`, `runs/.gitkeep`

**Interfaces:**
- Produces: 패키지 경로 `scripts.sources` 임포트 가능, `tests/conftest.py`의 `ROOT` fixture(`pathlib.Path`)와 `tmp_cache`(임시 캐시 디렉터리) fixture.

- [ ] **Step 1: git 초기화와 무시 규칙**

```bash
cd "$ROOT" && git init -b main
```
`.gitignore`:
```
.env
__pycache__/
*.pyc
.pytest_cache/
kb/cache/*
!kb/cache/.gitkeep
runs/*
!runs/.gitkeep
reports/*/logs/
research_kca_reports/*.html
.omc/
```

- [ ] **Step 2: 의존성과 pytest 설정**

`requirements.txt`:
```
requests>=2.32
jsonschema>=4.22
PyYAML>=6.0
python-dotenv>=1.0
defusedxml>=0.7
pytest>=8.2
```
`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -q
```
설치: `python -m pip install -r requirements.txt`

- [ ] **Step 3: 패키지 파일과 conftest**

`scripts/__init__.py`와 `scripts/sources/__init__.py`는 빈 파일. `tests/conftest.py`:
```python
import pathlib, pytest

@pytest.fixture
def ROOT() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]

@pytest.fixture
def tmp_cache(tmp_path) -> pathlib.Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d
```

- [ ] **Step 4: 헤드리스 허용 규칙**

`.claude/settings.json`:
```json
{
  "permissions": {
    "allow": [
      "Bash(python scripts/*)",
      "Bash(python -m pytest*)",
      "Read", "Write", "Edit", "Glob", "Grep",
      "WebSearch", "WebFetch", "Agent"
    ]
  }
}
```

- [ ] **Step 5: CLAUDE.md**

```markdown
# KCA 연구보고서 결론 재도출·현행화 하네스

## 목적
보고서의 결론 하나하나에 대해 「지금 같은 연구를 다시 하면 같은 결론이 나오는가」를 판정한다.
자료 최신화는 입력이고, 결론 판정이 산출물이다. 설계: docs/superpowers/specs/2026-09-15-kca-refresh-harness-design.md

## 규칙
- 언어: 산출물·로그·주석 한국어.
- 근거 없는 수치 금지. 모든 수치·판정에 출처 URL, 조회일, 증거 등급(A 1차·공식 / B 2차 / C 추정·시뮬레이션·블라인드 결론)을 붙인다.
- 근거 수집은 `python scripts/evidence.py`로만 한다(캐시·등급·기록 일관성). 결과는 `kb/evidence/*.jsonl`.
- kb 선독후기: 조사 전에 `kb/events/<domain>/`을 읽고, 새 사건은 같은 형식으로 기록한다.
- 작성자와 검토자를 분리한다. 보고서·대조표 산출 후 `refresh-critic` 에이전트 검토를 통과해야 완료다.
- 블라인드 재수행 에이전트에게는 원문 경로를 절대 주지 않는다. 입력은 `reports/<id>/L2/blind_input/`만.
- 설문·실험은 수행하지 않는다. R3 결론은 "판정 불가"로 두고 설계서를 붙인다. 합성 시뮬레이션은 옵션이며 C등급과 "시뮬레이션" 표기가 필수다.
- 키는 `.env`에만 있다. 키 값을 출력·기록하지 않는다.

## 경로
reports/<id>/ (00_source, 01_meta.json, 02_classification.json, 03_argument_chains.json, 03_claims.jsonl, L0/, L1/, L2/, comparison_table.json, 07_report/, logs/)
kb/ (events, evidence, cache, domains, sources.md) · templates/ · scripts/ · ui/ · runs/ · registry.csv

## 실행
- 소스 상태: `python scripts/evidence.py doctor`
- 논문 검색: `python scripts/evidence.py papers --q "..." --since 2023-01-01 --limit 20`
- 스키마 검증: `python scripts/validate.py <file> --schema claim`
- 테스트: `python -m pytest`
```

- [ ] **Step 6: `.env.example`** — `docs/api_keys_guide.md` 4절의 블록을 그대로 복사한다(변수 26개, 값은 비움).

- [ ] **Step 7: pytest가 0건으로 정상 종료하는지 확인**

Run: `python -m pytest`
Expected: `no tests ran` 종료코드 5(테스트 없음). 임포트 확인: `python -c "import scripts.sources; print('ok')"` → `ok`

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "chore: P0 골격·규칙·설정 파일"
```

---

### Task 1: 근거 레코드·HTTP 캐시·소스 기반 클래스

**Files:**
- Create: `scripts/sources/base.py`
- Test: `tests/test_base.py`

**Interfaces:**
- Produces:
  - `EvidenceRecord(source:str, id:str, url:str, title:str, date:str|None, snippet:str, grade:str, retrieved_at:str, query:str, extra:dict)`; `.to_json() -> dict`
  - `HttpClient(cache_dir: Path, ttl_days:int=7, no_cache:bool=False, user_agent:str="kca-refresh/0.1")`; `.get_json(url, params=None, headers=None, timeout=20) -> dict`; `.get_text(url, params=None, headers=None, timeout=20) -> str`
  - `BaseSource(env: Mapping[str,str], http: HttpClient)`; 클래스 속성 `name, tier, kind, env_vars: list[str], default_grade`; 메서드 `is_configured() -> bool`, `search(query, since=None, until=None, limit=20) -> list[EvidenceRecord]`(추상), `ping() -> tuple[bool,str]`(추상), `now_iso()`
  - `SourceStatus(name, tier, kind, env_vars, configured, implemented, ok, detail)` dataclass

- [ ] **Step 1: 실패하는 테스트**

`tests/test_base.py`:
```python
import json, time
from unittest.mock import patch, MagicMock
from scripts.sources.base import EvidenceRecord, HttpClient, BaseSource

def test_evidence_record_to_json_has_required_fields():
    r = EvidenceRecord(source="openalex", id="W1", url="https://x", title="t",
                       date="2024-01-01", snippet="s", grade="A",
                       retrieved_at="2026-09-15T00:00:00", query="q")
    j = r.to_json()
    assert set(["source","id","url","title","date","snippet","grade","retrieved_at","query","extra"]) <= set(j)
    assert j["grade"] == "A"

def test_evidence_record_rejects_bad_grade():
    import pytest
    with pytest.raises(ValueError):
        EvidenceRecord(source="s", id="1", url="u", title="t", date=None, snippet="",
                       grade="D", retrieved_at="x", query="q")

def test_http_get_json_uses_cache(tmp_cache):
    http = HttpClient(cache_dir=tmp_cache)
    fake = MagicMock(); fake.status_code = 200; fake.json.return_value = {"a": 1}; fake.text = '{"a": 1}'
    with patch("scripts.sources.base.requests.get", return_value=fake) as g:
        assert http.get_json("https://api.test/x", params={"q": "1"}) == {"a": 1}
        assert http.get_json("https://api.test/x", params={"q": "1"}) == {"a": 1}
        assert g.call_count == 1
    assert len(list(tmp_cache.glob("*.json"))) == 1

def test_http_no_cache_bypasses(tmp_cache):
    http = HttpClient(cache_dir=tmp_cache, no_cache=True)
    fake = MagicMock(); fake.status_code = 200; fake.json.return_value = {"a": 1}; fake.text = "{}"
    with patch("scripts.sources.base.requests.get", return_value=fake) as g:
        http.get_json("https://api.test/y"); http.get_json("https://api.test/y")
        assert g.call_count == 2

def test_base_source_is_configured_checks_env():
    class S(BaseSource):
        name="s"; tier="T1"; kind="papers"; env_vars=["K1"]; default_grade="B"
        def search(self, query, since=None, until=None, limit=20): return []
        def ping(self): return True, "ok"
    assert S({"K1": "v"}, http=None).is_configured() is True
    assert S({}, http=None).is_configured() is False
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_base.py -v`
Expected: FAIL, `ModuleNotFoundError: scripts.sources.base`

- [ ] **Step 3: 구현**

`scripts/sources/base.py`:
```python
"""근거 레코드, HTTP 캐시 클라이언트, 소스 기반 클래스."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional
import requests

GRADES = ("A", "B", "C")

@dataclass
class EvidenceRecord:
    source: str
    id: str
    url: str
    title: str
    date: Optional[str]
    snippet: str
    grade: str
    retrieved_at: str
    query: str
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.grade not in GRADES:
            raise ValueError(f"증거 등급은 A/B/C 중 하나여야 합니다: {self.grade}")

    def to_json(self) -> dict:
        return asdict(self)

@dataclass
class SourceStatus:
    name: str
    tier: str
    kind: str
    env_vars: list
    configured: bool
    implemented: bool
    ok: Optional[bool]
    detail: str

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

class HttpClient:
    """GET 전용, JSON 파일 캐시. 키 값은 캐시 키에 넣지 않는다(헤더는 캐시 키 제외)."""
    def __init__(self, cache_dir: Path, ttl_days: int = 7, no_cache: bool = False,
                 user_agent: str = "kca-refresh/0.1"):
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_days * 86400; self.no_cache = no_cache; self.user_agent = user_agent

    def _key(self, url: str, params: Optional[dict]) -> Path:
        raw = json.dumps([url, sorted((params or {}).items())], ensure_ascii=False)
        return self.cache_dir / (hashlib.sha1(raw.encode("utf-8")).hexdigest() + ".json")

    def _fetch(self, url, params, headers, timeout) -> tuple[int, str]:
        h = {"User-Agent": self.user_agent}; h.update(headers or {})
        resp = requests.get(url, params=params, headers=h, timeout=timeout)
        return resp.status_code, resp.text

    def get_text(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
                 timeout: int = 20) -> str:
        p = self._key(url, params)
        if not self.no_cache and p.exists():
            c = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - c["fetched_at"] < self.ttl and c["status"] == 200:
                return c["body"]
        status, body = self._fetch(url, params, headers, timeout)
        if status != 200:
            raise requests.HTTPError(f"HTTP {status} for {url}")
        if not self.no_cache:
            p.write_text(json.dumps({"fetched_at": time.time(), "status": status, "url": url,
                                     "body": body}, ensure_ascii=False), encoding="utf-8")
        return body

    def get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
                 timeout: int = 20) -> dict:
        return json.loads(self.get_text(url, params, headers, timeout))

class BaseSource:
    name: str = ""; tier: str = ""; kind: str = ""; env_vars: list = []; default_grade: str = "B"

    def __init__(self, env: Mapping[str, str], http: Optional[HttpClient]):
        self.env = env; self.http = http

    def is_configured(self) -> bool:
        return all(self.env.get(k) for k in self.env_vars)

    def search(self, query: str, since: Optional[str] = None, until: Optional[str] = None,
               limit: int = 20) -> list[EvidenceRecord]:
        raise NotImplementedError

    def ping(self) -> tuple[bool, str]:
        raise NotImplementedError

    def record(self, **kw) -> EvidenceRecord:
        kw.setdefault("source", self.name); kw.setdefault("grade", self.default_grade)
        kw.setdefault("retrieved_at", now_iso()); kw.setdefault("extra", {})
        return EvidenceRecord(**kw)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_base.py -v` → 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/base.py tests/test_base.py && git commit -m "feat(sources): 근거 레코드·HTTP 캐시·BaseSource"
```

---

### Task 2: 소스 카탈로그와 로더

**Files:**
- Create: `scripts/sources/catalog.py`, Modify: `scripts/sources/__init__.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces:
  - `CATALOG: list[dict]` 각 항목 `{"name","tier","kind","env_vars","impl"}` (`impl`은 `"모듈:클래스"` 문자열 또는 `None`)
  - `load_sources(env, http, kind=None, only=None) -> list[BaseSource]` (구현된 소스만 인스턴스화)
  - `source_statuses(env, http, do_ping=False) -> list[SourceStatus]`

- [ ] **Step 1: 실패하는 테스트**

`tests/test_catalog.py`:
```python
from scripts.sources.catalog import CATALOG
from scripts.sources import load_sources, source_statuses

EXPECTED = {"openalex","crossref","semantic_scholar","arxiv","data_go_kr","kosis","law_go_kr",
            "assembly","naver_news","ecos","kci","nanet","scienceon","ieee","core","springer","lens",
            "scopus","wos","dimensions","exa","tavily","perplexity","serpapi_scholar","dbpia","bigkinds"}

def test_catalog_names_and_fields():
    names = {c["name"] for c in CATALOG}
    assert names == EXPECTED
    for c in CATALOG:
        assert c["tier"] in ("T0","T1","T2","T3")
        assert c["kind"] in ("papers","stats","law","bills","news","web")
        assert isinstance(c["env_vars"], list)

def test_statuses_report_configured_and_implemented():
    st = {s.name: s for s in source_statuses({"KOSIS_API_KEY": "x"}, http=None)}
    assert st["kosis"].configured is True and st["kosis"].implemented is False
    assert st["openalex"].configured is True   # 키 없음 = 항상 설정됨
    assert st["scopus"].configured is False

def test_load_sources_returns_only_implemented(tmp_cache):
    from scripts.sources.base import HttpClient
    srcs = load_sources({}, HttpClient(tmp_cache), kind="papers")
    assert {s.name for s in srcs} >= {"openalex","crossref","semantic_scholar","arxiv"}
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_catalog.py -v` → ImportError

- [ ] **Step 3: 카탈로그 구현**

`scripts/sources/catalog.py`:
```python
"""근거 소스 카탈로그. 이름·등급·종류·환경변수·구현 클래스를 한 곳에 선언한다."""
def _c(name, tier, kind, env_vars, impl=None):
    return {"name": name, "tier": tier, "kind": kind, "env_vars": env_vars, "impl": impl}

CATALOG = [
    # T0 키 없음
    _c("openalex", "T0", "papers", [], "scripts.sources.openalex:OpenAlexSource"),
    _c("crossref", "T0", "papers", [], "scripts.sources.crossref:CrossrefSource"),
    _c("semantic_scholar", "T0", "papers", [], "scripts.sources.semantic_scholar:SemanticScholarSource"),
    _c("arxiv", "T0", "papers", [], "scripts.sources.arxiv_src:ArxivSource"),
    # T1 무료 키·국내 (커넥터는 P4)
    _c("data_go_kr", "T1", "stats", ["DATA_GO_KR_API_KEY"]),
    _c("kosis", "T1", "stats", ["KOSIS_API_KEY"]),
    _c("law_go_kr", "T1", "law", ["LAW_GO_KR_OC"]),
    _c("assembly", "T1", "bills", ["ASSEMBLY_API_KEY"]),
    _c("naver_news", "T1", "news", ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]),
    _c("ecos", "T1", "stats", ["ECOS_API_KEY"]),
    _c("kci", "T1", "papers", ["KCI_API_KEY"]),
    _c("nanet", "T1", "papers", ["NANET_API_KEY"]),
    # T2 무료 키·선택
    _c("scienceon", "T2", "papers", ["SCIENCEON_API_KEY"]),
    _c("ieee", "T2", "papers", ["IEEE_API_KEY"]),
    _c("core", "T2", "papers", ["CORE_API_KEY"]),
    _c("springer", "T2", "papers", ["SPRINGER_API_KEY"]),
    _c("lens", "T2", "papers", ["LENS_API_TOKEN"]),
    # T3 유료·구독
    _c("scopus", "T3", "papers", ["ELSEVIER_API_KEY"]),
    _c("wos", "T3", "papers", ["WOS_API_KEY"]),
    _c("dimensions", "T3", "papers", ["DIMENSIONS_API_KEY"]),
    _c("exa", "T3", "web", ["EXA_API_KEY"]),
    _c("tavily", "T3", "web", ["TAVILY_API_KEY"]),
    _c("perplexity", "T3", "web", ["PERPLEXITY_API_KEY"]),
    _c("serpapi_scholar", "T3", "papers", ["SERPAPI_API_KEY"]),
    _c("dbpia", "T3", "papers", ["DBPIA_API_KEY"]),
    _c("bigkinds", "T3", "news", ["BIGKINDS_API_KEY"]),
]
OPTIONAL_ENV = ["OPENALEX_MAILTO", "CROSSREF_MAILTO", "S2_API_KEY", "ELSEVIER_INSTTOKEN"]
```

`scripts/sources/__init__.py`:
```python
"""소스 로더."""
from __future__ import annotations
import importlib
from typing import Mapping, Optional
from .base import BaseSource, HttpClient, SourceStatus
from .catalog import CATALOG

def _cls(impl: str):
    mod, cls = impl.split(":")
    return getattr(importlib.import_module(mod), cls)

def load_sources(env: Mapping[str, str], http: Optional[HttpClient], kind: Optional[str] = None,
                 only: Optional[list] = None) -> list[BaseSource]:
    out = []
    for c in CATALOG:
        if c["impl"] is None: continue
        if kind and c["kind"] != kind: continue
        if only and c["name"] not in only: continue
        src = _cls(c["impl"])(env, http)
        if src.is_configured(): out.append(src)
    return out

def get_source(name: str, env, http) -> Optional[BaseSource]:
    for c in CATALOG:
        if c["name"] == name and c["impl"]:
            return _cls(c["impl"])(env, http)
    return None

def source_statuses(env: Mapping[str, str], http: Optional[HttpClient], do_ping: bool = False) -> list[SourceStatus]:
    out = []
    for c in CATALOG:
        configured = all(env.get(k) for k in c["env_vars"])
        implemented = c["impl"] is not None
        ok, detail = None, ""
        if not configured:
            detail = "키 없음: " + ", ".join(c["env_vars"])
        elif not implemented:
            detail = "키 있음, 커넥터는 P4에서 구현"
        elif do_ping:
            try:
                ok, detail = _cls(c["impl"])(env, http).ping()
            except Exception as e:  # 네트워크 오류도 상태로 보고
                ok, detail = False, f"오류: {type(e).__name__}"
        else:
            detail = "설정됨"
        out.append(SourceStatus(c["name"], c["tier"], c["kind"], c["env_vars"], configured, implemented, ok, detail))
    return out
```

- [ ] **Step 4: 통과 확인** — Task 3·4의 커넥터가 아직 없으므로 `test_load_sources_returns_only_implemented`는 ImportError로 실패한다. 나머지 2개 통과 확인 후 진행. (Task 4 완료 후 이 파일 전체 통과.)

Run: `python -m pytest tests/test_catalog.py -v -k "names or statuses"` → 2 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/catalog.py scripts/sources/__init__.py tests/test_catalog.py && git commit -m "feat(sources): 카탈로그 26종·로더·상태 조회"
```

---

### Task 3: OpenAlex 커넥터

**Files:**
- Create: `scripts/sources/openalex.py`
- Test: `tests/test_openalex.py`

**Interfaces:**
- Produces: `OpenAlexSource(BaseSource)`; `name="openalex"`, `kind="papers"`; `search()`는 DOI가 있으면 `grade="A"`, 없으면 `"B"`; `extra`에 `doi, type, cited_by_count, venue`.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_openalex.py`:
```python
from unittest.mock import patch
from scripts.sources.base import HttpClient
from scripts.sources.openalex import OpenAlexSource, _abstract_from_inverted

SAMPLE = {"results": [{
    "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/abc",
    "display_name": "5G spectrum policy in Korea", "publication_date": "2024-03-01", "type": "article",
    "cited_by_count": 3,
    "primary_location": {"landing_page_url": "https://pub/1", "source": {"display_name": "Telecom Policy"}},
    "abstract_inverted_index": {"Korea": [0], "spectrum": [1], "policy": [2]}}]}

def test_inverted_abstract():
    assert _abstract_from_inverted({"b": [1], "a": [0]}) == "a b"

def test_search_maps_fields(tmp_cache):
    src = OpenAlexSource({"OPENALEX_MAILTO": "me@x.kr"}, HttpClient(tmp_cache))
    with patch.object(src.http, "get_json", return_value=SAMPLE) as g:
        recs = src.search("5G spectrum", since="2023-01-01", until="2026-09-15", limit=5)
    r = recs[0]
    assert r.source == "openalex" and r.grade == "A" and r.date == "2024-03-01"
    assert r.url == "https://pub/1" and r.extra["doi"].endswith("10.1/abc")
    params = g.call_args.kwargs.get("params") or g.call_args.args[1]
    assert params["mailto"] == "me@x.kr" and "from_publication_date:2023-01-01" in params["filter"]
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_openalex.py -v` → ImportError

- [ ] **Step 3: 구현**

`scripts/sources/openalex.py`:
```python
"""OpenAlex 논문 검색. 키 불필요, mailto로 우대 속도."""
from __future__ import annotations
from .base import BaseSource

API = "https://api.openalex.org/works"

def _abstract_from_inverted(inv: dict | None) -> str:
    if not inv: return ""
    pos = []
    for w, idxs in inv.items():
        for i in idxs: pos.append((i, w))
    return " ".join(w for _, w in sorted(pos))

class OpenAlexSource(BaseSource):
    name = "openalex"; tier = "T0"; kind = "papers"; env_vars = []; default_grade = "B"

    def _params(self, query, since, until, limit):
        filt = []
        if since: filt.append(f"from_publication_date:{since}")
        if until: filt.append(f"to_publication_date:{until}")
        p = {"search": query, "per-page": min(limit, 50), "sort": "relevance_score:desc"}
        if filt: p["filter"] = ",".join(filt)
        if self.env.get("OPENALEX_MAILTO"): p["mailto"] = self.env["OPENALEX_MAILTO"]
        return p

    def search(self, query, since=None, until=None, limit=20):
        data = self.http.get_json(API, params=self._params(query, since, until, limit))
        out = []
        for w in data.get("results", []):
            loc = w.get("primary_location") or {}
            doi = w.get("doi") or ""
            out.append(self.record(
                id=w.get("id", ""), url=loc.get("landing_page_url") or doi or w.get("id", ""),
                title=w.get("display_name") or "", date=w.get("publication_date"),
                snippet=_abstract_from_inverted(w.get("abstract_inverted_index"))[:1000],
                grade="A" if doi else "B", query=query,
                extra={"doi": doi, "type": w.get("type"), "cited_by_count": w.get("cited_by_count"),
                       "venue": ((loc.get("source") or {}).get("display_name"))}))
        return out[:limit]

    def ping(self):
        d = self.http.get_json(API, params={"search": "spectrum", "per-page": 1})
        return ("results" in d), f"OK, 총 {d.get('meta', {}).get('count', '?')}건 색인"
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_openalex.py -v` → 2 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/openalex.py tests/test_openalex.py && git commit -m "feat(sources): OpenAlex 커넥터"
```

---

### Task 4: Crossref·Semantic Scholar·arXiv 커넥터

**Files:**
- Create: `scripts/sources/crossref.py`, `scripts/sources/semantic_scholar.py`, `scripts/sources/arxiv_src.py`
- Test: `tests/test_other_sources.py`

**Interfaces:**
- Produces: `CrossrefSource`, `SemanticScholarSource`, `ArxivSource` (모두 `BaseSource`, `kind="papers"`). arXiv는 `grade="B"`(프리프린트), Crossref는 `"A"`(DOI 보장), S2는 DOI 있으면 `"A"` 아니면 `"B"`.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_other_sources.py`:
```python
from unittest.mock import patch
from scripts.sources.base import HttpClient
from scripts.sources.crossref import CrossrefSource
from scripts.sources.semantic_scholar import SemanticScholarSource
from scripts.sources.arxiv_src import ArxivSource

CR = {"message": {"items": [{"DOI": "10.2/x", "title": ["OTT regulation"], "URL": "https://doi.org/10.2/x",
       "issued": {"date-parts": [[2024, 5, 2]]}, "abstract": "<jats:p>abs</jats:p>",
       "container-title": ["J Media"]}]}}
S2 = {"data": [{"paperId": "p1", "title": "6G spectrum sharing", "abstract": "a", "year": 2025,
       "publicationDate": "2025-02-01", "url": "https://s2/p1", "externalIds": {"DOI": "10.3/y"},
       "tldr": {"text": "short"}}]}
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2501.00001v1</id><title>Spectrum sharing for 6G</title>
<summary>sum</summary><published>2025-01-02T00:00:00Z</published></entry></feed>"""

def test_crossref(tmp_cache):
    s = CrossrefSource({}, HttpClient(tmp_cache))
    with patch.object(s.http, "get_json", return_value=CR):
        r = s.search("OTT", since="2023-01-01")[0]
    assert r.grade == "A" and r.date == "2024-05-02" and r.snippet == "abs" and r.extra["venue"] == "J Media"

def test_semantic_scholar_header_when_key(tmp_cache):
    s = SemanticScholarSource({"S2_API_KEY": "k"}, HttpClient(tmp_cache))
    with patch.object(s.http, "get_json", return_value=S2) as g:
        r = s.search("6G", since="2023-01-01", until="2026-12-31")[0]
    assert r.grade == "A" and r.snippet == "short" and g.call_args.kwargs["headers"]["x-api-key"] == "k"
    assert g.call_args.kwargs["params"]["year"] == "2023-2026"

def test_arxiv_parses_atom_and_filters_date(tmp_cache):
    s = ArxivSource({}, HttpClient(tmp_cache))
    with patch.object(s.http, "get_text", return_value=ATOM):
        assert len(s.search("6G", since="2025-06-01")) == 0
        r = s.search("6G", since="2024-01-01")[0]
    assert r.grade == "B" and r.date == "2025-01-02" and r.url.startswith("http://arxiv.org/abs/")
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_other_sources.py -v` → ImportError

- [ ] **Step 3: 구현**

`scripts/sources/crossref.py`:
```python
"""Crossref 메타데이터 검색. 키 불필요."""
from __future__ import annotations
import re
from .base import BaseSource
API = "https://api.crossref.org/works"

def _date(item):
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    if not parts or parts[0] is None: return None
    y, m, d = (list(parts) + [1, 1])[:3]
    return f"{y:04d}-{m:02d}-{d:02d}"

class CrossrefSource(BaseSource):
    name = "crossref"; tier = "T0"; kind = "papers"; env_vars = []; default_grade = "A"
    def search(self, query, since=None, until=None, limit=20):
        filt = []
        if since: filt.append(f"from-pub-date:{since}")
        if until: filt.append(f"until-pub-date:{until}")
        p = {"query": query, "rows": min(limit, 50)}
        if filt: p["filter"] = ",".join(filt)
        if self.env.get("CROSSREF_MAILTO"): p["mailto"] = self.env["CROSSREF_MAILTO"]
        items = (self.http.get_json(API, params=p).get("message") or {}).get("items", [])
        out = []
        for it in items:
            abs_ = re.sub(r"<[^>]+>", "", it.get("abstract") or "").strip()
            out.append(self.record(id=it.get("DOI", ""), url=it.get("URL", ""),
                                   title=(it.get("title") or [""])[0], date=_date(it), snippet=abs_[:1000],
                                   query=query, extra={"doi": it.get("DOI"), "type": it.get("type"),
                                                       "venue": (it.get("container-title") or [None])[0]}))
        return out[:limit]
    def ping(self):
        d = self.http.get_json(API, params={"rows": 1, "query": "spectrum"})
        return ("message" in d), "OK"
```

`scripts/sources/semantic_scholar.py`:
```python
"""Semantic Scholar Graph API. 키 선택(x-api-key)."""
from __future__ import annotations
from .base import BaseSource
API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,publicationDate,url,externalIds,tldr,venue,citationCount"

class SemanticScholarSource(BaseSource):
    name = "semantic_scholar"; tier = "T0"; kind = "papers"; env_vars = []; default_grade = "B"
    def _headers(self):
        return {"x-api-key": self.env["S2_API_KEY"]} if self.env.get("S2_API_KEY") else {}
    def search(self, query, since=None, until=None, limit=20):
        p = {"query": query, "limit": min(limit, 100), "fields": FIELDS}
        if since or until:
            p["year"] = f"{(since or '1900')[:4]}-{(until or '2100')[:4]}"
        data = self.http.get_json(API, params=p, headers=self._headers())
        out = []
        for d in data.get("data", []):
            doi = (d.get("externalIds") or {}).get("DOI")
            tldr = (d.get("tldr") or {}).get("text")
            out.append(self.record(id=d.get("paperId", ""), url=d.get("url", ""), title=d.get("title", ""),
                                   date=d.get("publicationDate") or (str(d["year"]) if d.get("year") else None),
                                   snippet=(tldr or d.get("abstract") or "")[:1000], grade="A" if doi else "B",
                                   query=query, extra={"doi": doi, "venue": d.get("venue"),
                                                       "citationCount": d.get("citationCount")}))
        return out[:limit]
    def ping(self):
        d = self.http.get_json(API, params={"query": "spectrum", "limit": 1, "fields": "title"}, headers=self._headers())
        return ("data" in d), "OK" + (" (키 사용)" if self.env.get("S2_API_KEY") else " (키 없음, 낮은 쿼터)")
```

`scripts/sources/arxiv_src.py`:
```python
"""arXiv Atom API. 키 불필요. 날짜 필터는 클라이언트에서. XML은 defusedxml로 파싱(XXE 방지)."""
from __future__ import annotations
import defusedxml.ElementTree as ET
from .base import BaseSource
API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}

class ArxivSource(BaseSource):
    name = "arxiv"; tier = "T0"; kind = "papers"; env_vars = []; default_grade = "B"
    def search(self, query, since=None, until=None, limit=20):
        p = {"search_query": f"all:{query}", "start": 0, "max_results": min(limit * 3, 100),
             "sortBy": "submittedDate", "sortOrder": "descending"}
        root = ET.fromstring(self.http.get_text(API, params=p))
        out = []
        for e in root.findall("a:entry", NS):
            date = (e.findtext("a:published", default="", namespaces=NS) or "")[:10]
            if since and date < since: continue
            if until and date > until: continue
            aid = e.findtext("a:id", default="", namespaces=NS)
            out.append(self.record(id=aid, url=aid, title=" ".join((e.findtext("a:title", default="", namespaces=NS)).split()),
                                   date=date or None, snippet=" ".join((e.findtext("a:summary", default="", namespaces=NS)).split())[:1000],
                                   query=query, extra={"preprint": True}))
        return out[:limit]
    def ping(self):
        root = ET.fromstring(self.http.get_text(API, params={"search_query": "all:spectrum", "max_results": 1}))
        return (root.find("a:entry", NS) is not None), "OK"
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_other_sources.py tests/test_catalog.py -v` → 6 passed (Task 2의 로더 테스트 포함)

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/crossref.py scripts/sources/semantic_scholar.py scripts/sources/arxiv_src.py tests/test_other_sources.py && git commit -m "feat(sources): Crossref·Semantic Scholar·arXiv 커넥터"
```

---

### Task 5: `evidence.py` CLI — `papers`, `doctor`

**Files:**
- Create: `scripts/evidence.py`
- Test: `tests/test_evidence_cli.py`

**Interfaces:**
- Produces:
  - `python scripts/evidence.py papers --q "<질의>" [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--limit N] [--sources a,b] [--out path.jsonl] [--no-cache]` → JSONL 저장, 표준출력에 소스별 건수 표. 기본 출력 경로 `kb/evidence/<YYYYMMDD_HHMMSS>_papers_<slug>.jsonl`
  - `python scripts/evidence.py doctor [--json] [--no-ping]` → 소스 상태 표(이름·등급·종류·키·구현·연결·비고). 종료코드 0.
  - 함수 `run_papers(args, env, http) -> list[dict]`, `run_doctor(env, http, do_ping) -> list[SourceStatus]`, `load_env(root) -> dict`(`.env` + OS env 병합), `main(argv=None) -> int`

- [ ] **Step 1: 실패하는 테스트**

`tests/test_evidence_cli.py`:
```python
import json
from unittest.mock import patch
from scripts import evidence
from scripts.sources.base import EvidenceRecord

def _rec(src):
    return EvidenceRecord(source=src, id="1", url="u", title="t", date="2024-01-01", snippet="s",
                          grade="B", retrieved_at="x", query="q")

def test_papers_writes_jsonl(tmp_path, tmp_cache, monkeypatch):
    out = tmp_path / "o.jsonl"
    class Fake:
        name = "openalex"
        def search(self, *a, **k): return [_rec("openalex"), _rec("openalex")]
    with patch.object(evidence, "load_sources", return_value=[Fake()]):
        rc = evidence.main(["papers", "--q", "5G", "--out", str(out), "--cache-dir", str(tmp_cache)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["source"] == "openalex"

def test_doctor_table_lists_all_and_hides_key_values(capsys, tmp_cache):
    env = {"KOSIS_API_KEY": "SECRET123"}
    with patch.object(evidence, "load_env", return_value=env):
        rc = evidence.main(["doctor", "--no-ping", "--cache-dir", str(tmp_cache)])
    out = capsys.readouterr().out
    assert rc == 0 and "kosis" in out and "scopus" in out and "SECRET123" not in out

def test_doctor_json(capsys, tmp_cache):
    with patch.object(evidence, "load_env", return_value={}):
        evidence.main(["doctor", "--no-ping", "--json", "--cache-dir", str(tmp_cache)])
    data = json.loads(capsys.readouterr().out)
    assert any(d["name"] == "openalex" and d["configured"] for d in data)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_evidence_cli.py -v` → ImportError

- [ ] **Step 3: 구현**

`scripts/evidence.py`:
```python
"""근거 수집 CLI. papers / doctor (stats·law·bills·news는 P4에서 추가)."""
from __future__ import annotations
import argparse, json, os, re, sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from scripts.sources import load_sources, source_statuses
from scripts.sources.base import HttpClient

ROOT = Path(__file__).resolve().parents[1]

def load_env(root: Path = ROOT) -> dict:
    env = dict(dotenv_values(root / ".env")) if (root / ".env").exists() else {}
    for k, v in os.environ.items():
        if k in env or k.endswith(("_API_KEY", "_MAILTO", "_OC", "_CLIENT_ID", "_CLIENT_SECRET", "_TOKEN", "_INSTTOKEN")):
            env.setdefault(k, v)
    return {k: v for k, v in env.items() if v}

def _slug(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", s).strip("_")[:40] or "q"

def run_papers(args, env, http) -> list[dict]:
    only = args.sources.split(",") if args.sources else None
    rows, counts = [], {}
    for src in load_sources(env, http, kind="papers", only=only):
        try:
            recs = src.search(args.q, since=args.since, until=args.until, limit=args.limit)
        except Exception as e:
            print(f"[{src.name}] 오류: {type(e).__name__}: {e}", file=sys.stderr); recs = []
        counts[src.name] = len(recs); rows += [r.to_json() for r in recs]
    out = Path(args.out) if args.out else ROOT / "kb" / "evidence" / f"{datetime.now():%Y%m%d_%H%M%S}_papers_{_slug(args.q)}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"질의: {args.q}  기간: {args.since or '-'}~{args.until or '-'}")
    for k, v in counts.items(): print(f"  {k:<18} {v:>4}건")
    print(f"저장: {out}  (총 {len(rows)}건)")
    return rows

def run_doctor(env, http, do_ping: bool):
    return source_statuses(env, http, do_ping=do_ping)

def _print_doctor(statuses):
    print(f"{'소스':<18}{'등급':<5}{'종류':<8}{'키':<6}{'구현':<6}{'연결':<6}비고")
    for s in statuses:
        key = "있음" if s.configured and s.env_vars else ("불필요" if s.configured else "없음")
        impl = "예" if s.implemented else "P4"
        ok = "-" if s.ok is None else ("OK" if s.ok else "실패")
        print(f"{s.name:<18}{s.tier:<5}{s.kind:<8}{key:<6}{impl:<6}{ok:<6}{s.detail}")

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evidence", description="근거 소스 수집·상태 점검")
    ap.add_argument("--cache-dir", default=str(ROOT / "kb" / "cache"))
    ap.add_argument("--no-cache", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("papers", help="논문·보고서 검색")
    p.add_argument("--q", required=True); p.add_argument("--since"); p.add_argument("--until")
    p.add_argument("--limit", type=int, default=20); p.add_argument("--sources"); p.add_argument("--out")
    d = sub.add_parser("doctor", help="소스 키·연결 상태")
    d.add_argument("--json", action="store_true"); d.add_argument("--no-ping", action="store_true")
    args = ap.parse_args(argv)
    env = load_env(); http = HttpClient(Path(args.cache_dir), no_cache=args.no_cache)
    if args.cmd == "papers":
        run_papers(args, env, http); return 0
    statuses = run_doctor(env, http, do_ping=not args.no_ping)
    if args.json: print(json.dumps([asdict(s) for s in statuses], ensure_ascii=False, indent=1))
    else: _print_doctor(statuses)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_evidence_cli.py -v` → 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/evidence.py tests/test_evidence_cli.py && git commit -m "feat: evidence.py CLI (papers, doctor)"
```

---

### Task 6: 스키마 8종과 `validate.py`

**Files:**
- Create: `templates/schemas/evidence_record.schema.json`, `conclusion.schema.json`, `chain.schema.json`, `claim.schema.json`, `verdict.schema.json`, `event.schema.json`, `comparison_row.schema.json`, `run_config.schema.json`, `scripts/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Produces: `validate_obj(obj, schema_name) -> list[str]`, `validate_file(path, schema_name) -> list[str]`(`.jsonl`은 행별, `.json`은 배열이면 원소별), CLI `python scripts/validate.py <file> --schema <name>` (오류 0이면 종료 0, 아니면 1과 오류 목록).

- [ ] **Step 1: 실패하는 테스트**

`tests/test_validate.py`:
```python
import json
from scripts.validate import validate_obj, validate_file

def test_claim_schema_requires_fields():
    errs = validate_obj({"claim_id": "R01-F-001"}, "claim")
    assert errs and any("type" in e or "statement" in e for e in errs)

def test_valid_claim_and_verdict():
    claim = {"claim_id": "R01-F-001", "conclusion_id": "R01-K-Fc-01", "type": "F", "page": 57,
             "statement": "2025년 5G 가입자 4,120만 명", "original_value": {"metric": "5G 가입자", "year": 2025, "value": 41200000, "unit": "명"},
             "assumptions": ["연 12% 순증"], "verify_method": "backtest", "data_sources_hint": ["kosis"]}
    assert validate_obj(claim, "claim") == []
    verdict = {"claim_id": "R01-F-001", "verdict": "과대", "current_value": {"value": 36000000, "unit": "명", "asof": "2025-12"},
               "reason": "실적 대비 +14%", "evidence": [{"url": "https://kosis.kr/x", "grade": "A", "retrieved_at": "2026-09-15"}]}
    assert validate_obj(verdict, "verdict") == []

def test_conclusion_and_comparison_row_and_run_config():
    k = {"conclusion_id": "R01-K-Fc-01", "kind": "Fc", "statement": "…", "page": 57, "method": "시계열 추정",
         "premises": ["P-01"], "evidence_refs": ["R01-F-001"], "types": ["F"]}
    assert validate_obj(k, "conclusion") == []
    row = {"row_id": "K-Fc-01", "level": "conclusion", "location": "4장 2절 p.57", "old": "…", "new": "…",
           "change_type": "수치갱신", "verdict": "부분수정", "reason_locus": ["E"], "evidence_ids": ["ev1"],
           "grade": "A", "status": "L2 최종", "linked_conclusions": ["R01-K-Fc-01"]}
    assert validate_obj(row, "comparison_row") == []
    rc = {"report_id": "R01", "layers": ["L0"], "options": {"blind_rerun": {"enabled": True, "repeats": 1},
          "survey_redesign": True, "experiment_plan": True, "synthetic_sim": {"enabled": False, "panel_size": 200},
          "l0_rewrite_scope": "env_and_desk_updatable"}, "sources": ["openalex"], "output": ["hwpx", "html"],
          "period": {"since": "2023-04-20", "until": "today"}}
    assert validate_obj(rc, "run_config") == []

def test_validate_jsonl_file(tmp_path):
    p = tmp_path / "e.jsonl"
    good = {"source": "openalex", "id": "1", "url": "u", "title": "t", "date": None, "snippet": "", "grade": "A",
            "retrieved_at": "2026-09-15T00:00:00", "query": "q", "extra": {}}
    bad = dict(good, grade="Z")
    p.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
    errs = validate_file(p, "evidence_record")
    assert len(errs) == 1 and errs[0].startswith("행 2")
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_validate.py -v` → ImportError

- [ ] **Step 3: 스키마 작성** (모두 `templates/schemas/`, `$schema` 는 draft-07)

`evidence_record.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"근거 레코드","type":"object",
 "required":["source","id","url","title","snippet","grade","retrieved_at","query"],
 "properties":{"source":{"type":"string"},"id":{"type":"string"},"url":{"type":"string"},"title":{"type":"string"},
  "date":{"type":["string","null"]},"snippet":{"type":"string"},"grade":{"enum":["A","B","C"]},
  "retrieved_at":{"type":"string"},"query":{"type":"string"},"extra":{"type":"object"}},"additionalProperties":false}
```
`conclusion.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"결론(K)","type":"object",
 "required":["conclusion_id","kind","statement","page","method","premises","evidence_refs","types"],
 "properties":{"conclusion_id":{"type":"string","pattern":"^R\\d{2}-K-(RQ|F|Fc|R)-\\d{2}$"},
  "kind":{"enum":["RQ","F","Fc","R"]},"statement":{"type":"string","minLength":1},"page":{"type":"integer"},
  "method":{"type":"string"},"premises":{"type":"array","items":{"type":"string"}},
  "evidence_refs":{"type":"array","items":{"type":"string"}},
  "types":{"type":"array","items":{"enum":["F","M","S","P","T","B","G"]}},
  "rerun_grade":{"enum":["R1","R2","R3"]}}}
```
`chain.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"논증 사슬","type":"object",
 "required":["report_id","conclusions","premises","edges"],
 "properties":{"report_id":{"type":"string"},
  "conclusions":{"type":"array","items":{"$ref":"conclusion.schema.json"}},
  "premises":{"type":"array","items":{"type":"object","required":["premise_id","statement","section","page"],
    "properties":{"premise_id":{"type":"string","pattern":"^P-\\d{2,3}$"},"statement":{"type":"string"},
     "section":{"type":"string"},"page":{"type":"integer"},"indicator":{"type":"string"}}}},
  "edges":{"type":"array","items":{"type":"object","required":["from","to","relation"],
    "properties":{"from":{"type":"string"},"to":{"type":"string"},"relation":{"enum":["premise_of","evidence_of","supports","cites"]},
     "confidence":{"type":"number","minimum":0,"maximum":1}}}}}}
```
`claim.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"주장(E 단위)","type":"object",
 "required":["claim_id","conclusion_id","type","page","statement","verify_method"],
 "properties":{"claim_id":{"type":"string","pattern":"^R\\d{2}-[FMSPTBG]-\\d{3}$"},"conclusion_id":{"type":"string"},
  "type":{"enum":["F","M","S","P","T","B","G"]},"page":{"type":"integer"},"statement":{"type":"string","minLength":1},
  "original_value":{"type":"object","properties":{"metric":{"type":"string"},"year":{"type":"integer"},
    "value":{"type":["number","string"]},"unit":{"type":"string"}}},
  "assumptions":{"type":"array","items":{"type":"string"}},
  "verify_method":{"enum":["backtest","model_rerun","survey_map","policy_track","standard_track","case_refresh","kpi_track"]},
  "data_sources_hint":{"type":"array","items":{"type":"string"}}}}
```
`verdict.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"근거 판정","type":"object",
 "required":["claim_id","verdict","reason","evidence"],
 "properties":{"claim_id":{"type":"string"},
  "verdict":{"enum":["적중","과대","과소","유효","수정필요","폐기","검증불가"]},
  "current_value":{"type":"object"},"reason":{"type":"string"},
  "evidence":{"type":"array","minItems":1,"items":{"type":"object","required":["url","grade","retrieved_at"],
    "properties":{"url":{"type":"string"},"grade":{"enum":["A","B","C"]},"retrieved_at":{"type":"string"},"note":{"type":"string"}}}}}}
```
`event.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"환경 사건","type":"object",
 "required":["event_id","domain","date","title","summary","sources","grade"],
 "properties":{"event_id":{"type":"string","pattern":"^E-[a-z0-9_]+-\\d{4}-\\d{2}-[a-z0-9_]+$"},
  "domain":{"enum":["spectrum","emf_inspection","broadcast_media","network_5g6g","ict_qualification","kca_management"]},
  "date":{"type":"string","pattern":"^\\d{4}-\\d{2}(-\\d{2})?$"},"title":{"type":"string"},"summary":{"type":"string"},
  "affected_indicators":{"type":"array","items":{"type":"string"}},
  "sources":{"type":"array","minItems":1,"items":{"type":"object","required":["url","retrieved_at"],
    "properties":{"url":{"type":"string"},"title":{"type":"string"},"retrieved_at":{"type":"string"}}}},
  "grade":{"enum":["A","B","C"]}}}
```
`comparison_row.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"신구 대조표 행","type":"object",
 "required":["row_id","level","location","old","new","change_type","grade","status"],
 "properties":{"row_id":{"type":"string"},"level":{"enum":["conclusion","section","table","claim","recommendation"]},
  "location":{"type":"string"},"old":{"type":"string"},"new":{"type":"string"},
  "change_type":{"enum":["유지","수치갱신","서술수정","폐기","신규추가","재수행필요"]},
  "verdict":{"enum":["동일","강화","부분수정","약화","뒤집힘","신규결론","판정불가"]},
  "reason_locus":{"type":"array","items":{"enum":["P","E","M"]}},
  "evidence_ids":{"type":"array","items":{"type":"string"}},"grade":{"enum":["A","B","C"]},
  "status":{"enum":["L0 잠정","L1 근거갱신","L2 최종","R3 설계서"]},
  "linked_conclusions":{"type":"array","items":{"type":"string"}},
  "upstream":{"type":"array","items":{"type":"string"}},"blind_new":{"type":"string"}}}
```
`run_config.schema.json`:
```json
{"$schema":"http://json-schema.org/draft-07/schema#","title":"실행 설정","type":"object",
 "required":["report_id","layers","options","sources","output","period"],
 "properties":{"report_id":{"type":"string","pattern":"^R\\d{2}$"},
  "layers":{"type":"array","minItems":1,"items":{"enum":["L0","L1","L2"]}},
  "options":{"type":"object","required":["blind_rerun","survey_redesign","experiment_plan","synthetic_sim","l0_rewrite_scope"],
   "properties":{"blind_rerun":{"type":"object","required":["enabled"],"properties":{"enabled":{"type":"boolean"},"repeats":{"type":"integer","minimum":1,"maximum":5}}},
    "survey_redesign":{"type":"boolean"},"experiment_plan":{"type":"boolean"},
    "synthetic_sim":{"type":"object","required":["enabled"],"properties":{"enabled":{"type":"boolean"},"panel_size":{"type":"integer","minimum":10}}},
    "l0_rewrite_scope":{"enum":["env_only","env_and_desk_updatable"]}}},
  "sources":{"type":"array","items":{"type":"string"}},
  "output":{"type":"array","minItems":1,"items":{"enum":["hwpx","html"]}},
  "period":{"type":"object","required":["since","until"],"properties":{"since":{"type":"string"},"until":{"type":"string"}}}}}
```

- [ ] **Step 4: `validate.py` 구현**

```python
"""JSON/JSONL 스키마 검증. 사용: python scripts/validate.py <file> --schema <name>"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from jsonschema import Draft7Validator, RefResolver

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "templates" / "schemas"

def _validator(schema_name: str) -> Draft7Validator:
    path = SCHEMA_DIR / f"{schema_name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    resolver = RefResolver(base_uri=path.as_uri(), referrer=schema)
    return Draft7Validator(schema, resolver=resolver)

def validate_obj(obj, schema_name: str) -> list[str]:
    v = _validator(schema_name)
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in v.iter_errors(obj)]

def validate_file(path, schema_name: str) -> list[str]:
    path = Path(path); errs = []
    if path.suffix == ".jsonl":
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            errs += [f"행 {i}: {m}" for m in validate_obj(json.loads(line), schema_name)]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        for i, obj in enumerate(items, 1):
            errs += [f"항목 {i}: {m}" for m in validate_obj(obj, schema_name)]
    return errs

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--schema", required=True)
    a = ap.parse_args(argv); errs = validate_file(a.file, a.schema)
    print("검증 통과" if not errs else "\n".join(errs)); return 0 if not errs else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/test_validate.py -v` → 4 passed

- [ ] **Step 6: Commit**

```bash
git add templates/schemas scripts/validate.py tests/test_validate.py && git commit -m "feat: 스키마 8종과 validate.py"
```

---

### Task 7: 분류체계·판정 규칙·도메인 프로파일·출처 신뢰도

**Files:**
- Create: `templates/taxonomy.yaml`, `templates/verdict_rules.yaml`, `kb/domains/{spectrum,emf_inspection,broadcast_media,network_5g6g,ict_qualification,kca_management}.yaml`, `kb/sources.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: `taxonomy.yaml`의 `types[]`(code, name, strategy, verify_method, rerun_grade), `verdict_rules.yaml`의 `verdicts[]`와 `numeric_rules`, 도메인 yaml의 `id, name, indicators[], laws[], agencies[], standards[], journals[], news_keywords[]`.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_templates.py`:
```python
import yaml

def test_taxonomy_has_7_types(ROOT):
    t = yaml.safe_load((ROOT / "templates" / "taxonomy.yaml").read_text(encoding="utf-8"))
    assert [x["code"] for x in t["types"]] == ["F","M","S","P","T","B","G"]
    for x in t["types"]:
        assert x["verify_method"] in ("backtest","model_rerun","survey_map","policy_track","standard_track","case_refresh","kpi_track")
        assert x["rerun_grade"] in ("R1","R1~R2","R2~R3")

def test_verdict_rules(ROOT):
    v = yaml.safe_load((ROOT / "templates" / "verdict_rules.yaml").read_text(encoding="utf-8"))
    assert [x["name"] for x in v["verdicts"]] == ["동일","강화","부분수정","약화","뒤집힘","신규결론","판정불가"]
    assert v["numeric_rules"]["same_within_pct"] == 10

def test_domains(ROOT):
    ids = {"spectrum","emf_inspection","broadcast_media","network_5g6g","ict_qualification","kca_management"}
    files = {p.stem for p in (ROOT / "kb" / "domains").glob("*.yaml")}
    assert files == ids
    for p in (ROOT / "kb" / "domains").glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert d["id"] == p.stem
        for key in ("name","indicators","laws","agencies","standards","journals","news_keywords"):
            assert key in d
        for ind in d["indicators"]:
            assert {"name","source","locator"} <= set(ind)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_templates.py -v` → FileNotFoundError

- [ ] **Step 3: taxonomy.yaml**

```yaml
# 연구유형 분류체계. 유형은 결론의 방법(M)과 근거(E)에 붙는다. 한 보고서에 여러 유형이 혼재한다.
types:
  - code: F
    name: 전망·예측형
    signals: [시장규모 전망, 가입자 전망, 트래픽 예측, 시나리오, "년까지", CAGR]
    strategy: 실적 수집 → 백테스트(예측 vs 실적) → 판정 → 최신 데이터로 재전망
    verify_method: backtest
    rerun_grade: R1
  - code: M
    name: 경제성·계량분석형
    signals: [후생효과, NPV, 편익, 탄력성, 회귀, 파라미터, 할인율, 경제성 분석]
    strategy: 수식·가정 복원 → 입력값 갱신 → 재계산 → 민감도 분석
    verify_method: model_rerun
    rerun_grade: R1~R2
  - code: S
    name: 실태조사·설문형
    signals: [설문, 응답자, 표본, FGI, 인터뷰, "%가 응답", 실태조사]
    strategy: 이후 공식조사로 대체 → 없으면 재설문 설계서 → 옵션 합성패널(C등급)
    verify_method: survey_map
    rerun_grade: R2~R3
  - code: P
    name: 정책·제도 대안형
    signals: [개선방안, 법제, 제도 개선, 정책 방향, 추진체계, 제언]
    strategy: 채택·입법·시행 추적 → 환경 변화 대비 유효성 → 유지/수정/폐기/신규
    verify_method: policy_track
    rerun_grade: R1
  - code: T
    name: 기술·표준·실험형
    signals: [측정방법, 실험, 3GPP, ITU, 표준, 시험, 검증]
    strategy: 표준·기술 변화 추적 → 재실험 계획서 → 계산 가능한 부분은 시뮬레이션
    verify_method: standard_track
    rerun_grade: R2~R3
  - code: B
    name: 사례·동향 조사형
    signals: [해외 사례, 동향, 벤치마킹, 미국, 일본, EU]
    strategy: 사례별 현재 상태 추적 → 신규 사례 추가
    verify_method: case_refresh
    rerun_grade: R1
  - code: G
    name: 기관 전략·사업 기획형
    signals: [중장기 전략, 조직, KPI, 사업 개편, 로드맵]
    strategy: 실행 여부·KPI 달성도 추적 → 전략 재정렬
    verify_method: kpi_track
    rerun_grade: R1~R2
rerun_grades:
  R1: 즉시 재수행(공개 데이터·데스크리서치·모델 재계산)
  R2: 대체 재수행(프록시 데이터·유사 최신조사 대입)
  R3: 계획만 수립(설문·실험·실측 필요 → 설계서, 판정 불가)
```

- [ ] **Step 4: verdict_rules.yaml**

```yaml
# 결론 판정 어휘와 수치 규칙. 비교기가 원 결론(K)·추적 재도출(K')·블라인드(K'')를 놓고 적용한다.
verdicts:
  - {name: 동일, rule: 방향 동일 + 수치 오차 same_within_pct 이내 + 블라인드도 같은 방향}
  - {name: 강화, rule: 방향 동일 + 근거 등급 상승 또는 효과 크기 증가 ≥ strengthen_pct}
  - {name: 부분수정, rule: 방향 동일 + 오차 same_within_pct 초과 ~ partial_within_pct 이내, 또는 조건·범위 변경}
  - {name: 약화, rule: 방향 동일 + 근거 등급 하락 또는 효과 크기 감소 ≥ strengthen_pct}
  - {name: 뒤집힘, rule: 부호·방향 반전, 또는 제언이 반대 정책으로 대체}
  - {name: 신규결론, rule: 원 연구에 없던 결론이 K' 또는 K''에서 A/B 근거로 도출}
  - {name: 판정불가, rule: 근거 E를 재수집할 수 없음(설문·실험·실측 필요) → R3, 설계서 첨부}
numeric_rules:
  same_within_pct: 10
  partial_within_pct: 30
  strengthen_pct: 20
reason_locus: [P, E, M]      # 달라진 이유의 위치: 전제 / 근거 / 방법
blind_agreement:
  required_for_same: true    # "동일"은 블라인드 결론과도 방향이 일치해야 한다
  disagreement_downgrade: 부분수정
```

- [ ] **Step 5: 도메인 프로파일 6개** (`kb/domains/`)

`spectrum.yaml`:
```yaml
id: spectrum
name: 전파자원·주파수
indicators:
  - {name: 5G 가입자 수, source: msit, locator: "과기정통부 무선통신서비스 가입 현황(월별)", unit: 명}
  - {name: 이동통신 트래픽, source: msit, locator: "과기정통부 무선데이터 트래픽 통계", unit: TB}
  - {name: 주파수 할당대가, source: msit, locator: "주파수 할당 공고·경매 결과 보도자료", unit: 억원}
  - {name: 이음5G 사업자 수, source: kca, locator: "KCA 이음5G 현황", unit: 개}
laws: [전파법, 전파법 시행령, 주파수 할당 고시]
agencies: [과학기술정보통신부, 한국방송통신전파진흥원, 국립전파연구원, 중앙전파관리소]
standards: [ITU-R, 3GPP, WRC 결과]
journals: [한국통신학회논문지, 정보통신정책연구, KISDI 보고서, 전파진흥원 이슈리포트]
news_keywords: [주파수 경매, 28GHz, 제4이동통신, 이음5G, 주파수 재할당, 6G 주파수, WRC-27]
```
`emf_inspection.yaml`:
```yaml
id: emf_inspection
name: 전파검사·전자파
indicators:
  - {name: 무선국 수, source: msit, locator: "무선국 통계(국립전파연구원·KCA)", unit: 국}
  - {name: 전자파 민원 건수, source: kca, locator: "전자파안전정보센터 연보", unit: 건}
laws: [전파법, 전자파 인체보호기준 고시, 무선설비규칙]
agencies: [국립전파연구원, 한국방송통신전파진흥원 전자파안전정보센터, 중앙전파관리소]
standards: [ICNIRP 2020, IEC 62232, ITU-T K.52]
journals: [한국전자파학회논문지, 전파연구원 보고서]
news_keywords: [전자파 인체보호, 무선국 검사, 5G 전자파, 전기차 충전 전자파]
```
`broadcast_media.yaml`:
```yaml
id: broadcast_media
name: 방송·미디어·OTT
indicators:
  - {name: 유료방송 가입자, source: msit, locator: "유료방송 가입자 수 검증 결과(반기)", unit: 명}
  - {name: 방송사업 매출, source: kisdi, locator: "방송산업 실태조사·방송통계포털", unit: 억원}
  - {name: OTT 이용률, source: kmcc, locator: "방송매체 이용행태조사", unit: "%"}
  - {name: 홈쇼핑 송출수수료, source: kmcc, locator: "방송사업자 재산상황 공표집", unit: 억원}
laws: [방송법, 인터넷 멀티미디어 방송사업법, 전기통신사업법, 통합미디어법(안)]
agencies: [방송미디어통신위원회, 과학기술정보통신부, 한국방송통신전파진흥원, KISDI]
standards: []
journals: [방송통신연구, 한국방송학보, 정보통신정책연구, KISDI 보고서, 국회입법조사처]
news_keywords: [OTT 규제, 티빙 웨이브 합병, 넷플릭스 광고요금제, 유료방송 가입자 감소, 통합미디어법, 홈쇼핑 송출수수료]
```
`network_5g6g.yaml`:
```yaml
id: network_5g6g
name: 통신망·5G/6G·위성
indicators:
  - {name: 5G 기지국 수, source: msit, locator: "무선국 현황(5G)", unit: 국}
  - {name: 저궤도 위성 서비스 가입, source: news, locator: "스타링크 국내 서비스 관련 보도", unit: 명}
laws: [전기통신사업법, 전파법, 위성통신 관련 고시]
agencies: [과학기술정보통신부, 국립전파연구원, 한국방송통신전파진흥원]
standards: [3GPP Release 18/19/20, ITU-R IMT-2030, WRC-27 의제]
journals: [한국통신학회논문지, ETRI 전자통신동향분석, IEEE Communications]
news_keywords: [6G, 3GPP Release 19, 스타링크 한국, 위성통신 주파수, 오픈랜]
```
`ict_qualification.yaml`:
```yaml
id: ict_qualification
name: 기술자격
indicators:
  - {name: 국가기술자격 응시자 수(ICT), source: kca, locator: "KCA 자격검정 통계", unit: 명}
laws: [국가기술자격법, 국가기술자격법 시행령]
agencies: [한국방송통신전파진흥원 자격검정본부, 고용노동부, 과학기술정보통신부]
standards: [NCS]
journals: [직업능력개발연구, KRIVET 보고서]
news_keywords: [정보보안기사, 국가기술자격 개편, 디지털 배지, CBT 전환]
```
`kca_management.yaml`:
```yaml
id: kca_management
name: 기관 경영·사업
indicators:
  - {name: 방송통신발전기금 규모, source: msit, locator: "방송통신발전기금 운용계획", unit: 억원}
laws: [방송통신발전 기본법, 공공기관의 운영에 관한 법률]
agencies: [한국방송통신전파진흥원, 과학기술정보통신부, 기획재정부]
standards: []
journals: [알리오 경영공시, KCA 경영전략 문서]
news_keywords: [KCA 중장기 경영전략, 빛마루, 방송통신발전기금]
```

- [ ] **Step 6: kb/sources.md**

```markdown
# 출처 신뢰도 기본 등급
| 출처 유형 | 기본 등급 | 예 |
|---|---|---|
| 정부·공공기관 통계·공고·보도자료, 법령·고시, 표준문서, 학술지 원문(DOI) | A | 과기정통부, KOSIS, 법제처, 3GPP, KCI 논문 |
| 업계 보고서·리서치사·언론 기사·프리프린트 | B | 언론, arXiv, 컨설팅 보고서 |
| 추정·시뮬레이션·블라인드 재수행 결론·합성 패널 | C | 하네스 산출 추정치 |
규칙: 같은 사실에 A와 B가 있으면 A를 인용한다. B만 있으면 2개 이상 교차확인 후 채택하고 교차 여부를 기록한다.
```

- [ ] **Step 7: 통과 확인** — `python -m pytest tests/test_templates.py -v` → 3 passed

- [ ] **Step 8: Commit**

```bash
git add templates/taxonomy.yaml templates/verdict_rules.yaml kb/domains kb/sources.md tests/test_templates.py && git commit -m "feat: 분류체계·판정 규칙·도메인 프로파일 6종·출처 등급"
```

---

### Task 8: 레지스트리

**Files:**
- Create: `scripts/registry.py`, `registry.csv`(init 결과)
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `COLUMNS = ["id","title","published","domain","types","maturity","updated_at","source_pdf"]`; `load_registry(path) -> list[dict]`; `save_registry(rows, path)`; `upsert(path, row: dict)`; `set_maturity(path, id, level)`; CLI `python scripts/registry.py init` (reports/*.pdf에서 R01~R07 생성, maturity="-", title은 파일명에서 추출), `python scripts/registry.py list`.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_registry.py`:
```python
from scripts.registry import COLUMNS, load_registry, upsert, set_maturity, init_from_reports

def test_init_from_reports_maps_filenames(tmp_path):
    rep = tmp_path / "reports"; rep.mkdir()
    (rep / "01_[2023.04]_디지털전환_5G.pdf").write_bytes(b"%PDF")
    (rep / "예비06_[2019.08]_미래전략.pdf").write_bytes(b"%PDF")
    csv_path = tmp_path / "registry.csv"
    rows = init_from_reports(rep, csv_path)
    ids = {r["id"]: r for r in rows}
    assert ids["R01"]["published"] == "2023-04" and ids["R01"]["title"] == "디지털전환 5G"
    assert ids["R06"]["published"] == "2019-08" and ids["R06"]["maturity"] == "-"
    assert list(load_registry(csv_path)[0].keys()) == COLUMNS

def test_upsert_and_maturity(tmp_path):
    p = tmp_path / "r.csv"
    upsert(p, {"id": "R01", "title": "t", "published": "2023-04", "domain": "spectrum", "types": "F;M", "maturity": "-", "source_pdf": "x.pdf"})
    upsert(p, {"id": "R01", "title": "t2"})
    set_maturity(p, "R01", "L0")
    r = load_registry(p)[0]
    assert r["title"] == "t2" and r["maturity"] == "L0" and r["updated_at"]
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_registry.py -v` → ImportError

- [ ] **Step 3: 구현**

`scripts/registry.py`:
```python
"""보고서 레지스트리(registry.csv)."""
from __future__ import annotations
import argparse, csv, re, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "registry.csv"
COLUMNS = ["id", "title", "published", "domain", "types", "maturity", "updated_at", "source_pdf"]
FN = re.compile(r"^(?:예비)?(\d{2})_\[(\d{4})\.(\d{2})\]_(.+)\.pdf$")

def load_registry(path: Path = DEFAULT) -> list[dict]:
    if not Path(path).exists(): return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]

def save_registry(rows: list[dict], path: Path = DEFAULT) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS); w.writeheader()
        for r in rows: w.writerow({c: r.get(c, "") for c in COLUMNS})

def upsert(path: Path, row: dict) -> None:
    rows = load_registry(path); row = dict(row); row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, r in enumerate(rows):
        if r["id"] == row["id"]:
            rows[i] = {**r, **row}; break
    else:
        rows.append({c: row.get(c, "") for c in COLUMNS})
    save_registry(sorted(rows, key=lambda r: r["id"]), path)

def set_maturity(path: Path, rid: str, level: str) -> None:
    upsert(path, {"id": rid, "maturity": level})

def init_from_reports(reports_dir: Path, path: Path) -> list[dict]:
    for pdf in sorted(Path(reports_dir).glob("*.pdf")):
        m = FN.match(pdf.name)
        if not m: continue
        num, y, mo, title = m.groups()
        upsert(path, {"id": f"R{int(num):02d}", "title": title.replace("_", " "), "published": f"{y}-{mo}",
                      "domain": "", "types": "", "maturity": "-", "source_pdf": pdf.name})
    return load_registry(path)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init"); sub.add_parser("list")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        rows = init_from_reports(ROOT / "reports", DEFAULT); print(f"{len(rows)}건 등록")
    for r in load_registry(DEFAULT): print(f"{r['id']}  {r['maturity']:<4} {r['published']}  {r['title']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인 및 실제 초기화**

Run: `python -m pytest tests/test_registry.py -v` → 2 passed
Run: `python scripts/registry.py init` → `7건 등록` 후 R01~R07 목록 출력. `registry.csv`를 열어 제목·연월 확인.

- [ ] **Step 5: Commit**

```bash
git add scripts/registry.py tests/test_registry.py registry.csv && git commit -m "feat: 레지스트리 + 7편 초기 등록"
```

---

### Task 9: API 발급 가이드 검증본과 환경변수 동기화 테스트

**Files:**
- Modify: `docs/api_keys_guide.md`, `.env.example`
- Test: `tests/test_guide_sync.py`

**Interfaces:**
- Produces: 가이드 4절 변수 목록 == `catalog.py` 환경변수 ∪ `OPTIONAL_ENV`; `.env.example` == 가이드 4절 블록.

- [ ] **Step 1: 동기화 테스트**

`tests/test_guide_sync.py`:
```python
import re
from scripts.sources.catalog import CATALOG, OPTIONAL_ENV

def _vars_in(text):
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.M))

def test_guide_env_block_matches_catalog(ROOT):
    guide = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    block = guide.split("## 4.")[1].split("## 5.")[0]
    expected = {v for c in CATALOG for v in c["env_vars"]} | set(OPTIONAL_ENV)
    assert _vars_in(block) == expected

def test_env_example_matches_guide(ROOT):
    guide = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    block = guide.split("## 4.")[1].split("## 5.")[0]
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert _vars_in(example) == _vars_in(block)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_guide_sync.py -v`. 실패하면 가이드 4절 블록에 `ELSEVIER_INSTTOKEN`·`OPENALEX_MAILTO`·`CROSSREF_MAILTO`·`S2_API_KEY`가 있는지, 카탈로그와 이름이 같은지 맞춘다(가이드 초안에는 모두 있으므로 통과가 기대값. 실패 시 가이드가 아니라 카탈로그 오타를 먼저 의심).

- [ ] **Step 3: 포털별 검증** — 각 포털을 WebFetch로 열어 메뉴명·신청 절차·한도를 초안과 대조하고 다른 곳을 고친다. 확인 대상과 URL:

| 소스 | 확인 URL |
|---|---|
| 공공데이터포털 | https://www.data.go.kr/data/15085348/openapi.do (KCI 논문정보서비스) |
| KOSIS | https://kosis.kr/openapi/index/index.jsp |
| 법제처 | https://open.law.go.kr/LSO/openApi/guideList.do |
| NAVER | https://developers.naver.com/docs/serviceapi/search/news/news.md |
| 열린국회정보 | https://open.assembly.go.kr/portal/openapi/main.do |
| ECOS | https://ecos.bok.or.kr/api/ |
| 국회도서관 | https://www.nanet.go.kr/usermadang/etc/openApiView.do |
| ScienceON | https://scienceon.kisti.re.kr/apigateway/api/main/main.do |
| Semantic Scholar | https://www.semanticscholar.org/product/api |
| IEEE | https://developer.ieee.org/docs |

각 항목 끝에 `(확인 2026-09-xx)`를 붙이고 문서 상단 상태를 **초안 → 검증본**으로 바꾼다. 접근이 안 되는 포털은 "미확인" 표시를 남긴다.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_guide_sync.py -v` → 2 passed

- [ ] **Step 5: Commit**

```bash
git add docs/api_keys_guide.md .env.example tests/test_guide_sync.py && git commit -m "docs: API 발급 가이드 검증본·환경변수 동기화 테스트"
```

---

### Task 10: 실호출 스모크와 P0 마감

**Files:**
- Create: `docs/p0_smoke.md`

- [ ] **Step 1: 전체 테스트**

Run: `python -m pytest -v` → 전부 통과(예상 22개 내외)

- [ ] **Step 2: doctor 실호출**

Run: `python scripts/evidence.py doctor`
Expected: openalex·crossref·semantic_scholar·arxiv 행이 `연결 OK`. 키 없는 소스는 `키 없음`, 키를 넣은 소스는 `키 있음, 커넥터는 P4에서 구현`. 실패한 T0 소스가 있으면 `--no-cache`로 재시도 후 네트워크 문제인지 코드 문제인지 구분해 기록.

- [ ] **Step 3: papers 실호출 2건**

```bash
python scripts/evidence.py papers --q "5G spectrum auction welfare Korea" --since 2022-01-01 --limit 10
python scripts/evidence.py papers --q "OTT 규제 국내 온라인 동영상 시장" --since 2023-06-01 --limit 10
```
Expected: `kb/evidence/`에 JSONL 2개, 소스별 건수 표. 이어서 `python scripts/validate.py kb/evidence/<파일> --schema evidence_record` → `검증 통과`.

- [ ] **Step 4: 결과 기록**

`docs/p0_smoke.md`에 실행 일시, doctor 표, 두 질의의 소스별 건수와 대표 결과 3건(제목·날짜·등급·URL)을 붙여 넣는다. 키 값은 절대 기록하지 않는다.

- [ ] **Step 5: Commit**

```bash
git add docs/p0_smoke.md && git commit -m "docs: P0 스모크 결과"
```

---

## Self-Review

**Spec coverage (P0 범위):** 5절 근거 소스 계층 → Task 1~5(T0 4종·doctor·캐시·키 없는 소스 자동 비활성); 카탈로그에 T1~T3 26종 선언 → Task 2; `.env.example`·가이드 → Task 0·9; 6절 kb·도메인 6종·sources.md → Task 7; 8절 골격(CLAUDE.md, settings.json, templates/schemas 8종, registry) → Task 0·6·8; 11절 P0 완료 기준 "doctor T0 정상" → Task 10. T1/T3 커넥터·intake·스킬·에이전트·UI는 P1~P5 계획에서 다룬다(스펙 11절대로).

**Placeholder scan:** 모든 코드 스텝에 실제 코드가 있다. Task 9 Step 3은 문서 검증 절차이며 대상 URL을 명시했다.

**Type consistency:** `EvidenceRecord` 필드명은 스키마 `evidence_record.schema.json`과 일치. `load_sources(env, http, kind, only)` 시그니처는 Task 2 정의와 Task 5 사용이 같다. `SourceStatus` 필드(`name, tier, kind, env_vars, configured, implemented, ok, detail`)는 Task 1 정의·Task 2 생성·Task 5 출력이 같다. `validate_obj/validate_file` 이름은 Task 6 정의·Task 10 사용이 같다. 레지스트리 `COLUMNS`는 Task 8 내부에서만 쓰인다.
