"""설정 화면이 `.env` 를 저장할 때 파일 배치를 망가뜨리지 않는지 검사한다.

예전에는 저장할 때마다 파일을 통째로 다시 썼다. 그래서 두 가지가 실제로 일어났다.
  1. 사람이 편집기에 열어 둔 내용과 어긋나 VS Code 가 저장을 거부했다
     ("파일의 내용이 최신입니다. 버전을 파일 내용과 비교하거나…")
  2. 주석과 구역이 사라져, 견본 파일과 배치가 달라졌다

지금은 **있는 줄의 값만 바꾸고, 없는 키만 끝에 덧붙인다.**
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config


SAMPLE = """# 독립 프로그램 설정. git 에 올라가지 않는다.

# ── 웹 검색 ──
# Tavily 검색 키
TAVILY_API_KEY=tvly-old
# Exa 검색 키
EXA_API_KEY=

# ── 국내 ──
KOSIS_API_KEY=kosis-old
"""


@pytest.fixture
def envfile(tmp_path):
    p = tmp_path / ".env"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def _lines(p):
    return p.read_text(encoding="utf-8").splitlines()


def test_comments_and_order_survive_a_save(envfile, monkeypatch):
    monkeypatch.setattr(config, "ENV_PATH", envfile)
    config.save_env_values({"TAVILY_API_KEY": "tvly-new"}, path=envfile)
    lines = _lines(envfile)
    # 주석이 그대로 있다
    assert "# ── 웹 검색 ──" in lines and "# Tavily 검색 키" in lines
    assert "# ── 국내 ──" in lines
    # 줄 차례가 그대로다
    names = [l.split("=", 1)[0] for l in lines if l and not l.startswith("#") and "=" in l]
    assert names == ["TAVILY_API_KEY", "EXA_API_KEY", "KOSIS_API_KEY"]
    # 바꾼 값만 바뀌었다
    assert "TAVILY_API_KEY=tvly-new" in lines
    assert "KOSIS_API_KEY=kosis-old" in lines


def test_missing_key_is_appended_not_reordered(envfile, monkeypatch):
    """파일에 없던 키는 끝에 붙인다. 앞쪽 차례를 흔들지 않는다."""
    monkeypatch.setattr(config, "ENV_PATH", envfile)
    config.save_env_values({"OPENROUTER_API_KEY": "sk-or-test"}, path=envfile)
    lines = _lines(envfile)
    assert lines[:3] == SAMPLE.splitlines()[:3]          # 앞부분 그대로
    assert "OPENROUTER_API_KEY=sk-or-test" in lines
    assert lines.index("OPENROUTER_API_KEY=sk-or-test") > lines.index("KOSIS_API_KEY=kosis-old")


def test_empty_value_clears_the_key_but_keeps_the_line(envfile, monkeypatch):
    """빈 값으로 저장하면 키가 비워진다. 줄은 남아 있어야 나중에 다시 넣기 쉽다."""
    monkeypatch.setattr(config, "ENV_PATH", envfile)
    config.save_env_values({"KOSIS_API_KEY": ""}, path=envfile)
    lines = _lines(envfile)
    assert "KOSIS_API_KEY=" in lines
    assert "KOSIS_API_KEY=kosis-old" not in lines
    assert config._read_env_file(envfile)["KOSIS_API_KEY"] == ""


def test_unknown_key_is_refused_and_file_untouched(envfile, monkeypatch):
    monkeypatch.setattr(config, "ENV_PATH", envfile)
    before = envfile.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="허용되지 않은"):
        config.save_env_values({"AWS_SECRET_ACCESS_KEY": "x"}, path=envfile)
    assert envfile.read_text(encoding="utf-8") == before


def test_data_go_kr_prefix_key_is_accepted(envfile, monkeypatch):
    """공공데이터포털 전용 키(DATA_GO_KR_KEY_*)는 목록에 없어도 허용한다."""
    monkeypatch.setattr(config, "ENV_PATH", envfile)
    config.save_env_values({"DATA_GO_KR_KEY_PRISM": "abc"}, path=envfile)
    assert "DATA_GO_KR_KEY_PRISM=abc" in _lines(envfile)


def test_saving_twice_does_not_keep_growing_the_file(envfile, monkeypatch):
    """같은 키를 두 번 저장해도 줄이 늘지 않는다(덧붙인 줄을 다시 찾아 고친다)."""
    monkeypatch.setattr(config, "ENV_PATH", envfile)
    config.save_env_values({"OPENROUTER_API_KEY": "sk-or-1"}, path=envfile)
    first = len(_lines(envfile))
    config.save_env_values({"OPENROUTER_API_KEY": "sk-or-2"}, path=envfile)
    lines = _lines(envfile)
    assert len(lines) == first
    assert "OPENROUTER_API_KEY=sk-or-2" in lines
    assert "OPENROUTER_API_KEY=sk-or-1" not in lines
