"""단계 정의. DESIGN.md 4절 표를 그대로 코드로 옮긴다.

- inputs 는 reports/<id>/ 기준 상대경로. `kb/`·`templates/` 로 시작하면 공통 핵심(CORE_DIR) 기준.
  `<id>`·`<domain>` 자리표시자는 실행 시 치환되고, `*` 가 있으면 glob 로 여러 파일을 인라인한다.
- outputs 는 모델이 최종 JSON 응답에서 키로 돌려줘야 하는 파일 경로.
- validations 는 (출력 경로, 스키마 이름, 선택자) 목록. 선택자 "" 는 객체 전체, "[]" 는 배열 원소,
  "conclusion_rows[],body_rows[]" 처럼 쓰면 그 키의 배열 원소를 검증한다.
- input_rules 는 입력 인라인 규칙: max_chars(글자 수 상한), transform(특수 추림), optional(없어도 됨).
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Optional

# 층 매핑(DESIGN 4절): L0 = classify·chains·delta·impact, L1 = verify, L2 = brief·blind·compare, 마지막에 report·critic
LAYER_OF = {
    "intake": None, "classify": "L0", "chains": "L0", "delta": "L0", "impact": "L0",
    "verify": "L1", "brief": "L2", "blind": "L2", "compare": "L2", "report": None, "critic": None,
}
STAGE_ORDER = ["intake", "classify", "chains", "delta", "impact", "verify", "brief", "blind", "compare", "report", "critic"]


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

    @property
    def layer(self) -> Optional[str]:
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
        name="verify", prompt_file="04_forecast_verify.md",
        inputs=["03_argument_chains.json", "L0/events.json", "L0/provisional_verdicts.json"],
        outputs=["L1/verdicts.json", "L2/traced/traced_conclusions.json"],
        schema="verdict", tools=["web_search", "fetch_page", "evidence_search", "read_report_file"],
        validations=[("L1/verdicts.json", "verdict", "[]")],
        required_inputs=["03_argument_chains.json"],
        note="전망 검증(L1) + 추적 재도출(L2 트랙 A)"),
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
    """이름으로 단계를 찾는다. blind_2 처럼 반복 접미사가 붙은 이름도 받는다."""
    if name in _BY_NAME:
        return _BY_NAME[name]
    base = name.split("_")[0]
    if base in _BY_NAME:
        return _BY_NAME[base]
    raise KeyError(f"알 수 없는 단계: {name}")


def stage_names() -> list:
    return list(STAGE_ORDER)


def blind_repeat(spec: StageSpec, k: int) -> StageSpec:
    """블라인드 반복 k(2 이상)번째 사본. 출력 파일명에 _k 를 붙인다."""
    out = [o.replace("blind_conclusions.json", f"blind_conclusions_{k}.json") for o in spec.outputs]
    return replace(spec, name=f"blind_{k}", outputs=out)


def stages_for(run_config: dict) -> list:
    """run_config.layers 와 options 에 따라 실행할 단계 목록을 순서대로 돌려준다.

    - intake 는 항상 맨 앞(산출물이 있으면 러너가 건너뛴다).
    - layers 에 없는 층은 건너뛴다. options.blind_rerun.enabled=false 면 brief·blind 생략.
    - blind_rerun.repeats(1~5) 만큼 blind 사본을 만든다.
    - report·critic 은 항상 마지막.
    """
    layers = set(run_config.get("layers") or ["L0", "L1", "L2"])
    options = run_config.get("options") or {}
    blind_opt = options.get("blind_rerun") or {}
    blind_enabled = bool(blind_opt.get("enabled", True))
    repeats = int(blind_opt.get("repeats") or 1)
    repeats = max(1, min(repeats, 5))
    out = []
    for spec in STAGES:
        if spec.name in ("intake", "report", "critic"):
            out.append(spec)
            continue
        if spec.layer not in layers:
            continue
        if spec.name in ("brief", "blind") and not blind_enabled:
            continue
        out.append(spec)
        if spec.name == "blind":
            for k in range(2, repeats + 1):
                out.append(blind_repeat(spec, k))
    # report·critic 을 맨 뒤로
    tail = [s for s in out if s.name in ("report", "critic")]
    head = [s for s in out if s.name not in ("report", "critic")]
    return head + tail
