"""키 안내서·`.env.example`·코드의 변수 이름이 어긋나지 않는지 검사한다.

받는 사람이 안내서대로 키를 넣었는데 프로그램이 못 알아보는 일을 막는 것이 목적이다.
안내서의 구성(절 번호·차례)은 자유롭게 바꿔도 되고, **변수 이름이 세 곳에서 일치하는지**만 본다.

  (1) `scripts/sources/catalog.py` 가 요구하는 이름  ─┐
  (2) `.env.example` 에 자리가 마련된 이름            ─┼─ 이 셋이 서로 맞아야 한다
  (3) `docs/api_keys_guide.md` 가 설명하는 이름       ─┘

공공데이터포털은 API(데이터셋)마다 인증키가 달라서 `DATA_GO_KR_KEY_<이름>` 을 자유롭게
추가할 수 있다. 그 접두사는 고정 목록이 아니라 규칙으로 검사한다.
"""
from __future__ import annotations

import re
import sys

import pytest

PREFIX_RULES = ("DATA_GO_KR_KEY_",)


def _catalog_vars(ROOT):
    sys.path.insert(0, str(ROOT))
    from scripts.sources.catalog import CATALOG, OPTIONAL_ENV
    return {v for c in CATALOG for v in c["env_vars"]} | set(OPTIONAL_ENV)


def _env_example_vars(ROOT) -> set:
    """`.env.example` 에서 값 자리가 마련된 이름. 주석 줄의 예시(`#   NAME=`)도 자리로 본다."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, flags=re.M))


def _guide_vars(ROOT) -> set:
    """안내서 본문에 등장하는 대문자 변수 이름."""
    text = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    return set(re.findall(r"\b([A-Z][A-Z0-9_]{5,})\b", text))


def test_env_example_covers_every_catalog_var(ROOT):
    missing = _catalog_vars(ROOT) - _env_example_vars(ROOT)
    assert missing == set(), (
        f".env.example 에 자리가 없는 변수: {sorted(missing)} — 받는 사람이 어디에 적을지 알 수 없다"
    )


def test_guide_explains_every_catalog_var(ROOT):
    missing = _catalog_vars(ROOT) - _guide_vars(ROOT)
    assert missing == set(), (
        f"안내서가 설명하지 않는 변수: {sorted(missing)} — 키를 어디서 받는지 알 수 없다"
    )


def test_env_example_has_no_unknown_var(ROOT):
    known = _catalog_vars(ROOT)
    try:
        sys.path.insert(0, str(ROOT / "app"))
        import config
        known |= set(config.ENV_KEYS)
    except Exception:  # 독립 프로그램이 없어도 이 검사는 돌아간다
        pass
    unknown = {v for v in _env_example_vars(ROOT) - known
               if not any(v.startswith(p) and len(v) > len(p) for p in PREFIX_RULES)}
    assert unknown == set(), (
        f".env.example 에 코드가 모르는 변수: {sorted(unknown)} — 넣어도 무시된다"
    )


def test_data_go_kr_per_api_keys_are_allowed(ROOT):
    """공공데이터포털은 API 마다 키가 다르다. 접두사 규칙이 실제로 통하는지 확인한다."""
    sys.path.insert(0, str(ROOT / "app"))
    try:
        import config
    except ImportError:
        pytest.skip("독립 프로그램(app/) 없음")
    assert config.is_allowed_env_key("DATA_GO_KR_KEY_KCI")
    assert config.is_allowed_env_key("DATA_GO_KR_KEY_PRISM")
    assert not config.is_allowed_env_key("DATA_GO_KR_KEY_")     # 이름이 비면 안 된다
    assert not config.is_allowed_env_key("AWS_SECRET_ACCESS_KEY")
    keys = config.data_go_kr_keys({"DATA_GO_KR_KEY_KCI": "a", "DATA_GO_KR_API_KEY": "b"})
    assert keys == {"kci": "a", "_default": "b"}


def test_guide_states_one_account_key_for_data_go_kr(ROOT):
    """공공데이터포털 설명을 고정한다 — 활용신청은 API 마다 따로, 인증키는 계정에 하나.

    이 문장을 한 번 뒤집어 적었다가 되돌린 적이 있어(2026-09-19) 회귀를 막으려 검사한다.
    """
    text = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    assert "활용신청은 API마다 따로, 인증키는 계정에 하나" in text, "핵심 문장이 없다"
    assert "일반 인증키(Decoding)" in text, "어느 키를 복사할지 안내가 없다"
    assert "데이터셋(API)마다 인증키가 따로" not in text, "키가 API 마다 다르다는 잘못된 설명이 남아 있다"


def test_guide_law_oc_is_not_email_prefix(ROOT):
    """법제처 OC 설명을 고정한다 — 이메일 앞부분이 아니라 인증키관리 화면의 값.

    '이메일의 @ 앞부분'으로 잘못 적었다가 실제 화면(OC=기관 약칭)으로 정정했다(2026-09-19).
    """
    text = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    assert "usrOcInfoMod" in text, "OC 확인 화면 주소가 없다"
    assert "이메일 앞부분이 아닙니다" in text, "이메일 앞부분이 아니라는 경고가 없다"
    assert "이메일의 @ 앞부분" not in text, "잘못된 설명이 남아 있다"


def test_guide_assembly_uses_portal_url(ROOT):
    """열린국회정보는 최상위 주소가 아니라 별도 포털 주소로 안내한다(2026-09-19 확인)."""
    text = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    assert "open.assembly.go.kr/portal/openapi/main.do" in text, "API 포털 주소가 없다"
