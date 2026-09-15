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
