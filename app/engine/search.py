"""웹 검색 공급자 통합. DESIGN.md 3절 web_search.

provider="auto" 는 tavily → exa → naver(뉴스) → openrouter_online 순으로 키가 있는 첫 공급자를 쓴다.
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


class SearchError(Exception):
    """검색 공급자 오류. 메시지에 키 값은 넣지 않는다."""


# ---------- 공통 ----------
def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    return _html.unescape(text).strip()


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


def _search_naver(query: str, since: Optional[str], max_results: int, lang: str, env: dict, llm=None) -> list:
    resp = requests.get("https://openapi.naver.com/v1/search/news.json",
                        params={"query": query, "display": min(max(max_results, 1), 100), "sort": "date"},
                        headers={"X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
                                 "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"], "User-Agent": UA},
                        timeout=TIMEOUT)
    if resp.status_code != 200:
        raise SearchError(f"naver HTTP {resp.status_code}")
    out = []
    for it in resp.json().get("items", []):
        date = ""
        try:
            date = parsedate_to_datetime(it.get("pubDate", "")).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
        if since and date and date < since:
            continue
        out.append(_norm(it.get("title"), it.get("originallink") or it.get("link"), it.get("description"), date, "naver"))
    return out[:max_results]


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
