import json
from unittest.mock import patch
from scripts import evidence
from scripts.sources.base import EvidenceRecord

def _rec(src):
    return EvidenceRecord(source=src, id="1", url="u", title="t", date="2024-01-01", snippet="s",
                          grade="B", retrieved_at="x", query="q")

def test_papers_writes_jsonl(tmp_path, tmp_cache, monkeypatch):
    out = tmp_path / "o.jsonl"
    class Fake:
        name = "openalex"
        def search(self, *a, **k): return [_rec("openalex"), _rec("openalex")]
    with patch.object(evidence, "load_sources", return_value=[Fake()]):
        rc = evidence.main(["papers", "--q", "5G", "--out", str(out), "--cache-dir", str(tmp_cache)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["source"] == "openalex"

def test_doctor_table_lists_all_and_hides_key_values(capsys, tmp_cache):
    env = {"KOSIS_API_KEY": "SECRET123"}
    with patch.object(evidence, "load_env", return_value=env):
        rc = evidence.main(["doctor", "--no-ping", "--cache-dir", str(tmp_cache)])
    out = capsys.readouterr().out
    assert rc == 0 and "kosis" in out and "scopus" in out and "SECRET123" not in out

def test_doctor_json(capsys, tmp_cache):
    with patch.object(evidence, "load_env", return_value={}):
        evidence.main(["doctor", "--no-ping", "--json", "--cache-dir", str(tmp_cache)])
    data = json.loads(capsys.readouterr().out)
    assert any(d["name"] == "openalex" and d["configured"] for d in data)
