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
