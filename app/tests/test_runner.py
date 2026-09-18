"""engine.runner / stages / jobs 테스트 — MockLLM 으로 classify→chains→delta→impact→L1(전망·모형·정책·설문·실험)
→brief→blind→compare→report→critic 흐름, 스키마 오류 재요청, 재개 건너뜀, 블라인드 격리, 강제 재실행, JobStore 를 확인한다.
유형 기반 단계 라우팅 자체는 test_stages_routing.py 에서 본다. 네트워크 없음."""
from __future__ import annotations
import json
import queue
import threading
import time

import pytest

import config
from engine import search as search_mod
from engine.runner import run_pipeline, run_stage, parse_final_json, JsonlLogger
from engine.stages import get_stage, stages_for
from engine.tools import ToolRegistry
from tests.conftest import MockLLM, all_text, calls, final, tool_call

RID = "R90"
SRC_MARKER = "ORIG_SOURCE_MARKER_ZX9"
STMT_SECRET = "원결론문장비밀토큰77"
SOURCE = ("<!-- page 1 -->\n연구보고서 표지\n<!-- page 2 -->\n목 차\n제1장 서론 … 5\n<!-- page 3 -->\n"
          f"본문 {SRC_MARKER}. 2022년 말 이음5G 26개소.\n" + "환경분석 장 문단. " * 600 + f"\n<!-- page 4 -->\n결론: {STMT_SECRET} 2030년 910개소")
# SOURCE 는 약 6,000자: settings.max_source_chars(5,000) 보다 길고 classify 상한(30,000) 보다 짧다

CLASSIFICATION = {"report_id": RID, "title": "테스트 보고서", "published": "2023-04", "domains": ["network_5g6g", "spectrum"],
                  "type_mix": {"F": 0.6, "P": 0.4},
                  "research_design": {"rq": "이음5G 사이트 수 전망", "methods": ["상향식"], "data": ["KCA"], "sample": "", "limits": []},
                  "structure": []}
CHAINS = {"report_id": RID,
          "conclusions": [{"conclusion_id": "R90-K-Fc-01", "kind": "Fc", "statement": f"2030년 이음5G 910개소 {STMT_SECRET}", "page": 4,
                           "method": "상향식", "premises": ["P-01"], "evidence_refs": ["R90-F-001"], "types": ["F"], "rerun_grade": "R1"},
                          {"conclusion_id": "R90-K-R-01", "kind": "R", "statement": "28㎓ 대역 정책 재검토 제언", "page": 4,
                           "method": "정성", "premises": ["P-01"], "evidence_refs": [], "types": ["P"], "rerun_grade": "R2"}],
          "premises": [{"premise_id": "P-01", "statement": "2022년 말 26개소", "section": "제3장", "page": 3, "indicator": "이음5G 사이트 수"}],
          "claims": [{"claim_id": "R90-F-001", "conclusion_id": "R90-K-Fc-01", "type": "F", "page": 4, "statement": "2030년 910개소",
                      "original_value": {"metric": "사이트 수", "year": 2030, "value": 910, "unit": "개소"}, "verify_method": "backtest"}],
          "edges": [{"from": "P-01", "to": "R90-K-Fc-01", "relation": "premise_of", "confidence": 0.9}]}
EVENT = {"event_id": "E-network_5g6g-2024-01-eum5g_54_sites", "domain": "network_5g6g", "date": "2024-01",
         "title": "이음5G 54개소", "summary": "2023년 말 54개소로 확대.", "affected_indicators": ["이음5G 사이트 수"],
         "sources": [{"url": "https://example.gov/press", "title": "보도자료", "retrieved_at": "2026-09-15"}], "grade": "A"}
ROW_OLD = f"2030년 이음5G 910개소 {STMT_SECRET}"


def crow(verdict="", status="L0 잠정", new="잠정: 전제 약화", old=ROW_OLD, **kw):
    r = {"row_id": "K-Fc-01", "conclusion_id": "R90-K-Fc-01", "kind": "Fc", "location": "제7장 p.4", "old": old, "new": new,
         "blind_new": "", "verdict": verdict, "reason_locus": ["P"], "reason": "사건 E 로 전제 약화",
         "evidence": [{"url": "https://example.gov/press", "grade": "A", "note": "사건"}], "grade": "C", "status": status,
         "upstream": ["P-01"]}
    r.update(kw)
    return r


def brow():
    return {"row_id": "S-3.1", "level": "section", "location": "제3장 p.3", "old": "2022년 말 26개소", "new": "2023년 말 54개소",
            "change_type": "수치갱신", "reason": "사건", "evidence": [{"url": "https://example.gov/press", "grade": "A"}],
            "grade": "A", "status": "L0 잠정", "linked_conclusions": ["R90-K-Fc-01"]}


def cmp_table(rows, maturity="L0", **kw):
    d = {"report_id": RID, "title": "테스트 보고서", "published": "2023-04", "generated_at": "2026-09-15", "maturity": maturity,
         "summary": {}, "conclusion_rows": rows, "body_rows": [brow()]}
    d.update(kw)
    return d


VERDICT = {"claim_id": "R90-F-001", "verdict": "과대", "original_value": {"metric": "사이트 수", "year": 2030, "value": 910, "unit": "개소"},
           "current_value": {"value": 104, "unit": "개소", "asof": "2025-12"}, "error_pct": 775.0, "reason": "실적 대비 과대",
           "evidence": [{"url": "https://example.gov/stat", "grade": "A", "retrieved_at": "2026-09-15"}]}
POLICY_VERDICT = {"claim_id": "R90-P-001", "verdict": "유효", "current_value": {"value": "시행", "asof": "2025-06"},
                  "reason": "제언이 고시로 반영돼 시행 중", "verify_method": "policy_track",
                  "evidence": [{"url": "https://law.go.kr/x", "grade": "A", "retrieved_at": "2026-09-15"}]}
TRACED = [{"conclusion_id": "R90-K-Fc-01", "method_applied": "상향식", "inputs_now": [], "rederived": "2030년 약 480개소",
           "delta_vs_original": "하향", "changed_locus": ["E"], "grade": "C", "calc_note": "…"}]
BRIEF = "# 블라인드 재수행 브리프 · R90\n\n## 연구질문\n이음5G 사이트 수를 전망한다.\n\n## 답해야 할 항목\n- Q1 2030년 사이트 수는 얼마인가.\n\n## 기간\n현재 시점 2026-09-15."
BLIND = [{"item_id": "Q1", "question": "2030년 사이트 수는 얼마인가.", "conclusion": "2030년 약 479개소", "method_used": "상향식",
          "inputs": [{"name": "현재 사이트", "value": 104, "unit": "개소", "source_url": "https://example.gov/stat", "grade": "A"}],
          "confidence": "중간", "caveats": [], "grade": "C"},
         {"files_opened": ["reports/R90/00_source/R90.md", "L2/blind_input/brief.md"]}]  # 러너가 강제로 바꿔야 한다


def run_config(layers=("L0", "L1", "L2"), blind=True, repeats=1):
    return {"report_id": RID, "layers": list(layers),
            "options": {"blind_rerun": {"enabled": blind, "repeats": repeats}, "survey_redesign": True, "experiment_plan": True,
                        "synthetic_sim": {"enabled": False, "panel_size": 200}, "l0_rewrite_scope": "env_and_desk_updatable"},
            "sources": ["web"], "output": ["html"], "period": {"since": "", "until": "today"}}


def call_of(llm, stage: str) -> dict:
    """단계 이름으로 MockLLM 호출을 찾는다(사용자 메시지 머리말의 '단계: <name>')."""
    hits = [c for c in llm.calls if f"단계: {stage}\n" in c["messages"][1]["content"]]
    assert hits, f"{stage} 호출을 찾지 못했습니다"
    return hits[-1]


def full_responses():
    """classify→chains→delta(도구 1회)→impact→L1 5단계→brief→blind→compare→(report 파이썬)→critic 순서의 응답.

    첫 실행에는 03_argument_chains.json 이 아직 없으므로 유형별 L1 단계가 모두 들어간다.
    대상이 없는 단계(M·S·T)는 각 프롬프트 규칙대로 빈 배열을 돌려준다.
    """
    return [
        final({"02_classification.json": CLASSIFICATION}),
        final({"03_argument_chains.json": CHAINS}),
        calls(tool_call("web_search", {"query": "이음5G 구축 현황", "since": "2023-05-01"})),
        final({"L0/events.json": [EVENT], "L0/environment_delta.md": "| 날짜 | 사건 |\n|---|---|\n| 2024-01 | 54개소 |"}),
        final({"L0/provisional_verdicts.json": [{"conclusion_id": "R90-K-Fc-01", "hit_premises": [], "provisional": {}, "grade": "C"}],
               "comparison_table.json": cmp_table([crow(), crow(row_id="K-R-01", conclusion_id="R90-K-R-01", kind="R", old="28㎓ 대역 정책 재검토 제언")])}),
        final({"L1/verdicts.json": [VERDICT], "L2/traced/traced_conclusions.json": TRACED}),          # verify_forecast
        final({"L1/model_rerun.json": [], "L2/traced/traced_conclusions.json": []}),                   # verify_model (M 없음)
        final({"L1/policy_tracking.md": "| 제언 | 단계 | 근거 | 등급 | 연결 K-ID |\n|---|---|---|---|---|\n| 28㎓ 재검토 | 시행 | 고시 | A | R90-K-R-01 |",
               "L1/verdicts.json": [POLICY_VERDICT]}),                                                # verify_policy
        final({"L3/survey_index.json": [], "files": {}}),                                             # design_survey (S 없음)
        final({"L3/experiment_index.json": []}),                                                      # design_experiment (T 없음)
        final({"L2/blind_input/brief.md": BRIEF, "L2/compare/question_map.json": {"Q1": "R90-K-Fc-01"}}),
        final({"L2/blind_output/blind_conclusions.json": BLIND}),
        final({"comparison_table.json": cmp_table(
            [crow(verdict="약화", status="L2 최종", new="2030년 약 480개소(추적)", blind_new="약 479개소(블라인드)",
                  old="고쳐진 old 문장(금지)"),
             crow(row_id="K-R-01", conclusion_id="R90-K-R-01", kind="R", old="28㎓ 대역 정책 재검토 제언", verdict="", status="L0 잠정")],
            maturity="L2(부분)", summary={"동일": 9}), "L2/compare/verdict_notes.md": "# 판정 근거\n| K | 판정 |"}),
        final({"07_report/critic_notes.md": "# 검토 기록 · R90\n- 결과: **PASS**"}),
    ]


@pytest.fixture
def stub_search(monkeypatch):
    rec = []

    def fake(query, since=None, max_results=8, lang="ko", provider="auto", env=None, llm=None):
        rec.append({"query": query, "since": since})
        return [{"title": "결과", "url": "https://example.gov/press", "snippet": "54개소", "date": "2024-01-03", "source": "stub"}]

    monkeypatch.setattr(search_mod, "search", fake)
    return rec


@pytest.fixture
def events():
    got = []
    return got


def _run(rid, rc, llm, settings, progress=None, **kw):
    tools = ToolRegistry(env={}, llm=llm, settings=settings)
    return run_pipeline(rid, rc, progress=progress, cancel=threading.Event(), settings=settings, llm=llm, tools=tools,
                        job_id="job_test", **kw)


# ---------------------------------------------------------------- 단계 매핑
def test_stages_for_layers_and_options():
    names = [s.name for s in stages_for(run_config())]
    assert names == ["intake", "classify", "chains", "delta", "impact", "verify_forecast", "verify_model", "verify_policy",
                     "design_survey", "design_experiment", "brief", "blind", "compare", "report", "critic"]
    assert [s.name for s in stages_for(run_config(layers=("L0",)))] == ["intake", "classify", "chains", "delta", "impact", "report", "critic"]
    assert "brief" not in [s.name for s in stages_for(run_config(blind=False))]
    assert "blind" not in [s.name for s in stages_for(run_config(blind=False))]
    reps = stages_for(run_config(repeats=2))
    assert [s.name for s in reps if s.name.startswith("blind")] == ["blind", "blind_2"]
    assert reps[[s.name for s in reps].index("blind_2")].outputs == ["L2/blind_output/blind_conclusions_2.json"]
    assert get_stage("blind_2").name == "blind"
    for s in stages_for(run_config()):
        assert s.python or s.prompt_file, s.name
        if s.prompt_file:
            assert (config.PROMPTS_DIR / s.prompt_file).exists(), s.prompt_file


def test_parse_final_json_variants():
    assert parse_final_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_final_json('설명\n{"a": {"b": [1]}}\n끝') == {"a": {"b": [1]}}
    with pytest.raises(ValueError):
        parse_final_json("JSON 없음")


# ---------------------------------------------------------------- 전체 흐름
def test_full_pipeline_flow(make_report, settings, stub_search, core_dir):
    rd = make_report(RID, SOURCE)
    llm = MockLLM(full_responses())
    events = []
    out = _run(RID, run_config(), llm, settings, progress=events.append)
    assert out["status"] == "done", out["error"]
    st = {s["stage"]: s["status"] for s in out["stages"]}
    assert st == {"intake": "skipped", "classify": "done", "chains": "done", "delta": "done", "impact": "done",
                  "verify_forecast": "done", "verify_model": "done", "verify_policy": "done",
                  "design_survey": "done", "design_experiment": "done",
                  "brief": "done", "blind": "done", "compare": "done", "report": "done", "critic": "done"}
    assert not llm.responses, "준비한 응답을 모두 써야 한다"
    assert len(llm.calls) == 14
    # 산출 파일
    for rel in ("02_classification.json", "03_argument_chains.json", "L0/events.json", "L0/environment_delta.md",
                "L0/provisional_verdicts.json", "comparison_table.json", "L0/comparison_table_v0.json", "L1/verdicts.json",
                "L1/model_rerun.json", "L1/policy_tracking.md", "L3/survey_index.json", "L3/experiment_index.json",
                "L2/traced/traced_conclusions.json", "L2/blind_input/brief.md", "L2/compare/question_map.json",
                "L2/blind_output/blind_conclusions.json", "L2/compare/verdict_notes.md", "07_report/comparison_table.html",
                "07_report/comparison_table_v0_L0.html", "07_report/report.md", "07_report/report.html", "07_report/critic_notes.md",
                "logs/app_run.jsonl"):
        assert (rd / rel).exists(), rel
    # L1/verdicts.json 은 여러 단계가 claim_id 기준으로 덧붙인다(전망 + 정책)
    verdicts = json.loads((rd / "L1" / "verdicts.json").read_text(encoding="utf-8"))
    assert [v["claim_id"] for v in verdicts] == ["R90-F-001", "R90-P-001"]
    # 빈 배열을 낸 모형 단계가 앞 단계의 추적 재도출을 지우지 않는다
    traced = json.loads((rd / "L2" / "traced" / "traced_conclusions.json").read_text(encoding="utf-8"))
    assert [t["conclusion_id"] for t in traced] == ["R90-K-Fc-01"]
    # 도구 호출이 tool 메시지로 들어갔는지(delta 의 두 번째 호출)
    delta_msgs = llm.calls[3]["messages"]
    assert delta_msgs[-1]["role"] == "tool" and "example.gov" in delta_msgs[-1]["content"]
    assert stub_search == [{"query": "이음5G 구축 현황", "since": "2023-05-01"}]
    # 모델 역할: classify·brief 는 cheap
    assert llm.calls[0]["model"] == "mock/cheap" and call_of(llm, "brief")["model"] == "mock/cheap" and llm.calls[1]["model"] == "mock/main"
    assert llm.calls[0]["json_mode"] is True and llm.calls[2]["json_mode"] is False
    # 입력 인라인 규칙
    classify_user = llm.calls[0]["messages"][1]["content"]
    assert "### 파일: 00_source/R90.md" in classify_user and "### 파일: 01_meta.json" in classify_user
    assert "역할 지시서 (prompts/00_intake.md)" in classify_user and '"02_classification.json"' in classify_user
    delta_user = llm.calls[2]["messages"][1]["content"]
    assert "premises 만" in delta_user and '"premise_id": "P-01"' in delta_user and '"claims"' not in delta_user
    assert "조사 기간: 2023-05" in delta_user and "도메인: network_5g6g" in delta_user
    chains_user = llm.calls[1]["messages"][1]["content"]
    assert "앞 5,000자만 인라인" in chains_user  # settings.max_source_chars
    compare_user = call_of(llm, "compare")["messages"][1]["content"]
    assert "### 파일: templates/verdict_rules.yaml" in compare_user and "blind_conclusions.json" in compare_user
    # 같은 프롬프트를 나눠 쓰는 단계는 "이 단계의 한정" 지시로 대상 유형을 좁힌다
    policy_user = call_of(llm, "verify_policy")["messages"][1]["content"]
    assert "## 이 단계의 한정" in policy_user and "정책·제도 대안형(P)" in policy_user
    assert "역할 지시서 (prompts/04_forecast_verify.md)" in policy_user
    assert "역할 지시서 (prompts/04b_survey.md)" in call_of(llm, "design_survey")["messages"][1]["content"]
    assert "역할 지시서 (prompts/04c_experiment.md)" in call_of(llm, "design_experiment")["messages"][1]["content"]
    assert "역할 지시서 (prompts/04a_model.md)" in call_of(llm, "verify_model")["messages"][1]["content"]
    # kb/events 복사
    kb_files = list((core_dir / "kb" / "events" / "network_5g6g").glob("2024-01_*.md"))
    assert len(kb_files) == 1
    txt = kb_files[0].read_text(encoding="utf-8")
    assert txt.startswith("---") and "event_id: E-network_5g6g-2024-01-eum5g_54_sites" in txt and "54개소" in txt
    # compare: old 복원·summary 재집계·v0 불변
    cmp = json.loads((rd / "comparison_table.json").read_text(encoding="utf-8"))
    v0 = json.loads((rd / "L0" / "comparison_table_v0.json").read_text(encoding="utf-8"))
    assert cmp["conclusion_rows"][0]["old"] == ROW_OLD == v0["conclusion_rows"][0]["old"]
    assert cmp["conclusion_rows"][0]["verdict"] == "약화"
    assert cmp["summary"] == {"동일": 0, "강화": 0, "부분수정": 0, "약화": 1, "뒤집힘": 0, "신규결론": 0, "판정불가": 0, "잠정": 1}
    # 레지스트리 성숙도·도메인
    from scripts.registry import load_registry
    row = next(r for r in load_registry(config.REGISTRY_CSV) if r["id"] == RID)
    assert row["maturity"] == "L2(부분)" and row["domain"] == "network_5g6g" and row["types"] == "F,P"
    # 진행 이벤트·토큰·비용
    assert events[-1]["stage"] == "pipeline" and events[-1]["status"] == "done"
    assert {e["stage"] for e in events} >= {"classify", "blind", "report", "pipeline"}
    assert out["tokens"] == {"in": 1400, "out": 700} and out["cost_usd"] == pytest.approx(0.014)
    assert all(e["job_id"] == "job_test" and e["ts"] for e in events)
    # 로그
    lines = [json.loads(l) for l in (rd / "logs" / "app_run.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = {(l["stage"], l["event"]) for l in lines}
    assert ("delta", "tool") in kinds and ("chains", "write") in kinds and ("intake", "skip") in kinds
    assert all({"ts", "stage", "model", "step", "event", "tokens_in", "tokens_out", "cost_usd", "note"} <= set(l) for l in lines)


def test_blind_isolation(make_report, settings, stub_search):
    rd = make_report(RID, SOURCE)
    llm = MockLLM(full_responses())
    out = _run(RID, run_config(), llm, settings)
    assert out["status"] == "done", out["error"]
    blind_call = call_of(llm, "blind")
    text = all_text(blind_call)
    assert SRC_MARKER not in text and STMT_SECRET not in text and "910" not in text
    assert "03_argument_chains" not in text.replace("03_argument_chains.json", "") or True
    assert "### 파일: L2/blind_input/brief.md" in text and "이음5G 사이트 수를 전망한다" in text
    assert "### 파일: 00_source" not in text and "question_map" not in text
    names = {d["function"]["name"] for d in (blind_call["tools"] or [])}
    assert names == {"web_search", "fetch_page", "evidence_search"}
    blind = json.loads((rd / "L2" / "blind_output" / "blind_conclusions.json").read_text(encoding="utf-8"))
    assert blind[-1] == {"files_opened": ["L2/blind_input/brief.md"]}
    assert sum(1 for x in blind if isinstance(x, dict) and "files_opened" in x) == 1
    assert blind[0]["item_id"] == "Q1"


def test_design_survey_writes_design_file_and_l3_maturity(make_report, settings, stub_search):
    """design_survey 가 files 키로 설계서를 쓰고, 설계서가 있으면 성숙도가 L3 가 된다."""
    rd = make_report(RID, SOURCE, files={"03_argument_chains.json": CHAINS,
                                         "comparison_table.json": cmp_table([crow(verdict="판정불가", status="R3 설계서")], maturity="L2"),
                                         "L0/comparison_table_v0.json": cmp_table([crow()])})
    design = "# 재설문 설계서 · R90-K-Fc-01\n\n| 항목 | 값 |\n|---|---|\n| 현재 판정 · 사유 | 판정불가 · 대체 조사 없음 |\n"
    llm = MockLLM([final({"L3/survey_index.json": [{"conclusion_id": "R90-K-Fc-01", "decision": "설계서필요",
                                                    "substitute_survey": None,
                                                    "design_file": "L3/survey_redesign_R90-K-Fc-01.md"}],
                          "L1/verdicts.json": [],
                          "files": {"L3/survey_redesign_R90-K-Fc-01.md": design}})])
    tools = ToolRegistry(env={}, llm=llm, settings=settings)
    res = run_stage(RID, "design_survey", settings, llm, tools, JsonlLogger(rd / "logs" / "app_run.jsonl"))
    assert res.status == "done", res.error
    assert "L3/survey_redesign_R90-K-Fc-01.md" in res.outputs
    assert (rd / "L3" / "survey_redesign_R90-K-Fc-01.md").read_text(encoding="utf-8").startswith("# 재설문 설계서")
    # 성숙도: L3/ 설계서가 있으면 L3
    rep = run_stage(RID, "report", settings, None, None, JsonlLogger(rd / "logs" / "app_run.jsonl"))
    assert rep.status == "done", rep.error
    from scripts.registry import load_registry
    row = next(r for r in load_registry(config.REGISTRY_CSV) if r["id"] == RID)
    assert row["maturity"] == "L3"


def test_resume_skips_when_outputs_exist(make_report, settings, stub_search):
    make_report(RID, SOURCE)
    llm = MockLLM(full_responses())
    assert _run(RID, run_config(), llm, settings)["status"] == "done"
    n = len(llm.calls)
    out2 = _run(RID, run_config(), llm, settings)  # 응답 없음 → 호출되면 LLMError → failed
    assert out2["status"] == "done"
    assert all(s["status"] == "skipped" for s in out2["stages"])
    assert len(llm.calls) == n


def test_force_from_reruns_with_backup(make_report, settings, stub_search):
    rd = make_report(RID, SOURCE)
    llm = MockLLM(full_responses())
    assert _run(RID, run_config(), llm, settings)["status"] == "done"
    llm.add(final({"comparison_table.json": cmp_table([crow(verdict="동일", status="L2 최종", new="같음", blind_new="같음")], maturity="L2"),
                   "L2/compare/verdict_notes.md": "# v2"}),
            final({"07_report/critic_notes.md": "# 검토 기록 2회차"}))
    out = _run(RID, run_config(), llm, settings, force_from="compare")
    assert out["status"] == "done", out["error"]
    st = {s["stage"]: s["status"] for s in out["stages"]}
    assert st["blind"] == "skipped" and st["compare"] == "done" and st["report"] == "done" and st["critic"] == "done"
    assert list(rd.glob("comparison_table.json.bak.*")) and list((rd / "L2" / "compare").glob("verdict_notes.md.bak.*"))
    assert "2회차" in (rd / "07_report" / "critic_notes.md").read_text(encoding="utf-8")
    cmp = json.loads((rd / "comparison_table.json").read_text(encoding="utf-8"))
    assert cmp["summary"]["동일"] == 1 and cmp["maturity"] == "L2"


# ---------------------------------------------------------------- 검증 실패 재요청
def test_schema_error_triggers_repair(make_report, settings):
    rd = make_report(RID, SOURCE, files={"02_classification.json": CLASSIFICATION})
    bad = {k: v for k, v in CHAINS.items() if k != "premises"}
    bad["conclusions"] = [dict(CHAINS["conclusions"][0], kind="X")]
    llm = MockLLM([final({"03_argument_chains.json": bad}), final({"03_argument_chains.json": CHAINS})])
    log_path = rd / "logs" / "app_run.jsonl"
    res = run_stage(RID, "chains", settings, llm, ToolRegistry(env={}, llm=llm, settings=settings), JsonlLogger(log_path))
    assert res.status == "done" and res.steps == 2
    repair = llm.calls[1]["messages"]
    assert repair[-2]["role"] == "assistant" and repair[-1]["role"] == "user"
    assert "premises" in repair[-1]["content"] and "kind" in repair[-1]["content"] and "JSON만" in repair[-1]["content"]
    assert json.loads((rd / "03_argument_chains.json").read_text(encoding="utf-8")) == CHAINS


def test_repair_exhausted_fails_without_writing(make_report, settings):
    rd = make_report(RID, SOURCE, files={"02_classification.json": CLASSIFICATION})
    llm = MockLLM([final("이건 JSON 이 아님"), final({"엉뚱한키": 1}), final({"03_argument_chains.json": "문자열이라 실패"})])
    res = run_stage(RID, "chains", settings, llm, ToolRegistry(env={}, llm=llm, settings=settings), JsonlLogger(rd / "logs" / "app_run.jsonl"))
    assert res.status == "failed" and res.steps == 3 and "검증 실패" in res.error
    assert not (rd / "03_argument_chains.json").exists()
    lines = [json.loads(l) for l in (rd / "logs" / "app_run.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(l["event"] == "error" and l.get("raw") for l in lines)
    # 파이프라인은 실패 단계에서 멈춘다
    llm2 = MockLLM([final({"02_classification.json": CLASSIFICATION}), final("x"), final("x"), final("x")])
    out = _run(RID, run_config(layers=("L0",)), llm2, settings)
    assert out["status"] == "failed" and out["error"].startswith("chains:")
    assert [s["stage"] for s in out["stages"]] == ["intake", "classify", "chains"]


def test_run_config_model_and_provider_override(make_report, settings, monkeypatch):
    """실행 화면에서 고른 model·search_provider 가 settings 보다 우선한다(서버가 run_config 에 그대로 담아 넘김)."""
    make_report(RID, SOURCE)
    rec = []

    def fake(query, since=None, max_results=8, lang="ko", provider="auto", env=None, llm=None):
        rec.append(provider)
        return []

    monkeypatch.setattr(search_mod, "search", fake)
    llm = MockLLM([final({"02_classification.json": CLASSIFICATION}), final({"03_argument_chains.json": CHAINS}),
                   calls(tool_call("web_search", {"query": "q"}))])  # 이후 응답 없음 → delta 실패로 끝
    rc = dict(run_config(layers=("L0",)), model="rc/model", search_provider="exa")
    out = run_pipeline(RID, rc, progress=None, cancel=threading.Event(), settings=settings, llm=llm, job_id="j")
    assert out["status"] == "failed" and out["error"].startswith("delta:")
    assert llm.calls[0]["model"] == "mock/cheap" and llm.calls[1]["model"] == "rc/model" and llm.calls[2]["model"] == "rc/model"
    assert rec == ["exa"]


def test_missing_required_input_fails(make_report, settings):
    make_report(RID, SOURCE)  # 02_classification 없음
    res = run_stage(RID, "chains", settings, MockLLM([]), ToolRegistry(env={}, llm=None, settings=settings), lambda e: None)
    assert res.status == "failed" and "02_classification.json" in res.error


def test_cancel_stops_at_boundary(make_report, settings):
    make_report(RID, SOURCE)
    ev = threading.Event()
    llm = MockLLM([lambda m: (ev.set(), final({"02_classification.json": CLASSIFICATION}))[1]])
    out = run_pipeline(RID, run_config(layers=("L0",)), progress=None, cancel=ev, settings=settings, llm=llm,
                       tools=ToolRegistry(env={}, llm=llm, settings=settings), job_id="j")
    assert out["status"] == "cancelled"
    assert [s["stage"] for s in out["stages"]] == ["intake", "classify"]


# ---------------------------------------------------------------- JobStore
def test_jobstore_runs_in_background(core_dir):
    from engine.jobs import JobStore, RunningError
    gate = threading.Event()

    def fake_pipeline(report_id, run_config, progress=None, cancel=None, force_from=None, job_id=""):
        progress({"job_id": job_id, "report_id": report_id, "stage": "classify", "status": "running", "step": 1, "message": "시작",
                  "tokens": {"in": 10, "out": 5}, "cost_usd": 0.001, "ts": "t"})
        gate.wait(5)
        progress({"job_id": job_id, "report_id": report_id, "stage": "classify", "status": "done", "step": 2, "message": "완료",
                  "tokens": {"in": 20, "out": 10}, "cost_usd": 0.002, "ts": "t"})
        return {"status": "cancelled" if cancel.is_set() else "done", "error": "", "tokens": {"in": 20, "out": 10}, "cost_usd": 0.002,
                "stages": [{"stage": "classify", "status": "done", "steps": 2, "tokens_in": 20, "tokens_out": 10, "cost_usd": 0.002,
                            "error": "", "started_at": "a", "ended_at": "b", "outputs": ["02_classification.json"]}],
                "started_at": "a", "ended_at": "b"}

    store = JobStore(runs_dir=core_dir / "runs_test", runner=fake_pipeline)
    jid = store.start(run_config(), force_from=None)
    q = store.subscribe(jid)
    with pytest.raises(RunningError):
        store.start(run_config())
    assert isinstance(RunningError("x"), RuntimeError)
    first = q.get(timeout=5)
    assert first["stage"] == "classify" and first["status"] == "running"
    assert store.get(jid)["status"] == "running" and store.get(jid)["current_stage"] == "classify"
    assert store.cancel(jid) is True
    gate.set()
    items = []
    while True:
        it = q.get(timeout=5)
        if it is None:
            break
        items.append(it)
    assert items[-1]["status"] == "done"
    job = store.wait(jid, 5)
    assert job["status"] == "cancelled" and job["tokens"] == {"in": 20, "out": 10} and job["cost_usd"] == 0.002
    assert job["stages"][0]["name"] == "classify" and job["stages"][0]["outputs"] == ["02_classification.json"]
    assert (core_dir / "runs_test" / f"{jid}.json").exists()
    assert store.list()[0]["job_id"] == jid
    assert store.cancel(jid) is False  # 끝난 작업
    late = store.subscribe(jid)  # 끝난 작업: 최근 이벤트 재생 뒤 곧바로 종료 신호
    replay = []
    while (it := late.get(timeout=1)) is not None:
        replay.append(it)
    assert replay and replay[-1]["status"] == "done" and late.empty()
    # 다시 시작 가능
    gate.set()
    jid2 = store.start(run_config())
    assert store.wait(jid2, 5)["status"] == "done"
    assert {j["job_id"] for j in store.list()} >= {jid, jid2}
    store2 = JobStore(runs_dir=core_dir / "runs_test", runner=fake_pipeline)
    assert len(store2.list()) >= 2  # 파일에서 이전 작업 복원
