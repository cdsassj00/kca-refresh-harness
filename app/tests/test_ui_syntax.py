"""브라우저 화면 파일(JS·HTML)이 문법적으로 성한지 검사한다.

왜 필요한가
  화면 코드는 파이썬 검사에 걸리지 않는다. 그래서 문자열 안에 줄바꿈이 잘못 들어가
  `app.js` 전체가 문법 오류가 난 적이 있다. 브라우저가 예전 파일을 캐시로 쓰고 있어서
  화면은 멀쩡해 보였고, 캐시가 지워졌다면 앱이 통째로 죽었을 상황이었다.

  파이썬 검사만 돌리면 이런 것을 못 잡는다. node 가 있으면 `node --check` 로 확인하고,
  없으면 최소한 "따옴표 안에 진짜 줄바꿈이 있는가" 만이라도 본다.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1] / "ui"
JS_FILES = sorted(UI_DIR.glob("*.js"))
NODE = shutil.which("node")


def test_ui_has_js_files():
    assert JS_FILES, "app/ui 에 .js 파일이 없습니다"


@pytest.mark.skipif(NODE is None, reason="node 가 없어 문법 검사를 건너뜀")
@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_js_parses(path):
    """node --check 로 실제 파서에 걸어 본다."""
    r = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"{path.name} 문법 오류:\n{(r.stderr or '')[:800]}"


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_no_raw_newline_inside_quotes(path):
    """node 가 없는 환경에서도 잡히도록, 따옴표가 줄 끝에서 안 닫힌 곳을 본다.

    `split('` 로 줄이 끝나면 그 다음 줄까지 문자열이 이어진다는 뜻인데,
    자바스크립트의 작은따옴표·큰따옴표 문자열은 줄을 넘을 수 없다.
    """
    bad = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.rstrip()
        if re.search(r"(?<!\\)['\"]\s*$", s) and s.count("'") % 2 == 1:
            bad.append((n, s.strip()[:70]))
        elif re.search(r'(?<!\\)"\s*$', s) and s.count('"') % 2 == 1:
            bad.append((n, s.strip()[:70]))
    assert not bad, (
        f"{path.name}: 따옴표가 줄 끝에서 안 닫혔습니다(문자열 안에 진짜 줄바꿈). "
        + "; ".join(f"{n}번째 줄 «{t}»" for n, t in bad[:5]))


@pytest.mark.parametrize("name", ["help.js"])
def test_help_is_loaded_before_app(name):
    """읽는 법 칸은 app.js 보다 먼저 읽혀야 화면이 다 그려진 뒤에 끼워 넣을 수 있다."""
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert f'src="{name}"' in html, f"index.html 이 {name} 을 읽지 않습니다"
    assert html.index(f'src="{name}"') < html.index('src="app.js"'), (
        f"{name} 이 app.js 보다 뒤에 있습니다")
