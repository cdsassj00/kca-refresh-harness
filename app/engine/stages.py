"""단계 정의. DESIGN.md 4절 표를 그대로 코드로 옮긴다.

- inputs 는 reports/<id>/ 기준 상대경로. `kb/`·`templates/` 로 시작하면 공통 핵심(CORE_DIR) 기준.
  `<id>`·`<domain>` 자리표시자는 실행 시 치환되고, `*` 가 있으면 glob 로 여러 파일을 인라인한다.
- outputs 는 모델이 최종 JSON 응답에서 키로 돌려줘야 하는 파일 경로.
- validations 는 (출력 경로, 스키마 이름, 선택자) 목록. 선택자 "" 는 객체 전체, "[]" 는 배열 원소,
  "conclusion_rows[],body_rows[]" 처럼 쓰면 그 키의 배열 원소를 검증한다.
- input_rules 는 입력 인라인 규칙: max_chars(글자 수 상한), transform(특수 추림), optional(없어도 됨).
- guidance 는 같은 프롬프트를 쓰는 단계를 좁히는 한정 지시(러너가 역할 지시서 뒤에 붙인다).
- merge_keys 는 "여러 단계가 같은 파일에 덧붙이는" 출력의 병합 키({출력 경로: 키 이름}).
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Optional

# 층 매핑: L0 = classify·chains·delta·impact, L1 = verify_*·design_*, L2 = brief·blind·compare, 마지막에 report·critic
LAYER_OF = {
    "intake": None, "classify": "L0", "chains": "L0", "delta": "L0", "impact": "L0",
    "verify_forecast": "L1", "verify_model": "L1", "verify_policy": "L1",
    "design_survey": "L1", "design_experiment": "L1",
    "brief": "L2", "blind": "L2", "compare": "L2", "report": None, "critic": None,
}
STAGE_ORDER = ["intake", "classify", "chains", "delta", "impact",
               "verify_forecast", "verify_model", "verify_policy", "design_survey", "design_experiment",
               "brief", "blind", "compare", "report", "critic"]

# 결론 유형(templates/taxonomy.yaml) → 담당 단계. B(사례·동향)·G(기관 전략)는 전망 검증이 사례·KPI 추적까지 맡는다.
TYPE_STAGE = {"F": "verify_forecast", "B": "verify_forecast", "G": "verify_forecast",
              "M": "verify_model", "P": "verify_policy", "S": "design_survey", "T": "design_experiment"}
# 유형에 따라 켜고 끄는 L1 단계(유형 정보가 없으면 전부 넣는다)
TYPED_STAGES = ["verify_forecast", "verify_model", "verify_policy", "design_survey", "design_experiment"]
# run_config.options 로 끌 수 있는 설계 단계
OPTION_OF = {"design_survey": "survey_redesign", "design_experiment": "experiment_plan"}
# 옛 이름 → 새 이름(force_from·문서 호환)
ALIASES = {"verify": "verify_forecast"}


@dataclass
class StageSpec:
    name: str
    prompt_file: Optional[str]
    inputs: list
    outputs: list
    schema: Optional[str]
    tools: list
    isolated: bool = False
    python: Optional[str] = None
    model_role: str = "main"
    # 아래는 DESIGN 표의 "비고" 열을 코드로 옮긴 보조 필드
    validations: list = field(default_factory=list)       # [(output, schema, selector)]
    input_rules: dict = field(default_factory=dict)       # {input: {"max_chars": n, "transform": "...", "optional": bool}}
    optional_outputs: list = field(default_factory=list)  # 있으면 저장, 없어도 실패 아님
    required_inputs: list = field(default_factory=list)   # 없으면 단계 실패
    note: str = ""
    guidance: str = ""                                    # 같은 프롬프트를 나눠 쓰는 단계의 한정 지시
    merge_keys: dict = field(default_factory=dict)        # {출력 경로: 병합 키} — 기존 파일과 합쳐 쓴다
    types: list = field(default_factory=list)             # 이 단계가 맡는 결론 유형(빈 목록이면 유형과 무관)
    allow_files: str = ""                                 # 비어 있지 않으면 최종 JSON 의 files 키를 허용(설명 문구)

    @property
    def layer(self) -> Optional[str]:
        if self.name in LAYER_OF:
            return LAYER_OF[self.name]
        return LAYER_OF.get(self.name.split("_")[0])

    @property
    def is_python(self) -> bool:
        return self.python is not None


STAGES: list = [
    StageSpec(
        name="intake", prompt_file=None, inputs=[], outputs=["00_source/<id>.md", "01_meta.json"],
        schema=None, tools=[], python="parsing.parse_document",
        note="접수: 원본 문서를 마크다운으로 변환하고 메타를 만든다"),
    StageSpec(
        name="classify", prompt_file="00_intake.md",
        inputs=["00_source/<id>.md", "01_meta.json"], outputs=["02_classification.json"],
        schema=None, tools=[], model_role="cheap",
        input_rules={"00_source/<id>.md": {"max_chars": 30000, "transform": "head_with_toc"}},
        required_inputs=["00_source/<id>.md", "01_meta.json"],
        note="분류: 도메인·유형·연구설계"),
    StageSpec(
        name="chains", prompt_file="01_chains.md",
        inputs=["00_source/<id>.md", "01_meta.json", "02_classification.json"], outputs=["03_argument_chains.json"],
        schema="chain", tools=["read_report_file"],
        validations=[("03_argument_chains.json", "chain", "")],
        input_rules={"00_source/<id>.md": {"max_chars": "max_source_chars"}},
        required_inputs=["00_source/<id>.md", "02_classification.json"],
        note="결론·논증 사슬 추출"),
    StageSpec(
        name="delta", prompt_file="02_delta.md",
        inputs=["01_meta.json", "02_classification.json", "03_argument_chains.json", "kb/events/<domain>/*.md"],
        outputs=["L0/events.json", "L0/environment_delta.md"],
        schema="event", tools=["web_search", "fetch_page", "read_core_file"],
        validations=[("L0/events.json", "event", "[]")],
        input_rules={"03_argument_chains.json": {"transform": "premises_only"},
                     "kb/events/<domain>/*.md": {"optional": True, "max_chars": 20000}},
        required_inputs=["01_meta.json", "02_classification.json"],
        note="환경 변화 사건 조사. 새 사건은 kb/events/<domain>/ 에도 복사"),
    StageSpec(
        name="impact", prompt_file="03_impact.md",
        inputs=["03_argument_chains.json", "L0/events.json", "00_source/<id>.md"],
        outputs=["L0/provisional_verdicts.json", "comparison_table.json"],
        schema="comparison_row", tools=["read_report_file"],
        validations=[("comparison_table.json", "comparison_row", "conclusion_rows[],body_rows[]")],
        input_rules={"00_source/<id>.md": {"max_chars": 40000}},
        required_inputs=["03_argument_chains.json", "L0/events.json"],
        note="영향 전파·잠정 판정. v0 사본을 L0/comparison_table_v0.json 으로"),
    StageSpec(
        name="verify_forecast", prompt_file="04_forecast_verify.md",
        inputs=["03_argument_chains.json", "L0/events.json", "L0/provisional_verdicts.json"],
        outputs=["L1/verdicts.json", "L2/traced/traced_conclusions.json"],
        schema="verdict", tools=["web_search", "fetch_page", "evidence_search", "read_report_file"],
        validations=[("L1/verdicts.json", "verdict", "[]")],
        required_inputs=["03_argument_chains.json"],
        types=["F", "B", "G"],
        guidance=("이 단계는 **전망·예측형(F)·사례 동향형(B)·기관 전략형(G)** 결론과 그에 딸린 claim 만 다룬다. "
                  "경제성·계량(M)·설문(S)·기술 실험(T)·정책 제언(P) 결론은 다른 단계가 맡으므로 손대지 않는다. "
                  "B 는 사례별 현재 상태 추적(case_refresh), G 는 실행 여부·KPI 달성도 추적(kpi_track)으로 같은 verdicts 형식에 적는다. "
                  "해당 유형의 결론이 하나도 없으면 `L1/verdicts.json` 과 `L2/traced/traced_conclusions.json` 을 모두 "
                  "빈 배열 `[]` 로 내고 정상 종료한다."),
        note="전망 검증(L1) + 추적 재도출(L2 트랙 A). B·G 의 사례·KPI 추적을 포함한다"),
    StageSpec(
        name="verify_model", prompt_file="04a_model.md",
        inputs=["03_argument_chains.json", "L0/events.json", "L0/provisional_verdicts.json"],
        outputs=["L1/model_rerun.json"],
        schema="verdict", tools=["web_search", "fetch_page", "evidence_search", "read_report_file"],
        validations=[("L1/verdicts.json", "verdict", "[]")],
        optional_outputs=["L2/traced/traced_conclusions.json", "L1/verdicts.json"],
        required_inputs=["03_argument_chains.json"],
        types=["M"],
        merge_keys={"L1/verdicts.json": "claim_id", "L2/traced/traced_conclusions.json": "conclusion_id"},
        note="모형 재계산(M): 수식·가정 복원 → 입력 갱신 → 재계산 → 민감도"),
    StageSpec(
        name="verify_policy", prompt_file="04_forecast_verify.md",
        inputs=["03_argument_chains.json", "L0/events.json", "L0/provisional_verdicts.json"],
        outputs=["L1/policy_tracking.md"],
        schema="verdict", tools=["web_search", "fetch_page", "evidence_search", "read_report_file"],
        validations=[("L1/verdicts.json", "verdict", "[]")],
        optional_outputs=["L1/verdicts.json"],
        required_inputs=["03_argument_chains.json"],
        types=["P"],
        merge_keys={"L1/verdicts.json": "claim_id"},
        guidance=("이 단계는 **정책·제도 대안형(P) 결론과 제언(kind R)** 만 다룬다. 전망(F)·모형(M)·설문(S)·실험(T) 결론은 "
                  "다른 단계가 맡으므로 손대지 않는다. 위 역할 지시서의 verdicts 형식을 그대로 쓰되, '전망 대비 실적' 자리에 "
                  "제언의 진행 단계를 넣는다: `current_value.value` 에 「채택 / 입법·고시 / 시행 / 결과(지표 변화) / 폐기·대체」 중 "
                  "어디까지 왔는지를 단계명으로, `note` 에 근거 문서명·날짜를 적는다. verdict 어휘의 뜻을 고정한다 — "
                  "유효(채택·시행 중) / 수정필요(부분 채택·형태 변경) / 폐기(철회·반대 정책) / 검증불가(추적 근거 없음). "
                  "채택됐다는 사실만으로 결론을 '강화'하지 않는다(결과 지표가 확인될 때만). 근거는 법제처(law.go.kr)·"
                  "열린국회정보·부처 고시·보도자료를 A 등급으로 두고, 언론만 있으면 B 등급으로 2건 이상 교차확인한다. "
                  "`L1/policy_tracking.md` 는 「제언 | 단계 | 근거 | 등급 | 연결 K-ID」 표로 쓴다. "
                  "해당 유형의 결론이 하나도 없으면 `L1/verdicts.json` 은 빈 배열 `[]`, `L1/policy_tracking.md` 는 "
                  "'대상 결론 없음' 한 줄로 내고 정상 종료한다. 추적 재도출(traced_conclusions)은 이 단계에서 만들지 않는다."),
        note="정책 추적(P·제언): 채택·입법·시행·폐기 단계 추적"),
    StageSpec(
        name="design_survey", prompt_file="04b_survey.md",
        inputs=["03_argument_chains.json", "L0/events.json", "L0/provisional_verdicts.json", "templates/survey_redesign.md"],
        outputs=["L3/survey_index.json"],
        schema="verdict", tools=["web_search", "fetch_page", "evidence_search", "read_report_file", "read_core_file"],
        validations=[("L1/verdicts.json", "verdict", "[]")],
        optional_outputs=["L1/verdicts.json"],
        input_rules={"templates/survey_redesign.md": {"optional": True}},
        required_inputs=["03_argument_chains.json"],
        types=["S"],
        merge_keys={"L1/verdicts.json": "claim_id"},
        allow_files="설계서가 필요한 결론마다 \"L3/survey_redesign_<K-ID>.md\": \"(마크다운 전문)\"",
        note="재설문 설계(S): 공식조사 대체 확인 → 불가하면 L3/survey_redesign_<K-ID>.md (files 키로)"),
    StageSpec(
        name="design_experiment", prompt_file="04c_experiment.md",
        inputs=["03_argument_chains.json", "L0/events.json", "L0/provisional_verdicts.json", "templates/experiment_plan.md"],
        outputs=["L3/experiment_index.json"],
        schema="verdict", tools=["web_search", "fetch_page", "evidence_search", "read_report_file", "read_core_file"],
        validations=[("L1/verdicts.json", "verdict", "[]")],
        optional_outputs=["L1/verdicts.json"],
        input_rules={"templates/experiment_plan.md": {"optional": True}},
        required_inputs=["03_argument_chains.json"],
        types=["T"],
        merge_keys={"L1/verdicts.json": "claim_id"},
        allow_files="계획서가 필요한 결론마다 \"L3/experiment_plan_<K-ID>.md\": \"(마크다운 전문)\"",
        note="재실험 계획(T): 표준·규격 추적 → 필요하면 L3/experiment_plan_<K-ID>.md (files 키로)"),
    StageSpec(
        name="brief", prompt_file="05a_brief.md",
        inputs=["02_classification.json", "03_argument_chains.json"], outputs=["L2/blind_input/brief.md"],
        schema=None, tools=[], model_role="cheap",
        input_rules={"03_argument_chains.json": {"transform": "conclusions_only"}},
        optional_outputs=["L2/compare/question_map.json"],
        required_inputs=["02_classification.json", "03_argument_chains.json"],
        note="블라인드 브리프. 원 결론·수치 제거. 질문 대응표는 L2/compare/question_map.json(블라인드에 주지 않음)"),
    StageSpec(
        name="blind", prompt_file="05_blind.md",
        inputs=["L2/blind_input/brief.md"], outputs=["L2/blind_output/blind_conclusions.json"],
        schema=None, tools=["web_search", "fetch_page", "evidence_search"], isolated=True,
        required_inputs=["L2/blind_input/brief.md"],
        note="격리: 브리프 외 어떤 보고서 내용도 대화에 넣지 않고 파일 읽기 도구 없음. files_opened 강제 기록"),
    StageSpec(
        name="compare", prompt_file="06_compare.md",
        inputs=["03_argument_chains.json", "L2/traced/traced_conclusions.json", "L2/blind_output/blind_conclusions*.json",
                "L1/verdicts.json", "L0/provisional_verdicts.json", "comparison_table.json", "templates/verdict_rules.yaml"],
        outputs=["comparison_table.json", "L2/compare/verdict_notes.md"],
        schema="comparison_row", tools=["read_report_file"],
        validations=[("comparison_table.json", "comparison_row", "conclusion_rows[],body_rows[]")],
        input_rules={"L2/traced/traced_conclusions.json": {"optional": True},
                     "L2/blind_output/blind_conclusions*.json": {"optional": True},
                     "L1/verdicts.json": {"optional": True}, "templates/verdict_rules.yaml": {"optional": True}},
        required_inputs=["03_argument_chains.json", "comparison_table.json"],
        note="최종 판정. old 문장은 v0 와 같아야 한다(러너가 복원)"),
    StageSpec(
        name="report", prompt_file=None, inputs=[],
        outputs=["07_report/comparison_table.html", "07_report/report.md", "07_report/report.html"],
        schema=None, tools=[], python="render",
        note="scripts.render_table.main, scripts.render_report.main, registry.set_maturity"),
    StageSpec(
        name="critic", prompt_file="08_critic.md",
        inputs=["comparison_table.json", "07_report/report.md", "L2/blind_output/blind_conclusions.json"],
        outputs=["07_report/critic_notes.md"],
        schema=None, tools=["read_report_file"],
        input_rules={"07_report/report.md": {"max_chars": 60000},
                     "L2/blind_output/blind_conclusions.json": {"optional": True}},
        required_inputs=["comparison_table.json"],
        note="읽기 전용 검토"),
]

_BY_NAME = {s.name: s for s in STAGES}


def get_stage(name: str) -> StageSpec:
    """이름으로 단계를 찾는다. blind_2 처럼 반복 접미사가 붙은 이름과 옛 이름(verify)도 받는다."""
    if name in _BY_NAME:
        return _BY_NAME[name]
    if name in ALIASES:
        return _BY_NAME[ALIASES[name]]
    base = name.split("_")[0]
    if base in _BY_NAME:
        return _BY_NAME[base]
    raise KeyError(f"알 수 없는 단계: {name}")


def base_name(name: str) -> str:
    """STAGE_ORDER 에서 찾을 수 있는 이름으로 바꾼다(blind_2 → blind, verify → verify_forecast)."""
    if name in STAGE_ORDER:
        return name
    if name in ALIASES:
        return ALIASES[name]
    base = name.split("_")[0]
    return base if base in STAGE_ORDER else name


def stage_names() -> list:
    return list(STAGE_ORDER)


def report_types(report_id: Optional[str]) -> Optional[set]:
    """reports/<id>/03_argument_chains.json 의 모든 결론 types 를 모은 집합.

    파일이 없거나 읽을 수 없으면 None(= 유형을 모름 → 유형별 단계를 모두 넣는다).
    """
    if not report_id:
        return None
    import json
    import config  # 지연 import (engine 단독 import 시 순환을 피한다)
    try:
        path = config.report_dir(report_id) / "03_argument_chains.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    found = set()
    for c in data.get("conclusions") or []:
        if not isinstance(c, dict):
            continue
        for t in c.get("types") or []:
            if isinstance(t, str) and t.strip():
                found.add(t.strip())
    return found


def blind_repeat(spec: StageSpec, k: int) -> StageSpec:
    """블라인드 반복 k(2 이상)번째 사본. 출력 파일명에 _k 를 붙인다."""
    out = [o.replace("blind_conclusions.json", f"blind_conclusions_{k}.json") for o in spec.outputs]
    return replace(spec, name=f"blind_{k}", outputs=out)


def stages_for(run_config: dict, report_id: Optional[str] = None) -> list:
    """run_config.layers·options 와 보고서의 결론 유형에 따라 실행할 단계 목록을 순서대로 돌려준다.

    - intake 는 항상 맨 앞(산출물이 있으면 러너가 건너뛴다).
    - layers 에 없는 층은 건너뛴다. options.blind_rerun.enabled=false 면 brief·blind 생략.
    - L1 의 유형별 단계(verify_forecast·verify_model·verify_policy·design_survey·design_experiment)는
      `reports/<id>/03_argument_chains.json` 의 결론 types 에 해당 유형이 있을 때만 넣는다.
      chains 파일이 아직 없으면(첫 실행) 전부 넣는다 — 대상이 없으면 각 프롬프트의 "빈 출력" 규칙이 처리한다.
    - options.survey_redesign / experiment_plan 이 false 면 design_* 단계를 건너뛴다.
    - blind_rerun.repeats(1~5) 만큼 blind 사본을 만든다.
    - report·critic 은 항상 마지막.
    """
    layers = set(run_config.get("layers") or ["L0", "L1", "L2"])
    options = run_config.get("options") or {}
    blind_opt = options.get("blind_rerun") or {}
    blind_enabled = bool(blind_opt.get("enabled", True))
    repeats = int(blind_opt.get("repeats") or 1)
    repeats = max(1, min(repeats, 5))
    rid = report_id or run_config.get("report_id")
    types = report_types(rid)
    out = []
    for spec in STAGES:
        if spec.name in ("intake", "report", "critic"):
            out.append(spec)
            continue
        if spec.layer not in layers:
            continue
        if spec.name in ("brief", "blind") and not blind_enabled:
            continue
        opt = OPTION_OF.get(spec.name)
        if opt and not bool(options.get(opt, True)):
            continue
        if spec.name in TYPED_STAGES and types is not None and not (set(spec.types) & types):
            continue
        out.append(spec)
        if spec.name == "blind":
            for k in range(2, repeats + 1):
                out.append(blind_repeat(spec, k))
    # report·critic 을 맨 뒤로
    tail = [s for s in out if s.name in ("report", "critic")]
    head = [s for s in out if s.name not in ("report", "critic")]
    return head + tail
