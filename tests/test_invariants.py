"""불변식 테스트 — 이 하네스가 절대 깨지면 안 되는 규칙을 실제 산출물에 대해 매번 검사한다.

`reports/<ID>/comparison_table.json` 이 있는 보고서를 모두 찾아 돌린다. 하나도 없으면 전부 skip한다.
개별 파일(events.json 등)이 없는 보고서는 그 항목만 skip한다.

검사 항목
  1) 스키마       03_argument_chains.json(chain) · L0/events.json(event) · L1/verdicts.json(verdict) ·
                  comparison_table.json 의 conclusion_rows·body_rows(comparison_row)
  2) 블라인드 격리 L2/blind_output/blind_conclusions.json 마지막 원소의 files_opened 가
                  지시서와 브리프 두 경로만 담고 있는가(원문·사슬·대조표가 섞이면 실패)
  3) 브리프 무오염 L2/blind_input/brief.md 에 원 결론의 수치가 새지 않았는가
  4) 원문 불변     comparison_table.json 의 old 문장이 03_argument_chains.json 의 원 결론에서만 나왔는가
  5) 근거 필수     판정(verdict)이 있는 행에는 근거가 1건 이상이고 등급이 A/B/C 인가
  6) 등급 규칙     행 등급이 A면 근거 중 최소 1건이 A인가

=========================== 허용 예외 (문서화된 것만) ===========================
새 예외를 넣을 때는 반드시 이유와 후속 조치를 여기에 함께 적는다.

[E1] 브리프 무오염 — 연도(19xx·20xx 네 자리)와 백분율(`%`·`퍼센트`가 바로 붙은 수)은 수치 유출로
     보지 않는다. 브리프는 기준 시점과 예측 연도를 밝혀야 하고, 비율 표기는 방법의 구조를 설명하는
     말이지 원 결론의 값이 아니기 때문이다. 그밖에 세 자리 이상 숫자가 브리프에 있으면 실패한다.

[E2] 원문 불변 — `old` 는 원 결론의 "요지"이지 글자 그대로의 인용이 아니다(대조표 HTML 각주도
     "현행 열은 원문 요지"라고 밝힌다). 그래서 ① 공백을 지운 뒤 원 결론 문장과 같거나 그 부분문자열이면
     바로 통과시키고, ② 아니면 수치 추적으로 검사한다 — `old` 안의 모든 수(세 자리 미만 포함)가 해당
     결론의 원문(statement·method·그 결론에 달린 claims)에도 있어야 한다. 즉 요약은 허용하되
     원문에 없는 숫자를 지어 넣는 것은 막는다. 요약하면서 생긴 집계 숫자만 아래 표에 예외로 둔다.

[E3] (해소됨 2026-09-18) chain 스키마의 edges.relation enum 이 실제 사슬 추출 어휘를 담지
     못해 R01 의 89개 간선 중 47개가 규격 위반이었다. `chain.schema.json` 의 enum 을 실제
     어휘(premise_of·evidence_for·input_to·answers·baseline_of·motivates·supports·cites,
     evidence_of 는 옛 이름 호환)로 넓히고 `prompts/01_chains.md` 에 어휘표를 명시해 해소했다.
     예외 없이 chain 스키마 전체를 검사한다.
=============================================================================
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.validate import validate_obj

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"

# 신규결론 행의 old 는 원 연구에 대응 문장이 없다는 표시만 담는다.
NEW_CONCLUSION_OLD = "(원 연구에 없음)"

# 블라인드 에이전트가 열어도 되는 파일 두 개(경로 끝으로 비교한다).
BLIND_ALLOWED_SUFFIXES = ("prompts/05_blind.md", "L2/blind_input/brief.md")

# 열렸다면 격리가 깨진 것으로 보는 조각들.
BLIND_FORBIDDEN_MARKERS = (
    "00_source", "01_meta", "02_classification", "03_argument_chains",
    "comparison_table", "L0/", "L1/", "L2/traced", "L2/compare", "07_report",
)


# [E2] 원문 불변에서 예외로 두는 수. (보고서 ID, 행 ID) -> {수: 이유}
OLD_NUMBER_EXEMPTIONS: dict[tuple[str, str], dict[str, str]] = {
    ("R01", "K-F-01"): {"19": "원 결론 문장이 열거한 사업자 19곳을 요약하며 센 값(원문에 목록만 있고 합계 표기가 없다)"},
}

GRADES = {"A", "B", "C"}

_NUM = re.compile(r"[0-9][0-9,.]*")
# 브리프 검사용: 앞에 숫자가 없는 자리에서 시작하는 수 + 바로 뒤의 백분율 표기
_BRIEF_NUM = re.compile(r"(?<![0-9])([0-9][0-9,.]*)\s*(%|퍼센트)?")
_YEAR = re.compile(r"(?:19|20)[0-9]{2}")


# ---------------------------------------------------------------- 대상 보고서 찾기

def _discover_report_ids() -> list[str]:
    if not REPORTS_DIR.is_dir():
        return []
    return sorted(d.name for d in REPORTS_DIR.iterdir()
                  if d.is_dir() and (d / "comparison_table.json").is_file())


REPORT_IDS = _discover_report_ids()

# 산출물이 하나도 없으면 파라미터 하나를 skip 표시로 넣어 "조용히 0건"이 되지 않게 한다.
REPORT_PARAMS = REPORT_IDS or [
    pytest.param("(없음)", marks=pytest.mark.skip(reason="reports/ 아래 산출물이 있는 보고서가 없다"))
]

pytestmark = pytest.mark.parametrize("rid", REPORT_PARAMS)


# ---------------------------------------------------------------- 공통 도우미

def _load(rid: str, *parts: str):
    """보고서 서랍의 JSON 을 읽는다. 없으면 그 검사만 skip."""
    p = REPORTS_DIR.joinpath(rid, *parts)
    if not p.is_file():
        pytest.skip(f"{rid}: {'/'.join(parts)} 없음")
    return json.loads(p.read_text(encoding="utf-8"))


def _read_text(rid: str, *parts: str) -> str:
    p = REPORTS_DIR.joinpath(rid, *parts)
    if not p.is_file():
        pytest.skip(f"{rid}: {'/'.join(parts)} 없음")
    return p.read_text(encoding="utf-8")


def _all_rows(table: dict) -> list[dict]:
    return list(table.get("conclusion_rows") or []) + list(table.get("body_rows") or [])


def _numbers(text: str) -> set[str]:
    """문장에서 수를 뽑아 자릿점을 지운 형태로 모은다. 1,020 과 1020 을 같은 값으로 본다."""
    out = set()
    for m in _NUM.finditer(text):
        tok = m.group(0).rstrip(".").replace(",", "")
        if tok:
            out.add(tok)
    return out


# ---------------------------------------------------------------- 1) 스키마

def test_chain_matches_schema(rid):
    chain = _load(rid, "03_argument_chains.json")
    errs = validate_obj(chain, "chain")  # [E3] 해소: 예외 없이 전체 검사
    assert errs == [], f"{rid}: 논증 사슬이 chain 스키마를 벗어났다 — {errs[:5]}"


def test_events_match_schema(rid):
    events = _load(rid, "L0", "events.json")
    assert isinstance(events, list) and events, f"{rid}: events.json 은 비어 있지 않은 배열이어야 한다"
    errs = [(i, e) for i, obj in enumerate(events, 1) for e in validate_obj(obj, "event")]
    assert errs == [], f"{rid}: 사건이 event 스키마를 벗어났다 — {errs[:5]}"


def test_l1_verdicts_match_schema(rid):
    verdicts = _load(rid, "L1", "verdicts.json")
    assert isinstance(verdicts, list) and verdicts, f"{rid}: verdicts.json 은 비어 있지 않은 배열이어야 한다"
    errs = [(i, e) for i, obj in enumerate(verdicts, 1) for e in validate_obj(obj, "verdict")]
    assert errs == [], f"{rid}: 근거 판정이 verdict 스키마를 벗어났다 — {errs[:5]}"


def test_comparison_rows_match_schema(rid):
    table = _load(rid, "comparison_table.json")
    rows = _all_rows(table)
    assert rows, f"{rid}: 대조표에 행이 하나도 없다"
    errs = [(r.get("row_id"), e) for r in rows for e in validate_obj(r, "comparison_row")]
    assert errs == [], f"{rid}: 대조표 행이 comparison_row 스키마를 벗어났다 — {errs[:5]}"


# ---------------------------------------------------------------- 2) 블라인드 격리

def test_blind_output_stayed_isolated(rid):
    blind = _load(rid, "L2", "blind_output", "blind_conclusions.json")
    assert isinstance(blind, list) and blind, f"{rid}: blind_conclusions.json 은 비어 있지 않은 배열이어야 한다"

    opened = blind[-1].get("files_opened") if isinstance(blind[-1], dict) else None
    assert isinstance(opened, list) and opened, (
        f"{rid}: 블라인드 산출물 마지막 원소에 files_opened 가 없다. 격리를 확인할 수 없으므로 실패로 본다"
    )

    normalized = [str(p).replace("\\", "/").lstrip("./") for p in opened]
    off_limits = [p for p in normalized if not p.endswith(BLIND_ALLOWED_SUFFIXES)]
    assert off_limits == [], (
        f"{rid}: 블라인드 에이전트가 허용되지 않은 파일을 열었다 — {off_limits}. "
        f"허용은 {list(BLIND_ALLOWED_SUFFIXES)} 뿐이다"
    )

    leaked = [p for p in normalized
              if any(m in p for m in BLIND_FORBIDDEN_MARKERS) and not p.endswith("L2/blind_input/brief.md")]
    assert leaked == [], f"{rid}: 블라인드 격리 위반 — 원문·중간 산출물을 열었다: {leaked}"


# ---------------------------------------------------------------- 3) 브리프 무오염

def test_blind_brief_has_no_leaked_numbers(rid):
    text = _read_text(rid, "L2", "blind_input", "brief.md")
    leaks = []
    for m in _BRIEF_NUM.finditer(text):
        token = m.group(1).rstrip(".")
        digits = token.replace(",", "").replace(".", "")
        if len(digits) < 3:
            continue
        if m.group(2):          # [E1] 백분율 표기
            continue
        if _YEAR.fullmatch(token):   # [E1] 연도
            continue
        around = text[max(0, m.start() - 30):m.end() + 20].replace("\n", " ")
        leaks.append((token, around))
    assert leaks == [], (
        f"{rid}: 블라인드 브리프에 원 결론의 수치가 샜을 수 있다(연도·백분율 제외, 세 자리 이상) — {leaks[:5]}"
    )


# ---------------------------------------------------------------- 4) 원문 불변

def test_old_column_comes_from_original(rid):
    table = _load(rid, "comparison_table.json")
    chain = _load(rid, "03_argument_chains.json")

    by_id = {c["conclusion_id"]: c for c in chain.get("conclusions", [])}
    claims_by_conclusion: dict[str, list[str]] = {}
    for cl in chain.get("claims", []):
        claims_by_conclusion.setdefault(cl.get("conclusion_id"), []).append(
            json.dumps(cl, ensure_ascii=False))

    problems = []
    for row in table.get("conclusion_rows") or []:
        rid_row, cid = row.get("row_id", ""), row.get("conclusion_id")
        old = (row.get("old") or "").strip()

        if cid not in by_id:
            # 원 연구에 대응 결론이 없는 행 = 신규결론. old 는 표시 문구여야 한다.
            if old != NEW_CONCLUSION_OLD:
                problems.append((rid_row, f"원 결론에 없는 행인데 old 가 '{NEW_CONCLUSION_OLD}' 가 아니다: {old[:40]}"))
            continue
        if old == NEW_CONCLUSION_OLD:
            problems.append((rid_row, f"원 결론 {cid} 이 있는데 old 가 신규결론 표시로 비어 있다"))
            continue

        conclusion = by_id[cid]
        statement = conclusion.get("statement", "")
        if re.sub(r"\s+", "", old) in re.sub(r"\s+", "", statement):
            continue  # 원문 그대로 인용한 경우

        # [E2] 요지로 줄인 경우: old 의 모든 수가 원문에 있어야 한다.
        source_text = " ".join([statement, conclusion.get("method", "")]
                               + claims_by_conclusion.get(cid, []))
        allowed = set(OLD_NUMBER_EXEMPTIONS.get((rid, rid_row), {}))
        invented = sorted(_numbers(old) - _numbers(source_text) - allowed)
        if invented:
            problems.append((rid_row, f"원문({cid})에 없는 수가 old 에 있다: {invented}"))

    assert problems == [], f"{rid}: 원 결론 문장(old)이 원문에서 벗어났다 — {problems}"


# ---------------------------------------------------------------- 5) 근거 필수

def test_rows_with_verdict_have_graded_evidence(rid):
    table = _load(rid, "comparison_table.json")
    missing, bad_grade = [], []
    for row in _all_rows(table):
        evidence = row.get("evidence") or []
        if (row.get("verdict") or "").strip() and not evidence:
            missing.append(row.get("row_id"))
        for ev in evidence:
            if ev.get("grade") not in GRADES:
                bad_grade.append((row.get("row_id"), ev.get("grade")))
    assert missing == [], f"{rid}: 판정이 있는데 근거가 없는 행 — {missing}"
    assert bad_grade == [], f"{rid}: 근거 등급이 A/B/C 가 아닌 행 — {bad_grade}"


# ---------------------------------------------------------------- 6) 등급 규칙

def test_grade_a_rows_need_an_a_evidence(rid):
    table = _load(rid, "comparison_table.json")
    offenders = []
    for row in _all_rows(table):
        if row.get("grade") != "A":
            continue
        grades = [ev.get("grade") for ev in (row.get("evidence") or [])]
        if "A" not in grades:
            offenders.append((row.get("row_id"), grades))
    assert offenders == [], f"{rid}: 등급 A 행인데 A등급 근거가 하나도 없다 — {offenders}"
