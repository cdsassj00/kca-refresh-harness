"""Semantic Scholar Graph API. 키 선택(x-api-key).

속도 제한: 발급받는 키의 조건이 **모든 엔드포인트 합쳐 초당 1회**다(2026-09 기준 안내문).
넘기면 요청이 거부되므로 호출 사이 간격을 코드로 지킨다. 키가 없을 때는 공용 한도가
더 낮으므로 간격을 더 벌린다.
"""
from __future__ import annotations
import threading
import time
from .base import BaseSource

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,publicationDate,url,externalIds,tldr,venue,citationCount"

MIN_INTERVAL_WITH_KEY = 1.1     # 초당 1회 조건에 여유를 둔다
MIN_INTERVAL_NO_KEY = 3.0       # 키 없는 공용 한도는 더 낮다

_lock = threading.Lock()
_last_call = 0.0


def _throttle(has_key: bool) -> None:
    """직전 호출로부터 최소 간격이 지나도록 기다린다(프로세스 안에서 공유)."""
    global _last_call
    gap = MIN_INTERVAL_WITH_KEY if has_key else MIN_INTERVAL_NO_KEY
    with _lock:
        wait = gap - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


class SemanticScholarSource(BaseSource):
    name = "semantic_scholar"; tier = "T0"; kind = "papers"; env_vars = []; default_grade = "B"
    def _headers(self):
        return {"x-api-key": self.env["S2_API_KEY"]} if self.env.get("S2_API_KEY") else {}
    def search(self, query, since=None, until=None, limit=20):
        p = {"query": query, "limit": min(limit, 100), "fields": FIELDS}
        if since or until:
            p["year"] = f"{(since or '1900')[:4]}-{(until or '2100')[:4]}"
        _throttle(bool(self.env.get("S2_API_KEY")))
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
        has_key = bool(self.env.get("S2_API_KEY"))
        _throttle(has_key)
        d = self.http.get_json(API, params={"query": "spectrum", "limit": 1, "fields": "title"}, headers=self._headers())
        gap = MIN_INTERVAL_WITH_KEY if has_key else MIN_INTERVAL_NO_KEY
        return ("data" in d), f"OK ({'키 사용' if has_key else '키 없음, 낮은 쿼터'}, 호출 간격 {gap}초)"
