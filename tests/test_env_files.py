"""`.env` 관련 파일 검사.

`.env.example` 은 **빈 견본**이다. git 에 올라가는 파일이므로, 여기에 실제 키가 들어가면
공개 저장소에 키가 그대로 노출된다. 실제로 한 번 이 자리에 키를 입력하는 일이 있었다.

  - `.env.example`  → git 에 올라감. **값이 있으면 안 된다**
  - `.env`          → git 이 무시함. 실제 키는 여기에만

값을 허용하는 예외는 딱 하나, 키가 아닌 것(이메일 주소 등)뿐이다. 그것조차 개인 정보이므로
견본에는 빈칸으로 두고 안내서에서 설명한다.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__"}


def _env_examples() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob(".env.example")
        if not SKIP_DIRS & set(p.relative_to(ROOT).parts))


EXAMPLES = _env_examples()


def _entries(path: Path) -> list[tuple[int, str, str]]:
    """(줄번호, 변수이름, 값) 목록. 주석과 빈 줄은 건너뛴다."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out.append((n, k.strip(), v.strip().strip('"').strip("'")))
    return out


def test_env_examples_exist():
    assert EXAMPLES, ".env.example 을 하나도 못 찾았습니다"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: str(p.relative_to(ROOT)))
def test_example_has_no_real_values(path):
    """견본에 값이 들어가면 그대로 커밋돼 공개된다."""
    filled = [(n, k, v) for n, k, v in _entries(path) if v]
    assert not filled, (
        f"{path.relative_to(ROOT)} 에 값이 들어 있습니다: "
        + ", ".join(f"{n}번째 줄 {k}" for n, k, _ in filled)
        + ". 견본은 비워 두고, 실제 키는 git 이 무시하는 .env 에 넣으세요")


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: str(p.relative_to(ROOT)))
def test_example_is_git_tracked_and_env_is_not(path):
    """견본은 올라가야 하고, 같은 자리의 실제 파일은 올라가면 안 된다."""
    import subprocess

    def tracked(p: Path) -> bool:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(p.relative_to(ROOT))],
                           cwd=ROOT, capture_output=True)
        return r.returncode == 0

    assert tracked(path), f"{path.relative_to(ROOT)} 는 git 에 올라가 있어야 합니다(받는 사람용 견본)"
    real = path.with_name(".env")
    if real.exists():
        assert not tracked(real), (
            f"{real.relative_to(ROOT)} 가 git 에 올라가 있습니다. 즉시 빼고 키를 새로 발급하세요")
