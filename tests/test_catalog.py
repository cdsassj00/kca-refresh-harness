from scripts.sources.catalog import CATALOG
from scripts.sources import load_sources, source_statuses

EXPECTED = {"openalex","crossref","semantic_scholar","arxiv","data_go_kr","kosis","law_go_kr",
            "assembly","naver_news","ecos","kci","nanet","scienceon","ieee","core","springer","lens",
            "scopus","wos","dimensions","exa","tavily","perplexity","serpapi_scholar","dbpia","bigkinds"}

def test_catalog_names_and_fields():
    names = {c["name"] for c in CATALOG}
    assert names == EXPECTED
    for c in CATALOG:
        assert c["tier"] in ("T0","T1","T2","T3")
        assert c["kind"] in ("papers","stats","law","bills","news","web")
        assert isinstance(c["env_vars"], list)

# 커넥터가 붙은 소스. 새로 구현할 때마다 여기에 더한다.
IMPLEMENTED = {"openalex", "crossref", "semantic_scholar", "arxiv",
               "kosis", "data_go_kr", "law_go_kr", "ecos", "assembly", "kci"}

def test_statuses_report_configured_and_implemented():
    st = {s.name: s for s in source_statuses({"KOSIS_API_KEY": "x"}, http=None)}
    assert st["kosis"].configured is True and st["kosis"].implemented is True
    assert st["nanet"].implemented is False    # 아직 커넥터 없음
    assert st["openalex"].configured is True   # 키 없음 = 항상 설정됨
    assert st["scopus"].configured is False

def test_catalog_implementation_list_matches():
    assert {c["name"] for c in CATALOG if c["impl"]} == IMPLEMENTED

def test_load_sources_needs_keys_for_domestic_sources(tmp_cache):
    """국내 공식자료는 키가 있어야 목록에 오른다."""
    from scripts.sources.base import HttpClient
    http = HttpClient(tmp_cache)
    assert load_sources({}, http, kind="stats") == []
    names = {s.name for s in load_sources(
        {"KOSIS_API_KEY": "k", "ECOS_API_KEY": "e", "DATA_GO_KR_API_KEY": "d"}, http, kind="stats")}
    assert names == {"kosis", "ecos", "data_go_kr"}
    assert {s.name for s in load_sources({"LAW_GO_KR_OC": "oc"}, http, kind="law")} == {"law_go_kr"}
    assert {s.name for s in load_sources({"ASSEMBLY_API_KEY": "a"}, http, kind="bills")} == {"assembly"}

def test_load_sources_returns_only_implemented(tmp_cache):
    from scripts.sources.base import HttpClient
    srcs = load_sources({}, HttpClient(tmp_cache), kind="papers")
    assert {s.name for s in srcs} >= {"openalex","crossref","semantic_scholar","arxiv"}
