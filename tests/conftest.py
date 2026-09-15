import pathlib, pytest

@pytest.fixture
def ROOT() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]

@pytest.fixture
def tmp_cache(tmp_path) -> pathlib.Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d
