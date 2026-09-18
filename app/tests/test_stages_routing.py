"""engine.stages.stages_for 의 유형 기반 조건부 라우팅과 runner 의 files 키 경로 제한 테스트.

- 결론 유형(03_argument_chains.json 의 conclusions[].types)에 해당하는 L1 단계만 목록에 넣는다.
- chains 파일이 아직 없으면(첫 실행) 유형별 단계를 모두 넣는다.
- options.survey_redesign / experiment_plan 이 false 면 design_* 단계를 뺀다.
- files 키는 reports/<id>/ 안으로만 쓸 수 있다.
네트워크·LLM 없음.
"""
from __future__ import annotations

import config
from engine.runner import collect_files, normalize_outputs
from engine.stages import get_stage, stages_for

RID = "R91"
ALL_L1 = ["verify_forecast", "verify_model", "verify_policy", "design_survey", "design_experiment"]
FULL_ORDER = ["intake", "classify", "chains", "delta", "impact",
              "verify_forecast", "verify_model", "verify_policy", "design_survey", "design_experiment",
              "brief", "blind", "compare", "report", "critic"]


def chains(*types_per_conclusion) -> dict:
    """결론마다 types 만 다른 최소 사슬 파일."""
    return {"report_id": RID,
            "conclusions": [{"conclusion_id": f"{RID}-K-{i:02d}", "kind": "Fc", "page": 1, "statement": "원 결론 문장",
                             "method": "방법", "premises": [], "evidence_refs": [], "types": list(ts), "rerun_grade": "R1"}
                            for i, ts in enumerate(types_per_conclusion, start=1)],
            "premises": [], "claims": [], "edges": []}


def rc(options: dict | None = None, layers=("L0", "L1", "L2")) -> dict:
    cfg = {"report_id": RID, "layers": list(layers),
           "options": {"blind_rerun": {"enabled": True, "repeats": 1}, "survey_redesign": True, "experiment_plan": True,
                       "synthetic_sim": {"enabled": False, "panel_size": 200}, "l0_rewrite_scope": "env_and_desk_updatable"},
           "sources": ["web"], "output": ["html"], "period": {"since": "", "until": "today"}}
    cfg["options"].update(options or {})
    return cfg


def names(cfg: dict, report_id: str = RID) -> list:
    return [s.name for s in stages_for(cfg, report_id)]


# ---------------------------------------------------------------- 유형 기반 라우팅
def test_forecast_only_drops_model_and_survey(make_report):
    """① chains 에 F 만 있으면 verify_model·design_survey 등은 목록에서 빠진다."""
    make_report(RID, files={"03_argument_chains.json": chains(["F"])})
    got = names(rc())
    assert "verify_forecast" in got
    for n in ("verify_model", "verify_policy", "design_survey", "design_experiment"):
        assert n not in got, n
    # 나머지 층은 그대로다
    assert [n for n in got if n not in ALL_L1] == [n for n in FULL_ORDER if n not in ALL_L1]


def test_survey_type_adds_design_survey(make_report):
    """② S 가 있으면 design_survey 가 들어간다(T 는 design_experiment)."""
    make_report(RID, files={"03_argument_chains.json": chains(["S"], ["T"])})
    got = names(rc())
    assert "design_survey" in got and "design_experiment" in got
    assert "verify_forecast" not in got and "verify_model" not in got and "verify_policy" not in got


def test_case_and_kpi_types_go_to_forecast(make_report):
    """B(사례)·G(기관 전략)는 전망 검증 단계가 맡는다."""
    make_report(RID, files={"03_argument_chains.json": chains(["B"], ["G"])})
    got = names(rc())
    assert "verify_forecast" in got
    assert "verify_model" not in got and "design_survey" not in got


def test_mixed_types_add_each_owner(make_report):
    make_report(RID, files={"03_argument_chains.json": chains(["F", "M"], ["P"], ["S"])})
    got = names(rc())
    assert [n for n in got if n in ALL_L1] == ["verify_forecast", "verify_model", "verify_policy", "design_survey"]


def test_option_off_drops_design_stages(make_report):
    """③ options.survey_redesign=false 면 design_survey 가 빠진다(experiment_plan 도 같다)."""
    make_report(RID, files={"03_argument_chains.json": chains(["S"], ["T"])})
    assert "design_survey" not in names(rc(options={"survey_redesign": False}))
    assert "design_experiment" in names(rc(options={"survey_redesign": False}))
    assert "design_experiment" not in names(rc(options={"experiment_plan": False}))
    off = names(rc(options={"survey_redesign": False, "experiment_plan": False}))
    assert not [n for n in off if n in ALL_L1]


def test_no_chains_file_includes_all_stages(make_report):
    """④ chains 파일이 아직 없으면(첫 실행) 유형별 단계를 모두 넣는다."""
    make_report(RID)  # 03_argument_chains.json 없음
    assert names(rc()) == FULL_ORDER


def test_layer_filter_still_applies(make_report):
    make_report(RID, files={"03_argument_chains.json": chains(["F"], ["S"])})
    got = names(rc(layers=("L0",)))
    assert got == ["intake", "classify", "chains", "delta", "impact", "report", "critic"]


def test_stage_outputs_do_not_collide(make_report):
    """L1 단계의 '필수 출력'이 서로 겹치지 않아야 재개(건너뜀) 판정이 어긋나지 않는다.

    (comparison_table.json 은 impact 가 v0 를 만들고 compare 가 덮어쓰는 설계라 예외다.)
    """
    make_report(RID)
    seen = {}
    for spec in stages_for(rc()):
        if spec.name not in ALL_L1:
            continue
        for o in spec.outputs:
            assert o not in seen, f"{o} 가 {seen.get(o)} 와 {spec.name} 에 겹쳐 있다"
            seen[o] = spec.name
    assert seen["L1/verdicts.json"] == "verify_forecast"
    assert seen["L1/model_rerun.json"] == "verify_model"
    assert seen["L1/policy_tracking.md"] == "verify_policy"
    assert seen["L3/survey_index.json"] == "design_survey"
    assert seen["L3/experiment_index.json"] == "design_experiment"


def test_l1_stages_have_prompts_and_layer():
    for name in ALL_L1:
        spec = get_stage(name)
        assert spec.layer == "L1", name
        assert (config.PROMPTS_DIR / spec.prompt_file).exists(), spec.prompt_file
    assert get_stage("verify").name == "verify_forecast"  # 옛 이름 호환


# ---------------------------------------------------------------- files 키 경로 제한
def test_files_key_rejects_escape(make_report):
    """⑤ files 키로 reports/<id>/ 밖을 쓰려 하면 거부된다."""
    rd = make_report(RID, files={"03_argument_chains.json": chains(["S"])})
    spec = get_stage("design_survey")
    for bad in ("../evil.md", "../../evil.md", "L3/../../evil.md", str(config.CORE_DIR / "evil.md")):
        outputs, errors = normalize_outputs(spec, {"L3/survey_index.json": [], "files": {bad: "나쁜 파일"}}, RID)
        assert any("밖으로" in e for e in errors), (bad, errors)
        assert not outputs.get(bad)
    assert not (rd.parent / "evil.md").exists() and not (config.CORE_DIR / "evil.md").exists()


def test_files_key_accepts_report_paths(make_report):
    make_report(RID, files={"03_argument_chains.json": chains(["S"])})
    spec = get_stage("design_survey")
    obj = {"L3/survey_index.json": [{"conclusion_id": f"{RID}-K-01", "decision": "설계서필요",
                                     "substitute_survey": None, "design_file": f"L3/survey_redesign_{RID}-K-01.md"}],
           "files": {f"reports/{RID}/L3/survey_redesign_{RID}-K-01.md": "# 재설문 설계서\n내용"}}
    outputs, errors = normalize_outputs(spec, obj, RID)
    assert errors == []
    assert outputs[f"L3/survey_redesign_{RID}-K-01.md"].startswith("# 재설문 설계서")


def test_files_key_not_allowed_for_other_stages(make_report):
    make_report(RID, files={"02_classification.json": {}})
    spec = get_stage("chains")
    _, errors = collect_files(spec, {"files": {"L3/x.md": "내용"}}, RID)
    assert errors and "files" in errors[0]
    assert collect_files(spec, {"files": {}}, RID) == ({}, [])
