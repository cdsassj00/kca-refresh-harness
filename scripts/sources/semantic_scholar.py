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
