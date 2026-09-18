import json

import yaml

from scripts.validate import validate_obj

def test_taxonomy_has_7_types(ROOT):
    t = yaml.safe_load((ROOT / "templates" / "taxonomy.yaml").read_text(encoding="utf-8"))
    assert [x["code"] for x in t["types"]] == ["F","M","S","P","T","B","G"]
    for x in t["types"]:
        assert x["verify_method"] in ("backtest","model_rerun","survey_map","policy_track","standard_track","case_refresh","kpi_track")
        assert x["rerun_grade"] in ("R1","R1~R2","R2~R3")

def test_verdict_rules(ROOT):
    v = yaml.safe_load((ROOT / "templates" / "verdict_rules.yaml").read_text(encoding="utf-8"))
    assert [x["name"] for x in v["verdicts"]] == ["동일","강화","부분수정","약화","뒤집힘","신규결론","판정불가"]
    assert v["numeric_rules"]["same_within_pct"] == 10

def test_domains(ROOT):
    ids = {"spectrum","emf_inspection","broadcast_media","network_5g6g","ict_qualification","kca_management"}
    files = {p.stem for p in (ROOT / "kb" / "domains").glob("*.yaml")}
    assert files == ids
    for p in (ROOT / "kb" / "domains").glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert d["id"] == p.stem
        for key in ("name","indicators","laws","agencies","standards","journals","news_keywords"):
            assert key in d
        for ind in d["indicators"]:
            assert {"name","source","locator"} <= set(ind)

# --- 지적 B: 사람의 승인 게이트(선택 필드) -------------------------------------
# comparability·method_changed·evidence_floor_ok 는 비교기가, approval 은 사람이 채운다.
# 넷 다 선택 필드라 있는 행도 없는 행도 comparison_row 스키마를 통과해야 한다.

_BASE_ROW = {"row_id": "K-Fc-01", "conclusion_id": "R01-K-Fc-01", "kind": "Fc", "location": "p.57",
             "old": "…", "new": "…", "verdict": "부분수정", "reason_locus": ["E"], "reason": "실적 대비 차이",
             "grade": "A", "status": "L2 최종"}
_APPROVAL_ROW = dict(_BASE_ROW,
                     comparability="대체지표 비교", comparability_note="원 조사의 모집단이 사라져 KCA 집계로 대신 쟀다.",
                     method_changed=True, method_change_note="기준연도를 2022년에서 2025년으로 옮겼다.",
                     evidence_floor_ok=True,
                     approval={"approver": "홍길동", "approved_at": "2026-09-18T14:30:00+09:00",
                               "decision": "승인", "comment": "대체지표 사용 사유 확인함"})

def test_comparison_row_schema_has_approval_gate_fields(ROOT):
    props = json.loads((ROOT / "templates" / "schemas" / "comparison_row.schema.json").read_text(encoding="utf-8"))["properties"]
    for key in ("comparability", "comparability_note", "method_changed", "method_change_note",
                "evidence_floor_ok", "approval"):
        assert key in props, key
    assert props["comparability"]["enum"] == ["직접비교 가능", "대체지표 비교", "비교 불가"]
    assert props["method_changed"]["type"] == "boolean"
    assert props["evidence_floor_ok"]["type"] == "boolean"
    assert props["approval"]["properties"]["decision"]["enum"] == ["승인", "보류", "반려"]

def test_comparison_row_passes_with_and_without_approval_fields():
    # 새 필드가 없는 기존 모양도, 다 채운 모양도 통과해야 한다(선택 필드).
    assert validate_obj(_BASE_ROW, "comparison_row") == []
    assert validate_obj(_APPROVAL_ROW, "comparison_row") == []
    # approval 을 사람이 아직 안 채운 상태(null)도 통과
    assert validate_obj(dict(_BASE_ROW, approval=None), "comparison_row") == []

def test_comparison_row_rejects_bad_approval_values():
    assert validate_obj(dict(_APPROVAL_ROW, comparability="대충 비교"), "comparison_row")
    assert validate_obj(dict(_APPROVAL_ROW, method_changed="예"), "comparison_row")
    assert validate_obj(dict(_APPROVAL_ROW, evidence_floor_ok="확인함"), "comparison_row")
    bad = dict(_APPROVAL_ROW, approval=dict(_APPROVAL_ROW["approval"], decision="반쯤 승인"))
    assert validate_obj(bad, "comparison_row")

def test_actual_r01_rows_still_pass_without_new_fields(ROOT):
    # 회귀 기준: reports/R01/comparison_table.json 은 새 필드가 없어도 그대로 통과한다.
    ct = json.loads((ROOT / "reports" / "R01" / "comparison_table.json").read_text(encoding="utf-8"))
    for row in ct["conclusion_rows"] + ct["body_rows"]:
        assert validate_obj(row, "comparison_row") == [], row["row_id"]
        assert "approval" not in row
