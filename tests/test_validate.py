import json
from scripts.validate import validate_obj, validate_file

def test_claim_schema_requires_fields():
    errs = validate_obj({"claim_id": "R01-F-001"}, "claim")
    assert errs and any("type" in e or "statement" in e for e in errs)

def test_valid_claim_and_verdict():
    claim = {"claim_id": "R01-F-001", "conclusion_id": "R01-K-Fc-01", "type": "F", "page": 57,
             "statement": "2025년 5G 가입자 4,120만 명", "original_value": {"metric": "5G 가입자", "year": 2025, "value": 41200000, "unit": "명"},
             "assumptions": ["연 12% 순증"], "verify_method": "backtest", "data_sources_hint": ["kosis"]}
    assert validate_obj(claim, "claim") == []
    verdict = {"claim_id": "R01-F-001", "verdict": "과대", "current_value": {"value": 36000000, "unit": "명", "asof": "2025-12"},
               "reason": "실적 대비 +14%", "evidence": [{"url": "https://kosis.kr/x", "grade": "A", "retrieved_at": "2026-09-15"}]}
    assert validate_obj(verdict, "verdict") == []

def test_conclusion_and_comparison_row_and_run_config():
    k = {"conclusion_id": "R01-K-Fc-01", "kind": "Fc", "statement": "…", "page": 57, "method": "시계열 추정",
         "premises": ["P-01"], "evidence_refs": ["R01-F-001"], "types": ["F"]}
    assert validate_obj(k, "conclusion") == []
    row = {"row_id": "K-Fc-01", "level": "conclusion", "location": "4장 2절 p.57", "old": "…", "new": "…",
           "change_type": "수치갱신", "verdict": "부분수정", "reason_locus": ["E"], "evidence_ids": ["ev1"],
           "grade": "A", "status": "L2 최종", "linked_conclusions": ["R01-K-Fc-01"]}
    assert validate_obj(row, "comparison_row") == []
    rc = {"report_id": "R01", "layers": ["L0"], "options": {"blind_rerun": {"enabled": True, "repeats": 1},
          "survey_redesign": True, "experiment_plan": True, "synthetic_sim": {"enabled": False, "panel_size": 200},
          "l0_rewrite_scope": "env_and_desk_updatable"}, "sources": ["openalex"], "output": ["hwpx", "html"],
          "period": {"since": "2023-04-20", "until": "today"}}
    assert validate_obj(rc, "run_config") == []

def test_comparison_row_optional_next_action_and_evidence():
    # 변경 3: next_action·kind·conclusion_id·reason·evidence는 선택 필드. 값 어휘는 스키마 enum과 같아야 한다.
    row = {"row_id": "K-Fc-01", "conclusion_id": "R01-K-Fc-01", "kind": "Fc", "location": "p.57", "old": "…", "new": "…",
           "verdict": "부분수정", "reason_locus": ["E"], "reason": "실적 대비 차이", "grade": "A", "status": "L2 최종",
           "next_action": "부록 갱신", "evidence": [{"url": "https://kosis.kr/x", "grade": "A", "note": "KOSIS"}]}
    assert validate_obj(row, "comparison_row") == []
    assert validate_obj(dict(row, next_action="모름"), "comparison_row")
    assert validate_obj(dict(row, evidence=[{"url": "u"}]), "comparison_row")

def test_comparison_row_matches_actual_r01_output(ROOT):
    # 변경 4: 실제 산출물의 결론 행·본문 행 첫 행이 스키마를 통과해야 한다.
    ct = json.loads((ROOT / "reports" / "R01" / "comparison_table.json").read_text(encoding="utf-8"))
    assert validate_obj(ct["conclusion_rows"][0], "comparison_row") == []
    assert validate_obj(ct["body_rows"][0], "comparison_row") == []

def test_event_matches_actual_r01_output(ROOT):
    events = json.loads((ROOT / "reports" / "R01" / "L0" / "events.json").read_text(encoding="utf-8"))
    assert validate_obj(events[0], "event") == []

def test_validate_jsonl_file(tmp_path):
    p = tmp_path / "e.jsonl"
    good = {"source": "openalex", "id": "1", "url": "u", "title": "t", "date": None, "snippet": "", "grade": "A",
            "retrieved_at": "2026-09-15T00:00:00", "query": "q", "extra": {}}
    bad = dict(good, grade="Z")
    p.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
    errs = validate_file(p, "evidence_record")
    assert len(errs) == 1 and errs[0].startswith("행 2")
