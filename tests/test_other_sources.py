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
