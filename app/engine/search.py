"""웹 검색 공급자 통합. DESIGN.md 3절 web_search.

provider="auto" 는 tavily → exa → naver(뉴스+웹문서) → openrouter_online 순으로 키가 있는 첫 공급자를 쓴다.
모든 공급자의 결과를 [{title, url, snippet, date, source}] 로 정규화한다.
"""
from __future__ import annotations
import html as _html
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

PROVIDER_ORDER = ["tavily", "exa", "naver", "openrouter_online"]
TIMEOUT = 20
UA = "kca-refresh-app/0.1"

# 네이버 검색은 2026년부터 NAVER API HUB(네이버 클라우드 플랫폼 중개)로 넘어갔다.
# 주소에 `.json` 확장자가 없고, 헤더 이름이 NCP API Gateway 규칙을 따른다.
NAVER_HUB_BASE = "https://naverapihub.apigw.ntruss.com/search/v1"
NAVER_LEGACY_BASE = "https://openapi.naver.com/v1/search"
# 신청하지 않은 API를 부르면 HTTP 401 과 함께 이 문구가 온다. 오류가 아니라 "그 API는 안 쓴다"는 뜻이다.
NAVER_NOT_ENABLED = "활성화되어 있지 않습니다"


class SearchError(Exception):
    """검색 공급자 오류. 메시지에 키 값은 넣지 않는다."""


# ---------- 공통 ----------
_TAG_RE = re.compile(r"<[^>]+>")
# 엔티티(&lt;b&gt;)가 풀려 다시 태그가 된 경우만 한 번 더 걷어낸다. 부등호가 섞인 문장은 건드리지 않게 좁게 잡는다.
_ENTITY_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")


def _clean(text: Optional[str]) -> str:
    """검색 결과의 `<b>` 강조 태그를 지우고 HTML 엔티티(&quot; 등)를 풀어 준다."""
    if not text:
        return ""
    text = _TAG_RE.sub("", str(text))
    text = _html.unescape(text)
    return _ENTITY_TAG_RE.sub("", text).strip()


def _norm(title, url, snippet, date, source) -> dict:
    return {"title": _clean(title)[:300], "url": (url or "").strip(), "snippet": _clean(snippet)[:600],
            "date": (date or "")[:10] if isinstance(date, str) else "", "source": source}


def _has_tavily(env: dict) -> bool:
    return bool(env.get("TAVILY_API_KEY"))


def _has_exa(env: dict) -> bool:
    return bool(env.get("EXA_API_KEY"))


def _has_naver(env: dict) -> bool:
    return bool(env.get("NAVER_CLIENT_ID") and env.get("NAVER_CLIENT_SECRET"))


def _has_openrouter_online(env: dict) -> bool:
    return bool(env.get("OPENROUTER_API_KEY"))


# ---------- 공급자 ----------
def _search_tavily(query: str, since: Optional[str], max_results: int, lang: str, env: dict, llm=None) -> list:
    key = env["TAVILY_API_KEY"]
    body = {"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": False}
    if since:
        body["start_date"] = since
    resp = requests.post("https://api.tavily.com/search", json={**body, "api_key": key},
                         headers={"Authorization": f"Bearer {key}", "User-Agent": UA}, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise SearchError(f"tavily HTTP {resp.status_code}")
    data = resp.json()
    return [_norm(r.get("title"), r.get("url"), r.get("content"), r.get("published_date"), "tavily")
            for r in data.get("results", [])][:max_results]


def _search_exa(query: str, since: Optional[str], max_results: int, lang: str, env: dict, llm=None) -> list:
    body = {"query": query, "numResults": max_results, "type": "auto",
            "contents": {"text": {"maxCharacters": 600}}}
    if since:
        body["startPublishedDate"] = f"{since}T00:00:00.000Z"
    resp = requests.post("https://api.exa.ai/search", json=body,
                         headers={"x-api-key": env["EXA_API_KEY"], "Content-Type": "application/json",
                                  "User-Agent": UA}, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise SearchError(f"exa HTTP {resp.status_code}")
    data = resp.json()
    return [_norm(r.get("title"), r.get("url"), r.get("text") or r.get("highlights"), r.get("publishedDate"), "exa")
            for r in data.get("results", [])][:max_results]


def naver_api_style(env: dict) -> str:
    """`hub`(기본, NAVER API HUB) 또는 `legacy`(옛 개발자센터 openapi.naver.com)."""
    style = str((env or {}).get("NAVER_API_STYLE") or "hub").strip().lower()
    return "legacy" if style == "legacy" else "hub"


def _naver_url(kind: str, style: str) -> str:
    """kind 는 `news`(뉴스) 또는 `webkr`(웹문서)."""
    if style == "legacy":
        return f"{NAVER_LEGACY_BASE}/{kind}.json"
    return f"{NAVER_HUB_BASE}/{kind}"


def _naver_headers(env: dict, style: str) -> dict:
    if style == "legacy":
        return {"X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
                "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"], "User-Agent": UA}
    return {"X-NCP-APIGW-API-KEY-ID": env["NAVER_CLIENT_ID"],
            "X-NCP-APIGW-API-KEY": env["NAVER_CLIENT_SECRET"], "User-Agent": UA}


def _naver_body_text(resp) -> str:
    try:
        return resp.text or ""
    except (AttributeError, ValueError):
        return ""


def _naver_fetch(kind: str, query: str, display: int, env: dict, style: str) -> Optional[list]:
    """네이버 검색 한 종류를 부른다. 신청하지 않은 API(401 + 활성화 문구)면 None 을 돌려 건너뛰게 한다."""
    params = {"query": query, "display": display}
    if kind == "news":
        params["sort"] = "date"          # 웹문서(webkr)는 sort 를 받지 않는다
    resp = requests.get(_naver_url(kind, style), params=params,
                        headers=_naver_headers(env, style), timeout=TIMEOUT)
    if resp.status_code == 401 and NAVER_NOT_ENABLED in _naver_body_text(resp):
        return None                      # 이 API는 신청하지 않았다 → 조용히 건너뛴다
    if resp.status_code != 200:
        raise SearchError(f"naver {kind} HTTP {resp.status_code}")
    data = resp.json()
    items = data.get("items") if isinstance(data, dict) else None
    return list(items or [])


def _naver_date(value) -> str:
    """뉴스의 pubDate(RFC 2822)를 YYYY-MM-DD 로. 없거나 못 읽으면 빈 문자열."""
    if not value:
        return ""
    try:
        return parsedate_to_datetime(str(value)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _search_naver(query: str, since: Optional[str], max_results: int, lang: str, env: dict, llm=None) -> list:
    """네이버 뉴스 + 웹문서. 뉴스를 먼저 채우고 모자라면 웹문서로 보충한다.

    웹문서(webkr)는 날짜가 없으므로 date 를 빈 문자열로 두고 since 필터에서 버리지 않는다.
    """
    style = naver_api_style(env)
    limit = min(max(int(max_results or 8), 1), 100)
    out, seen = [], set()
    for kind, source in (("news", "naver_news"), ("webkr", "naver_webkr")):
        if len(out) >= limit:
            break
        items = _naver_fetch(kind, query, limit, env, style)
        if items is None:                # 신청하지 않은 API → 남은 결과로 진행
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            date = _naver_date(it.get("pubDate")) if kind == "news" else ""
            if since and date and date < since:
                continue                 # 날짜가 있는 뉴스만 거른다. 날짜 없는 웹문서는 통과
            url = (it.get("originallink") or it.get("link") or "").strip()
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            out.append(_norm(it.get("title"), url, it.get("description"), date, source))
            if len(out) >= limit:
                break
    return out[:limit]


def _search_openrouter_online(query: str, since: Optional[str], max_results: int, lang: str, env: dict, llm=None) -> list:
    """LLM의 web 플러그인으로 검색. 결과를 JSON 배열로만 답하게 하고, 파싱에 실패하면 빈 배열."""
    if llm is None:
        raise SearchError("openrouter_online 검색에는 LLM 클라이언트가 필요합니다")
    period = f" {since} 이후 자료만." if since else ""
    prompt = (f"다음 주제를 웹에서 검색해 결과를 JSON 배열로만 답하라. 설명 문장·코드펜스 금지.{period}\n"
              f"각 원소: {{\"title\": \"...\", \"url\": \"https://...\", \"snippet\": \"핵심 두 문장\", \"date\": \"YYYY-MM-DD 또는 빈 문자열\"}}\n"
              f"최대 {max_results}개. 언어 우선순위: {lang}.\n검색어: {query}")
    r = llm.chat([{"role": "user", "content": prompt}], extra={"plugins": [{"id": "web"}]})
    arr = parse_json_array(r.content)
    out = []
    for it in arr:
        if isinstance(it, dict) and it.get("url"):
            out.append(_norm(it.get("title"), it.get("url"), it.get("snippet"), it.get("date"), "openrouter_online"))
    return out[:max_results]


def parse_json_array(text: str) -> list:
    """코드펜스·앞뒤 설명을 걷어내고 첫 JSON 배열을 파싱한다. 실패하면 []."""
    if not text:
        return []
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else []
    except ValueError:
        pass
    m = re.search(r"\[.*\]", t, re.S)
    if not m:
        return []
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, list) else []
    except ValueError:
        return []


PROVIDERS = {
    "tavily": (_has_tavily, _search_tavily),
    "exa": (_has_exa, _search_exa),
    "naver": (_has_naver, _search_naver),
    "openrouter_online": (_has_openrouter_online, _search_openrouter_online),
}


def available_providers(env: dict, llm=None) -> list:
    out = []
    for name in PROVIDER_ORDER:
        has, _ = PROVIDERS[name]
        if name == "openrouter_online" and llm is None:
            continue
        if has(env or {}):
            out.append(name)
    return out


def pick_provider(provider: str, env: dict, llm=None) -> Optional[str]:
    """설정된 공급자 이름을 확정한다. auto 는 키가 있는 첫 공급자. 없으면 None."""
    provider = (provider or "auto").strip()
    if provider != "auto":
        if provider not in PROVIDERS:
            raise SearchError(f"알 수 없는 검색 공급자: {provider}")
        return provider
    avail = available_providers(env, llm)
    return avail[0] if avail else None


def _default_llm(env: dict):
    """openrouter_online 폴백용 기본 LLM 클라이언트(키가 있을 때만)."""
    if not env.get("OPENROUTER_API_KEY"):
        return None
    import config
    from engine.llm import LLMClient
    s = config.load_settings()
    return LLMClient(base_url=env.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
                     api_key=env["OPENROUTER_API_KEY"], model=s.get("model") or "openrouter/auto",
                     temperature=float(s.get("temperature", 0.2)))


def search(query: str, since: Optional[str] = None, max_results: int = 8, lang: str = "ko",
           provider: Optional[str] = None, env: Optional[dict] = None, llm=None) -> list:
    """웹 검색. 반환 [{title,url,snippet,date,source}].

    env 가 None 이면 config.load_env(), provider 가 None 이면 settings.search_provider 를 쓴다.
    """
    if env is None:
        import config
        env = config.load_env()
    if provider is None:
        import config
        provider = config.load_settings().get("search_provider") or "auto"
    if llm is None:
        llm = _default_llm(env)
    name = pick_provider(provider, env, llm)
    if not name:
        raise SearchError("검색 공급자 키가 없습니다 (TAVILY_API_KEY / EXA_API_KEY / NAVER_CLIENT_ID+SECRET / OPENROUTER_API_KEY)")
    has, fn = PROVIDERS[name]
    if not has(env):
        raise SearchError(f"검색 공급자 '{name}'의 키가 없습니다")
    try:
        return fn(query, since, int(max_results or 8), lang or "ko", env, llm)
    except SearchError:
        raise
    except requests.RequestException as e:
        raise SearchError(f"{name} 네트워크 오류: {type(e).__name__}") from None
    except (ValueError, KeyError, TypeError) as e:
        raise SearchError(f"{name} 응답 해석 실패: {type(e).__name__}") from None


def now_date() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
