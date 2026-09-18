"""회귀 테스트 — 샘플 R01 의 산출물이 의도치 않게 바뀌지 않았는지 고정한다.

R01 은 배포판에 함께 실리는 유일한 완성 샘플이고, README·설명서·발표자료가 이 숫자를 그대로 인용한다.
그래서 값이 조용히 달라지면 문서와 산출물이 어긋난다. 아래 기준값이 그 잠금장치다.

────────────────────────── 기준값을 갱신하는 방법 ──────────────────────────
R01 을 다시 돌려서 값이 달라졌고 **그 변화가 정당할 때만** 아래 상수를 고친다.
  1) `python scripts/validate.py reports/R01/comparison_table.json --schema comparison_row` 등으로
     새 산출물이 스키마를 통과하는지 먼저 확인한다(`python -m pytest tests/test_invariants.py` 로 갈음 가능).
  2) 아래 명령으로 새 값을 뽑아 상수에 그대로 옮긴다.
       python -c "import json;d=json.load(open('reports/R01/comparison_table.json',encoding='utf-8'));\
print(len(d['conclusion_rows']),len(d['body_rows']),d['maturity'],d['summary'])"
       python -c "import json;print(len(json.load(open('reports/R01/L0/events.json',encoding='utf-8'))),\
len(json.load(open('reports/R01/L1/verdicts.json',encoding='utf-8'))))"
  3) 같은 숫자를 쓰는 문서(README.md, docs/설명서_구성과_기술스펙.md)도 함께 고친다.
  4) 변경 사유를 커밋 메시지에 남긴다. 기준값만 슬쩍 맞추는 커밋은 회귀 테스트를 무력화한다.
─────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
R01 = ROOT / "reports" / "R01"

# ── 기준값 (2026-09-15 생성분) ──────────────────────────────────────────────
EXPECTED_CONCLUSION_ROWS = 16          # 원 결론 12 + 신규결론 4
EXPECTED_BODY_ROWS = 8                 # 본문(환경분석·현황 절) 대조 행
EXPECTED_VERDICTS = {                  # 결론 행의 최종 판정 분포
    "동일": 2,
    "부분수정": 5,
    "약화": 2,
    "신규결론": 4,
    "판정불가": 2,
    "잠정": 1,
}
EXPECTED_EVENTS = 15                   # L0/events.json — 발간 이후 사건
EXPECTED_L1_VERDICTS = 22              # L1/verdicts.json — 근거 단위 판정
EXPECTED_MATURITY = "L2(부분)"
EXPECTED_TITLE = "디지털전환에 따른 5G 모바일 시장전망 및 주파수 경제성 분석"
EXPECTED_PUBLISHED = "2023-04"

# 렌더된 HTML 에 들어 있어야 하는 판정 배지. 배지 클래스가 바뀌면 화면 색이 바뀐 것이므로 회귀로 본다.
EXPECTED_BADGES = (
    '<span class="pill p-good">동일</span>',
    '<span class="pill p-warn">부분수정</span>',
    '<span class="pill p-warn">약화</span>',
    '<span class="pill p-new">신규결론</span>',
    '<span class="pill p-na">판정불가</span>',
    '<span class="pill p-na">잠정</span>',
)
# ──────────────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.skipif(
    not (R01 / "comparison_table.json").is_file(), reason="샘플 R01 산출물이 없다")


def _json(*parts: str):
    return json.loads(R01.joinpath(*parts).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 산출물 고정

def test_comparison_table_shape_is_fixed():
    table = _json("comparison_table.json")
    assert table["report_id"] == "R01"
    assert table["title"] == EXPECTED_TITLE
    assert table["published"] == EXPECTED_PUBLISHED
    assert table["maturity"] == EXPECTED_MATURITY
    assert len(table["conclusion_rows"]) == EXPECTED_CONCLUSION_ROWS
    assert len(table["body_rows"]) == EXPECTED_BODY_ROWS


def test_verdict_distribution_is_fixed():
    table = _json("comparison_table.json")
    counts: dict[str, int] = {}
    for row in table["conclusion_rows"]:
        counts[row.get("verdict") or ""] = counts.get(row.get("verdict") or "", 0) + 1
    assert counts == EXPECTED_VERDICTS
    # summary 블록(문서·화면이 그대로 읽는 값)도 같은 분포여야 한다.
    summary = {k: v for k, v in table["summary"].items() if v}
    assert summary == EXPECTED_VERDICTS


def test_event_and_verdict_counts_are_fixed():
    assert len(_json("L0", "events.json")) == EXPECTED_EVENTS
    assert len(_json("L1", "verdicts.json")) == EXPECTED_L1_VERDICTS


# ---------------------------------------------------------------- 렌더 회귀

def _render_sandbox(tmp_path: Path) -> Path:
    """scripts/ 와 reports/R01/ 만 복사한 임시 프로젝트. 저장소의 산출물을 건드리지 않는다
    (render_report.py 는 렌더 시각을 파일에 적으므로 저장소에서 돌리면 작업 트리가 더러워진다)."""
    sandbox = tmp_path / "proj"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "scripts", sandbox / "scripts", ignore=ignore)
    shutil.copytree(R01, sandbox / "reports" / "R01", ignore=ignore)
    shutil.rmtree(sandbox / "reports" / "R01" / "07_report", ignore_errors=True)
    return sandbox


def _run(sandbox: Path, script: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(sandbox))
    return subprocess.run([sys.executable, str(sandbox / "scripts" / script), "R01"],
                          cwd=sandbox, env=env, capture_output=True, text=True, encoding="utf-8")


def test_render_table_cli_produces_badged_html(tmp_path):
    sandbox = _render_sandbox(tmp_path)
    proc = _run(sandbox, "render_table.py")
    assert proc.returncode == 0, f"render_table.py 실패: {proc.stderr}"

    out = sandbox / "reports" / "R01" / "07_report" / "comparison_table.html"
    assert out.is_file(), "comparison_table.html 이 생성되지 않았다"
    html_text = out.read_text(encoding="utf-8")
    missing = [b for b in EXPECTED_BADGES if b not in html_text]
    assert missing == [], f"대조표 HTML 에 판정 배지가 없다 — {missing}"
    assert EXPECTED_TITLE in html_text and EXPECTED_MATURITY in html_text
    # 요약 배지(판정 n건)도 그대로 실려야 한다.
    for verdict, count in EXPECTED_VERDICTS.items():
        assert f">{verdict} {count}</span>" in html_text, f"요약 배지 누락: {verdict} {count}"


def test_render_report_cli_produces_md_and_html(tmp_path):
    sandbox = _render_sandbox(tmp_path)
    proc = _run(sandbox, "render_report.py")
    assert proc.returncode == 0, f"render_report.py 실패: {proc.stderr}"

    out_dir = sandbox / "reports" / "R01" / "07_report"
    md_text = (out_dir / "report.md").read_text(encoding="utf-8")
    html_text = (out_dir / "report.html").read_text(encoding="utf-8")

    assert "(아직 생성되지 않음" not in md_text, "R01 은 모든 입력이 있으므로 미생성 표시가 없어야 한다"
    assert EXPECTED_MATURITY in md_text and EXPECTED_MATURITY in html_text
    missing = [b for b in EXPECTED_BADGES if b not in html_text]
    assert missing == [], f"현행화 보고서 HTML 에 판정 배지가 없다 — {missing}"
    for verdict, count in EXPECTED_VERDICTS.items():
        assert f"| {verdict} | {count} |" in md_text, f"요약 표 누락: {verdict} {count}"
