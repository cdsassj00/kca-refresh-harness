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
