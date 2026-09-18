"""배치 파일(.bat/.cmd) 검사.

받은 사람이 두 번 클릭해서 여는 파일이라, 여기가 깨지면 프로그램 자체를 못 연다.
실제로 한 번 깨졌다: `.gitattributes` 가 모든 파일을 LF 로 강제하는 바람에
`run_app.bat` 의 줄 끝이 LF 가 되었고, cmd 가 줄을 엉뚱한 데서 잘라
`if ... ( )` 블록이 통째로 무너지면서 줄 조각을 명령으로 실행하려 들었다.

    'st'은(는) 내부 또는 외부 명령, 실행할 수 있는 프로그램, 또는 배치 파일이 아닙니다.

세 가지를 못 박는다.
  ① 줄 끝은 반드시 CRLF        — cmd 가 LF 만으로는 줄을 제대로 못 나눈다
  ② UTF-8 BOM 을 붙이지 않는다 — 붙이면 첫 줄이 `?@echo` 가 되어 실행된다(실험으로 확인)
  ③ 한글이 든 파일은 `chcp 65001` 을 켠다 — 없으면 한글이 깨져 보인다
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__"}


def _batch_files() -> list[Path]:
    out = []
    for pat in ("*.bat", "*.cmd"):
        for p in ROOT.rglob(pat):
            if not SKIP_DIRS & set(p.relative_to(ROOT).parts):
                out.append(p)
    return sorted(out)


BATCH_FILES = _batch_files()


def test_there_are_batch_files():
    """검사 대상이 실제로 있는지 본다(글로브가 틀려서 0건이면 아래 검사가 무의미해진다)."""
    assert BATCH_FILES, "배치 파일을 하나도 못 찾았습니다"


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_line_endings_are_crlf(path):
    """① cmd 는 배치 파일에 CRLF 를 요구한다."""
    data = path.read_bytes()
    bare_lf = data.replace(b"\r\n", b"").count(b"\n")
    assert bare_lf == 0, (
        f"{path.relative_to(ROOT)} 에 CRLF 가 아닌 줄이 {bare_lf}개 있습니다. "
        "cmd 가 줄을 잘못 잘라 실행이 깨집니다")


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_no_utf8_bom(path):
    """② BOM 이 있으면 첫 줄이 `?@echo off` 가 되어 명령으로 실행된다."""
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), (
        f"{path.relative_to(ROOT)} 에 UTF-8 BOM 이 있습니다")


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_korean_batch_sets_utf8_codepage(path):
    """③ 한글을 쓰는 배치 파일은 코드페이지를 65001 로 올려야 글자가 안 깨진다."""
    text = path.read_bytes().decode("utf-8")
    has_korean = any("가" <= ch <= "힣" for ch in text)
    if not has_korean:
        pytest.skip("한글이 없는 파일")
    assert "chcp 65001" in text, (
        f"{path.relative_to(ROOT)} 는 한글을 쓰는데 `chcp 65001` 이 없습니다")


def test_gitattributes_keeps_crlf_for_batch_files():
    """받는 사람이 clone 해도 CRLF 로 내려오도록 규칙이 있어야 한다.

    `* text=auto eol=lf` 만 있으면 배치 파일까지 LF 로 내려와 같은 사고가 재발한다.
    """
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    for pat in ("*.bat", "*.cmd"):
        assert any(l.startswith(pat) and "eol=crlf" in l for l in lines), (
            f".gitattributes 에 `{pat} text eol=crlf` 규칙이 없습니다")
