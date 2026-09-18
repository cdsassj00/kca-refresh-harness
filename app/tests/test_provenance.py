"""engine.provenance 테스트 — 실행 묶음의 해시 대조·변조 탐지·백테스트 오차율·환경 기록·LLM 재추적 표기.

핵심 고정점 두 가지:
- 계산 재현(결정적): 입력·코드·산출물 해시가 실제 파일과 맞아야 하고, 한 글자만 바뀌어도 잡혀야 한다.
- 판정 재추적(비결정적): LLM 기록에는 "재현되지 않는다"는 문장이 반드시 남아 재현을 약속하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
from pathlib import Path

import pytest

import config
from engine import provenance
from engine.provenance import bundled_backtest, open_bundle, verify_bundle

REPORT_ID = "R90"
SOURCES = [{"url": "https://www.kca.kr/contentsView.do?pageId=www277", "grade": "A", "asof": "2025-12",
            "note": "KCA 5G특화망 구축 현황"}]


# ---------------------------------------------------------------- 도우미
@pytest.fixture
def cleanup_report():
    """기본 위치(reports/R90/runs/)를 쓰는 테스트가 남긴 폴더를 지운다."""
    yield REPORT_ID
    shutil.rmtree(config.report_dir(REPORT_ID), ignore_errors=True)


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _filled_bundle(root, csv_text: str = "구분,공장수\n대기업,1151\n"):
    """입력(JSON·파일)·코드·중간값·산출물을 모두 담은 묶음을 만들어 (bundle, manifest) 로 돌려준다."""
    src = root / "femis_2025_10.csv"
    src.write_text(csv_text, encoding="utf-8")
    b = open_bundle(REPORT_ID, "verify_forecast", root=root)
    b.add_input("forecast.json", {"claim_id": "R01-F-019", "value": 140, "unit": "개소"},
                source_url="원 보고서 p.110(표16)", grade="C", asof="2022-12")
    b.add_input("femis_2025_10.csv", src, source_url="https://www.data.go.kr/data/3041646/fileData.do",
                grade="A", asof="2025-10")
    b.add_code("def error_pct(f, a):\n    return (f - a) / a * 100\n", name="calc.py")
    b.add_intermediate("step1_diff", {"forecast": 140, "actual": 104, "diff": 36})
    b.add_output("backtest", {"error_pct": 34.615385, "unit": "개소"})
    return b, b.close(status="ok", note="테스트용 묶음")


# ---------------------------------------------------------------- ① 해시 일치
def test_manifest_hashes_match_real_files(tmp_path):
    b, m = _filled_bundle(tmp_path)

    # manifest 파일 자체와 close() 반환값이 같다
    assert json.loads(b.manifest_path.read_text(encoding="utf-8")) == m
    assert m["bundle_id"].startswith(f"{REPORT_ID}_verify_forecast_")
    assert m["report_id"] == REPORT_ID and m["stage"] == "verify_forecast" and m["status"] == "ok"
    assert m["reproducibility"] == provenance.REPRO_DETERMINISTIC  # LLM 없음 → 계산 재현

    # 입력·코드·산출물 해시가 실제 파일과 일치
    checked = 0
    for kind in ("inputs", "code", "outputs"):
        assert m[kind], f"{kind} 가 비어 있습니다"
        for entry in m[kind]:
            p = b.dir / entry["path"]
            assert p.is_file(), f"{entry['path']} 가 없습니다"
            assert entry["sha256"] == _sha256(p)
            assert entry["bytes"] == p.stat().st_size
            checked += 1
    assert checked == 4  # 입력 2 + 코드 1 + 산출물 1
    # 중간값도 입력·코드·산출물과 같은 수준으로 해시가 남는다(변조 탐지 대상)
    assert [e["name"] for e in m["intermediate"]] == ["step1_diff.json"]
    mid = m["intermediate"][0]
    assert mid["path"] == "intermediate/step1_diff.json"
    assert len(mid["sha256"]) == 64 and mid["bytes"] > 0
    assert (b.dir / "intermediate" / "step1_diff.json").is_file()

    # 근거 메타(출처·등급·조회 시점)가 입력마다 붙는다
    femis = next(e for e in m["inputs"] if e["name"] == "femis_2025_10.csv")
    assert femis["grade"] == "A" and femis["asof"] == "2025-10"
    assert femis["source_url"].startswith("https://www.data.go.kr/")

    ok, problems = verify_bundle(b.dir)
    assert ok and problems == []
    assert m["verify_cmd"].startswith("python -m engine.provenance verify ")


def test_bundle_dir_is_under_report_runs(cleanup_report):
    """root 를 주지 않으면 reports/<id>/runs/<stage>_<시각>/ 에 만들어진다."""
    b = open_bundle(cleanup_report, "verify_forecast")
    assert b.dir.parent == config.report_dir(cleanup_report) / "runs"
    assert b.dir.name.startswith("verify_forecast_")
    assert len(b.dir.name) == len("verify_forecast_") + 15  # YYYYMMDD_HHMMSS
    b.close()
    assert b.manifest_path.is_file()


# ---------------------------------------------------------------- ② 변조 탐지
def test_verify_detects_tampering_and_missing(tmp_path):
    b, _m = _filled_bundle(tmp_path)
    assert verify_bundle(b.dir)[0] is True

    # 한 글자만 바꿔도 잡고, 어느 파일인지 알려준다
    tampered = b.dir / "inputs" / "femis_2025_10.csv"
    tampered.write_text("구분,공장수\n대기업,1152\n", encoding="utf-8")
    ok, problems = verify_bundle(b.dir)
    assert ok is False
    assert any("femis_2025_10.csv" in msg for msg in problems)
    assert any("변조" in msg or "해시" in msg for msg in problems)
    # 손대지 않은 파일은 문제 목록에 없다
    assert not any("forecast.json" in msg for msg in problems)

    # 파일이 사라져도 잡는다
    (b.dir / "outputs" / "backtest.json").unlink()
    ok2, problems2 = verify_bundle(b.dir)
    assert ok2 is False
    assert any("backtest.json" in msg and "없습니다" in msg for msg in problems2)

    # 중간값 파일이 사라져도 잡는다
    (b.dir / "intermediate" / "step1_diff.json").unlink()
    assert any("step1_diff.json" in msg for msg in verify_bundle(b.dir)[1])


def test_verify_detects_unrecorded_file_and_broken_bundle(tmp_path):
    b, _m = _filled_bundle(tmp_path)
    (b.dir / "inputs" / "몰래_끼워넣은.csv").write_text("x", encoding="utf-8")
    ok, problems = verify_bundle(b.dir)
    assert ok is False
    assert any("몰래_끼워넣은.csv" in msg for msg in problems)

    # manifest 가 없거나 폴더가 없으면 곧바로 실패
    (b.dir / "manifest.json").unlink()
    assert verify_bundle(b.dir) == (False, [f"manifest.json 이 없습니다: {b.dir}"])
    ok3, problems3 = verify_bundle(tmp_path / "없는폴더")
    assert ok3 is False and "묶음 폴더가 없습니다" in problems3[0]


def test_cli_verify_exit_code(tmp_path, capsys):
    b, _m = _filled_bundle(tmp_path)
    assert provenance.main(["verify", str(b.dir)]) == 0
    out = capsys.readouterr().out
    assert "결과: 통과" in out and "계산 재현(결정적)" in out and "femis_2025_10.csv" in out

    (b.dir / "inputs" / "forecast.json").write_text("{}", encoding="utf-8")
    assert provenance.main(["verify", str(b.dir)]) == 1
    failed_out = capsys.readouterr().out
    assert "결과: 실패" in failed_out
    assert provenance.main([]) == 2  # 사용법 안내

    # 한국어 윈도 콘솔(cp949)에서 표를 찍다가 죽지 않는다
    for text in (out, failed_out):
        text.encode("cp949")


# ---------------------------------------------------------------- ③ 백테스트 오차율
@pytest.mark.parametrize("forecast, actual, expected, direction", [
    (140, 104, 34.615385, "과대 전망"),    # 과대 전망 → 양수
    (93, 104, -10.576923, "과소 전망"),    # 과소 전망 → 음수(부호 유지)
    (104, 104, 0.0, "일치"),
    (-50, 100, -150.0, "과소 전망"),       # 음수 전망도 식 그대로
    (50, -100, -150.0, "과소 전망"),       # 실적이 음수여도 식 그대로
])
def test_bundled_backtest_error_pct(cleanup_report, forecast, actual, expected, direction):
    res = bundled_backtest(cleanup_report, "R01-F-019", forecast, actual, "개소", SOURCES,
                           code_note="KCA 2025년 말 실적 대비")
    assert res["error_pct"] == pytest.approx(expected, rel=1e-9, abs=1e-6)
    assert res["diff"] == forecast - actual
    assert res["direction"] == direction
    assert res["formula"] == "(전망 - 실적) / 실적 × 100"
    assert res["grade"] == "A" and res["asof"] == "2025-12" and res["sources"] == SOURCES
    # 계산 과정이 묶음에 남고, 그 묶음은 그대로 검증을 통과한다
    assert res["reproducibility"] == provenance.REPRO_DETERMINISTIC
    ok, problems = verify_bundle(res["bundle_dir"])
    assert ok, problems


def test_bundled_backtest_bundle_contents(cleanup_report):
    res = bundled_backtest(cleanup_report, "R01-S-002", 26, 104, "개소", SOURCES)
    bundle_dir = Path(res["bundle_dir"])
    assert bundle_dir.parent == config.report_dir(cleanup_report) / "runs"
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))

    assert {e["name"] for e in manifest["inputs"]} == {"forecast.json", "actual.json", "sources.json"}
    assert [e["name"] for e in manifest["intermediate"]] == ["diff.json"]
    assert len(manifest["intermediate"][0]["sha256"]) == 64
    assert [e["name"] for e in manifest["outputs"]] == ["backtest.json"]
    assert manifest["llm"] is None  # 순수 계산 → LLM 기록 없음

    # 실적치 입력에는 출처·등급·기준 시점이 붙는다
    actual = next(e for e in manifest["inputs"] if e["name"] == "actual.json")
    assert actual["source_url"] == SOURCES[0]["url"] and actual["grade"] == "A" and actual["asof"] == "2025-12"

    # 계산 코드 원문이 보존된다(식이 그대로 들어 있다)
    code_text = (bundle_dir / manifest["code"][0]["path"]).read_text(encoding="utf-8")
    assert "(forecast - actual) / actual * 100" in code_text


def test_bundled_backtest_zero_actual(cleanup_report):
    res = bundled_backtest(cleanup_report, "R01-F-020", 10, 0, "개소", SOURCES)
    assert res["error_pct"] is None
    assert res["direction"] == "산출 불가(실적 0)"
    assert verify_bundle(res["bundle_dir"])[0] is True


# ---------------------------------------------------------------- ④ 실행 환경
def test_manifest_records_environment(tmp_path):
    _b, m = _filled_bundle(tmp_path)
    env = m["environment"]
    assert env["python"] == platform.python_version()
    assert env["python"].startswith("3.")
    assert env["platform"] and isinstance(env["platform"], str)
    assert isinstance(env["packages"], dict) and env["packages"]
    # requirements 기준으로 이 프로젝트가 쓰는 패키지만 담는다(전체 freeze 금지)
    assert "pytest" in env["packages"]
    installed = set(env["packages"])
    declared = {n.lower().replace("_", "-") for n in provenance._requirement_names()}
    assert {n.lower().replace("_", "-") for n in installed} <= declared
    assert all(isinstance(v, str) and v for v in env["packages"].values())


# ---------------------------------------------------------------- ⑤ LLM 재추적(재현 아님)
def test_llm_context_is_traceable_not_reproducible(tmp_path):
    b = open_bundle(REPORT_ID, "compare", root=tmp_path)
    b.add_input("brief.md", "연구질문 1: …", grade="C")
    b.set_llm_context(model="anthropic/claude-x", temperature=0.2, seed=None, prompt_sha="프롬프트 전문")
    m = b.close()

    llm = m["llm"]
    assert "재현되지 않는다" in llm["note"]              # 판정 재현을 약속하지 않는다(고정점)
    assert llm["note"] == provenance.LLM_NOTE
    assert llm["model"] == "anthropic/claude-x" and llm["temperature"] == 0.2 and llm["seed"] is None
    assert len(llm["prompt_sha256"]) == 64               # 전문을 주면 해시로 바꿔 기록
    assert llm["prompt_sha256"] == hashlib.sha256("프롬프트 전문".encode("utf-8")).hexdigest()

    # LLM 이 끼면 "계산 재현"이 아니라 "판정 재추적"
    assert m["reproducibility"] == provenance.REPRO_TRACEABLE
    assert "재추적" in m["reproducibility_note"]
    assert verify_bundle(b.dir)[0] is True

    # 이미 64자리 해시를 주면 그대로 쓴다
    b2 = open_bundle(REPORT_ID, "compare", root=tmp_path)
    sha = hashlib.sha256(b"x").hexdigest()
    assert b2.set_llm_context("m", 0.0, seed=7, prompt_sha=sha)["prompt_sha256"] == sha
    assert b2.close()["llm"]["seed"] == 7


# ---------------------------------------------------------------- 안전장치
def test_rejects_bad_names_grades_and_ids(tmp_path):
    b = open_bundle(REPORT_ID, "verify_forecast", root=tmp_path)
    with pytest.raises(ValueError):
        b.add_input("../밖으로.json", {"a": 1})
    with pytest.raises(ValueError):
        b.add_input("x.json", {"a": 1}, grade="D")        # 등급은 A·B·C 만
    with pytest.raises(FileNotFoundError):
        b.add_input("x.csv", tmp_path / "없는파일.csv")
    b.close()
    with pytest.raises(provenance.BundleError):
        b.add_output("나중에", {"a": 1})                   # 닫힌 묶음에는 더 담지 않는다
    with pytest.raises(ValueError):
        open_bundle("BAD", "stage", root=tmp_path)        # 보고서 ID 형식
