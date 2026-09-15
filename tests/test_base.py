import json, time
from unittest.mock import patch, MagicMock
from scripts.sources.base import EvidenceRecord, HttpClient, BaseSource

def test_evidence_record_to_json_has_required_fields():
    r = EvidenceRecord(source="openalex", id="W1", url="https://x", title="t",
                       date="2024-01-01", snippet="s", grade="A",
                       retrieved_at="2026-09-15T00:00:00", query="q")
    j = r.to_json()
    assert set(["source","id","url","title","date","snippet","grade","retrieved_at","query","extra"]) <= set(j)
    assert j["grade"] == "A"

def test_evidence_record_rejects_bad_grade():
    import pytest
    with pytest.raises(ValueError):
        EvidenceRecord(source="s", id="1", url="u", title="t", date=None, snippet="",
                       grade="D", retrieved_at="x", query="q")

def test_http_get_json_uses_cache(tmp_cache):
    http = HttpClient(cache_dir=tmp_cache)
    fake = MagicMock(); fake.status_code = 200; fake.json.return_value = {"a": 1}; fake.text = '{"a": 1}'
    with patch("scripts.sources.base.requests.get", return_value=fake) as g:
        assert http.get_json("https://api.test/x", params={"q": "1"}) == {"a": 1}
        assert http.get_json("https://api.test/x", params={"q": "1"}) == {"a": 1}
        assert g.call_count == 1
    assert len(list(tmp_cache.glob("*.json"))) == 1

def test_http_no_cache_bypasses(tmp_cache):
    http = HttpClient(cache_dir=tmp_cache, no_cache=True)
    fake = MagicMock(); fake.status_code = 200; fake.json.return_value = {"a": 1}; fake.text = "{}"
    with patch("scripts.sources.base.requests.get", return_value=fake) as g:
        http.get_json("https://api.test/y"); http.get_json("https://api.test/y")
        assert g.call_count == 2

def test_base_source_is_configured_checks_env():
    class S(BaseSource):
        name="s"; tier="T1"; kind="papers"; env_vars=["K1"]; default_grade="B"
        def search(self, query, since=None, until=None, limit=20): return []
        def ping(self): return True, "ok"
    assert S({"K1": "v"}, http=None).is_configured() is True
    assert S({}, http=None).is_configured() is False
