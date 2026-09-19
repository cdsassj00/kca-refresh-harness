"""`.env.example` 두 개의 배치가 서로 어긋나지 않는지 검사한다.

왜 검사하는가
  키 파일이 여러 개인데 줄 차례와 구역 주석이 제각각이면 "지금 보고 있는 게 어느 파일인지"
  알 수 없다. 실제로 견본에 키를 적고, 편집기 내용이 디스크와 어긋나 저장이 막히는 일이 났다.
  그래서 배치를 `scripts/env_template.py` 한 곳에서 정하고 여기서 지킨다.

검사 대상은 **git 에 올라가는 견본뿐**이다. 실제 키 파일(`.env`)은 사람마다 다르고 저장소에
없으므로 검사하지 않는다(있으면 배치를 맞추라고 안내만 한다).

배치를 바꾸려면 `scripts/env_template.py` 의 SECTIONS 를 고치고
`python scripts/env_template.py --write` 를 돌린다.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [".env.example", "app/.env.example"]


def _template():
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts import env_template
    return env_template


@pytest.mark.parametrize("rel", EXAMPLES)
def test_example_matches_the_template(rel):
    """견본은 원본이 만드는 내용과 글자까지 같아야 한다."""
    t = _template()
    path = ROOT / rel
    assert path.exists(), f"{rel} 이 없습니다"
    assert path.read_text(encoding="utf-8") == t.render(rel), (
        f"{rel} 의 배치가 원본과 다릅니다. "
        "`python scripts/env_template.py --write` 로 맞추세요")


def test_every_example_has_the_same_variable_order():
    """두 견본의 변수 차례가 같아야 한다 — 이것이 헷갈림의 원인이었다."""
    t = _template()
    orders = {rel: t.layout_of((ROOT / rel).read_text(encoding="utf-8")) for rel in EXAMPLES}
    first, *rest = list(orders.values())
    for rel, order in orders.items():
        assert order == first, f"{rel} 의 변수 차례가 다릅니다"
    assert first == t.VAR_ORDER, "견본의 변수 차례가 원본(SECTIONS)과 다릅니다"


def test_template_covers_what_the_code_reads():
    """원본이 코드가 실제로 읽는 변수를 빠짐없이 담고 있는지 본다.

    빠지면 받는 사람이 그 키를 어디에 적을지 알 수 없다.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "app"))
    t = _template()
    from scripts.sources.catalog import CATALOG, OPTIONAL_ENV
    needed = {v for c in CATALOG for v in c["env_vars"]} | set(OPTIONAL_ENV)
    try:
        import config
        needed |= set(config.ENV_KEYS)
    except ImportError:      # 독립 프로그램이 없어도 이 검사는 돌아간다
        pass
    missing = needed - set(t.VAR_ORDER)
    assert missing == set(), (
        f"scripts/env_template.py 에 자리가 없는 변수: {sorted(missing)}")


def test_template_has_no_variable_the_code_ignores():
    """반대로, 코드가 모르는 변수를 견본에 두면 받는 사람이 넣어도 무시된다."""
    import sys
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "app"))
    t = _template()
    from scripts.sources.catalog import CATALOG, OPTIONAL_ENV
    known = {v for c in CATALOG for v in c["env_vars"]} | set(OPTIONAL_ENV)
    try:
        import config
        known |= set(config.ENV_KEYS)
    except ImportError:
        pass
    extra = set(t.VAR_ORDER) - known
    assert extra == set(), f"코드가 읽지 않는 변수: {sorted(extra)}"


def test_no_duplicate_variables():
    t = _template()
    seen, dup = set(), []
    for name in t.VAR_ORDER:
        (dup.append(name) if name in seen else seen.add(name))
    assert not dup, f"원본에 같은 변수가 두 번 있습니다: {dup}"
