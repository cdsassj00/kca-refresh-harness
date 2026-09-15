"""arXiv Atom API. 키 불필요. 날짜 필터는 클라이언트에서. XML은 defusedxml로 파싱(XXE 방지)."""
from __future__ import annotations
import defusedxml.ElementTree as ET
from .base import BaseSource
API = "https://export.arxiv.org/api/query"  # http는 301로 우회되어 한도 계산에 불리
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
