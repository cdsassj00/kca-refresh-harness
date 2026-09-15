import re
from scripts.sources.catalog import CATALOG, OPTIONAL_ENV

def _vars_in(text):
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.M))

def test_guide_env_block_matches_catalog(ROOT):
    guide = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    block = guide.split("## 4.")[1].split("## 5.")[0]
    expected = {v for c in CATALOG for v in c["env_vars"]} | set(OPTIONAL_ENV)
    assert _vars_in(block) == expected

def test_env_example_matches_guide(ROOT):
    guide = (ROOT / "docs" / "api_keys_guide.md").read_text(encoding="utf-8")
    block = guide.split("## 4.")[1].split("## 5.")[0]
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert _vars_in(example) == _vars_in(block)
