"""단계별 도구 레지스트리. DESIGN.md 3절.

도구 5종: web_search, fetch_page, evidence_search, read_report_file, read_core_file.
`ToolRegistry.for_stage(stage, report_id) -> (tool_defs, executor)`; executor(name, args) -> JSON 문자열.
- read_report_file 은 reports/<id>/ 안으로만(config.safe_join). 블라인드 단계에는 등록하지 않는다.
- read_core_file 은 kb/·templates/ 아래만.
- 결과 문자열은 도구별 상한(일반 12,000자, 파일 읽기 60,000자)을 넘으면 잘라내고 truncated:true 를 붙인다.
"""
from __future__ import annotations
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

import config
from engine import search as search_mod
from engine.stages import StageSpec, get_stage

RESULT_LIMIT = 12000
FILE_LIMIT = 60000
FETCH_TEXT_LIMIT = 12000
FETCH_TIMEOUT = 20
UA = "Mozilla/5.0 (compatible; kca-refresh-app/0.1; +http://localhost:8765)"

TOOL_DEFS = {
    "web_search": {"type": "function", "function": {
        "name": "web_search",
        "description": "웹 검색. 정책·통계·언론 자료를 찾을 때 쓴다. 결과는 [{title,url,snippet,date,source}] 배열.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "검색어"},
            "since": {"type": "string", "description": "YYYY-MM-DD, 이 날짜 이후 자료만(선택)"},
            "max_results": {"type": "integer", "description": "최대 결과 수(기본 8)"},
            "lang": {"type": "string", "enum": ["ko", "en"], "description": "언어(기본 ko)"}},
            "required": ["query"]}}},
    "fetch_page": {"type": "function", "function": {
        "name": "fetch_page",
        "description": "URL의 본문 텍스트를 가져온다(HTML 본문 추출, PDF는 앞 20쪽). 반환 {url,title,text,fetched_at,status}.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    "evidence_search": {"type": "function", "function": {
        "name": "evidence_search",
        "description": "학술 논문·연구보고서 검색(OpenAlex·Crossref·Semantic Scholar·arXiv). 결과는 kb/evidence/ 에도 저장된다.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "since": {"type": "string", "description": "YYYY-MM-DD(선택)"},
            "kind": {"type": "string", "enum": ["papers"], "description": "소스 종류(기본 papers)"},
            "limit": {"type": "integer", "description": "최대 건수(기본 10)"}},
            "required": ["query"]}}},
    "read_report_file": {"type": "function", "function": {
        "name": "read_report_file",
        "description": "이 보고서 서랍(reports/<id>/) 안의 파일을 읽는다. 예: 00_source/R01.md, 03_argument_chains.json, L0/events.json",
        "parameters": {"type": "object", "properties": {
            "relpath": {"type": "string", "description": "reports/<id>/ 기준 상대경로"},
            "offset": {"type": "integer", "description": "시작 글자 위치(선택, 긴 파일을 나눠 읽을 때)"}},
            "required": ["relpath"]}}},
    "read_core_file": {"type": "function", "function": {
        "name": "read_core_file",
        "description": "공통 지식베이스·양식 파일을 읽는다. kb/ 와 templates/ 아래만 허용. 예: kb/domains/spectrum.yaml, templates/verdict_rules.yaml",
        "parameters": {"type": "object", "properties": {
            "relpath": {"type": "string", "description": "프로젝트 루트 기준 상대경로(kb/... 또는 templates/...)"}},
            "required": ["relpath"]}}},
}
READ_TOOLS = {"read_report_file", "read_core_file"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def cap_json(obj, limit: int) -> str:
    """JSON 문자열이 limit 을 넘으면 내용을 줄이고 truncated:true 를 붙인다. 항상 유효한 JSON 을 돌려준다."""
    s = json.dumps(obj, ensure_ascii=False)
    if len(s) <= limit:
        return s
    if isinstance(obj, list):
        items = list(obj)
        while items and len(json.dumps(items, ensure_ascii=False)) > limit - 40:
            items.pop()
        return json.dumps({"results": items, "truncated": True, "dropped": len(obj) - len(items)}, ensure_ascii=False)
    if isinstance(obj, dict):
        d = dict(obj)
        for k in ("content", "text", "snippet", "summary"):
            if isinstance(d.get(k), str):
                over = len(s) - limit + 80
                d[k] = d[k][:max(0, len(d[k]) - over)] + "…"
                d["truncated"] = True
                return json.dumps(d, ensure_ascii=False)
    return json.dumps({"truncated": True, "text": s[:limit - 40]}, ensure_ascii=False)


# ---------- 개별 도구 구현 ----------
MAX_REDIRECTS = 5


def host_blocked(url: str) -> Optional[str]:
    """공개 인터넷 호스트가 아니면 차단 사유를 돌려준다(None 이면 허용).
    모델이 고른 URL 을 그대로 여는 도구이므로, 사설망·루프백·링크로컬(클라우드 메타데이터 169.254.169.254)·예약 대역과
    사용자 정보가 들어간 URL 은 열지 않는다(SSRF 방지)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except ValueError:
        return "URL 형식 오류"
    if p.scheme not in ("http", "https"):
        return "http(s) URL 만 허용"
    if p.username or p.password:
        return "URL 에 사용자 정보(아이디·비밀번호) 포함 불가"
    host = (p.hostname or "").lower()
    if not host:
        return "호스트 없음"
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        return "내부 호스트 차단"
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "호스트 이름을 풀 수 없음"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified):
            return f"내부·예약 주소 차단({ip})"
    return None


def fetch_page(url: str) -> dict:
    """requests(UA, 20s) → trafilatura.extract → 실패 시 BeautifulSoup get_text. PDF 면 pypdf 앞 20쪽.
    리다이렉트는 직접 따라가며 매 홉마다 호스트를 다시 검사한다."""
    from urllib.parse import urljoin
    if not url or not re.match(r"^https?://", url):
        return {"url": url, "title": "", "text": "", "fetched_at": _now(), "status": 0, "error": "http(s) URL 만 허용"}
    current = url
    resp = None
    for _ in range(MAX_REDIRECTS + 1):
        reason = host_blocked(current)
        if reason:
            return {"url": current, "title": "", "text": "", "fetched_at": _now(), "status": 0, "error": f"차단: {reason}"}
        try:
            resp = requests.get(current, headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"},
                                timeout=FETCH_TIMEOUT, allow_redirects=False)
        except requests.RequestException as e:
            return {"url": current, "title": "", "text": "", "fetched_at": _now(), "status": 0,
                    "error": f"요청 실패: {type(e).__name__}"}
        if getattr(resp, "status_code", 0) in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if not loc:
                break
            current = urljoin(current, loc)
            continue
        break
    else:
        return {"url": current, "title": "", "text": "", "fetched_at": _now(), "status": 0, "error": "리다이렉트 횟수 초과"}
    url = current
    ctype = (resp.headers.get("Content-Type") or "").lower()
    is_pdf = "application/pdf" in ctype or url.lower().split("?")[0].endswith(".pdf") or resp.content[:5] == b"%PDF-"
    title, text = "", ""
    if is_pdf:
        title, text = _pdf_text(resp.content)
    else:
        html_text = resp.text
        title, text = _html_text(html_text, url)
    return {"url": resp.url or url, "title": title[:300], "text": text[:FETCH_TEXT_LIMIT], "fetched_at": _now(),
            "status": resp.status_code, "truncated": len(text) > FETCH_TEXT_LIMIT}


def _pdf_text(data: bytes, max_pages: int = 20) -> tuple:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "(pypdf 미설치: PDF 본문을 읽을 수 없음)"
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for i, page in enumerate(reader.pages[:max_pages], 1):
            try:
                parts.append(f"<!-- page {i} -->\n" + (page.extract_text() or ""))
            except Exception:  # 개별 쪽 실패는 건너뜀
                parts.append(f"<!-- page {i} -->\n")
        title = ""
        try:
            title = (reader.metadata or {}).get("/Title") or ""
        except Exception:
            pass
        return str(title), "\n".join(parts)
    except Exception as e:
        return "", f"(PDF 해석 실패: {type(e).__name__})"


def _html_text(html_text: str, url: str) -> tuple:
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    text = ""
    try:
        import trafilatura
        text = trafilatura.extract(html_text, url=url, include_comments=False, include_tables=True,
                                   favor_recall=True) or ""
    except Exception:
        text = ""
    if not text.strip():
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_text, "html.parser")
            for t in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                t.decompose()
            text = soup.get_text("\n")
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = "\n".join(line.strip() for line in text.splitlines())
        except Exception:
            text = re.sub(r"<[^>]+>", " ", html_text)
    return title, text.strip()


def evidence_search(query: str, since: Optional[str] = None, kind: str = "papers", limit: int = 10,
                    env: Optional[dict] = None) -> list:
    """scripts.sources.load_sources 로 T0 커넥터 실행, 결과를 kb/evidence/ 에 저장."""
    from scripts.sources import load_sources
    from scripts.sources.base import HttpClient
    env = env if env is not None else config.load_env()
    http = HttpClient(config.KB_DIR / "cache")
    rows, errors = [], []
    for src in load_sources(env, http, kind=kind or "papers"):
        try:
            recs = src.search(query, since=since, limit=limit)
        except Exception as e:  # 개별 소스 실패는 기록만
            errors.append(f"{src.name}: {type(e).__name__}")
            continue
        rows += [r.to_json() for r in recs]
    out_dir = config.KB_DIR / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "_", query).strip("_")[:40] or "q"
    out = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{kind}_{slug}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    result = rows[: int(limit or 10)]
    if errors:
        result.append({"note": "일부 소스 실패", "errors": errors})
    return result


def read_report_file(report_id: str, relpath: str, offset: int = 0) -> dict:
    base = config.report_dir(report_id)
    p = config.safe_join(base, relpath)
    if not p.exists() or not p.is_file():
        return {"relpath": relpath, "error": "파일이 없습니다"}
    text = p.read_text(encoding="utf-8", errors="replace")
    offset = max(0, int(offset or 0))
    chunk = text[offset: offset + FILE_LIMIT]
    return {"relpath": relpath, "chars": len(text), "offset": offset, "truncated": offset + len(chunk) < len(text),
            "content": chunk}


def read_core_file(relpath: str) -> dict:
    p = config.safe_join(config.CORE_DIR, relpath)
    allowed = [config.KB_DIR.resolve(), config.TEMPLATES_DIR.resolve()]
    if not any(a == p or a in p.parents for a in allowed):
        raise PermissionError(f"kb/ 또는 templates/ 아래만 읽을 수 있습니다: {relpath}")
    if not p.exists() or not p.is_file():
        return {"relpath": relpath, "error": "파일이 없습니다"}
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"relpath": relpath, "chars": len(text), "truncated": len(text) > FILE_LIMIT, "content": text[:FILE_LIMIT]}


# ---------- 레지스트리 ----------
class ToolRegistry:
    def __init__(self, env: Optional[dict] = None, llm=None, settings: Optional[dict] = None):
        self.env = env if env is not None else config.load_env()
        self.llm = llm
        self.settings = settings or config.load_settings()

    def defs_for(self, names: list) -> list:
        return [TOOL_DEFS[n] for n in names if n in TOOL_DEFS]

    def for_stage(self, stage, report_id: str) -> tuple:
        """(tool_defs, executor). stage 는 StageSpec 또는 단계 이름."""
        spec: StageSpec = stage if isinstance(stage, StageSpec) else get_stage(stage)
        names = list(spec.tools)
        if spec.isolated:
            names = [n for n in names if n not in READ_TOOLS]  # 격리 단계에는 파일 읽기 도구를 절대 주지 않는다
        defs = self.defs_for(names)
        allowed = {n for n in names}

        def executor(name: str, args: Optional[dict]) -> str:
            args = args or {}
            if name not in allowed:
                return json.dumps({"error": f"이 단계에서 허용되지 않은 도구: {name}"}, ensure_ascii=False)
            try:
                result = self._call(name, args, report_id)
            except PermissionError as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)
            except search_mod.SearchError as e:
                return json.dumps({"error": f"검색 실패: {e}"}, ensure_ascii=False)
            except Exception as e:  # 도구 오류는 모델에게 알리고 계속 진행
                return json.dumps({"error": f"도구 오류 {type(e).__name__}: {str(e)[:200]}"}, ensure_ascii=False)
            limit = FILE_LIMIT + 400 if name in READ_TOOLS else RESULT_LIMIT
            return cap_json(result, limit)

        return defs, executor

    def _call(self, name: str, args: dict, report_id: str):
        if name == "web_search":
            return search_mod.search(query=str(args.get("query", "")), since=args.get("since") or None,
                                     max_results=int(args.get("max_results") or 8), lang=args.get("lang") or "ko",
                                     provider=self.settings.get("search_provider") or "auto", env=self.env, llm=self.llm)
        if name == "fetch_page":
            return fetch_page(str(args.get("url", "")))
        if name == "evidence_search":
            return evidence_search(str(args.get("query", "")), since=args.get("since") or None,
                                   kind=args.get("kind") or "papers", limit=int(args.get("limit") or 10), env=self.env)
        if name == "read_report_file":
            return read_report_file(report_id, str(args.get("relpath", "")), int(args.get("offset") or 0))
        if name == "read_core_file":
            return read_core_file(str(args.get("relpath", "")))
        raise KeyError(name)
