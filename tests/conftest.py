"""테스트 공통 설정.

임시폴더를 이 프로젝트 전용 경로로 옮긴다. 윈도우에서 다른 프로그램(예: 압축·편집 도구)이
시스템 임시폴더를 함께 쓰면, pytest 가 옛 임시폴더를 정리하다 PermissionError 로 멈추는 일이 있다.
CI(리눅스)에서도 같은 규칙이 적용되어 실행 환경이 한결같아진다.
`PYTEST_DEBUG_TEMPROOT` 를 직접 지정했거나 `--basetemp` 를 줬다면 그쪽이 우선한다.
"""
import os
import pathlib

import pytest

if not os.environ.get("PYTEST_DEBUG_TEMPROOT"):
    _tmproot = pathlib.Path.home() / ".cache" / "kca-refresh" / "pytest"
    try:
        _tmproot.mkdir(parents=True, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_tmproot)
    except OSError:
        pass  # 홈 폴더를 쓸 수 없으면 pytest 기본값을 그대로 둔다

@pytest.fixture
def ROOT() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]

@pytest.fixture
def tmp_cache(tmp_path) -> pathlib.Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d
