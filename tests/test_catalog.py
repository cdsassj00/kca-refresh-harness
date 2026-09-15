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

def test_statuses_report_configured_and_implemented():
    st = {s.name: s for s in source_statuses({"KOSIS_API_KEY": "x"}, http=None)}
    assert st["kosis"].configured is True and st["kosis"].implemented is False
    assert st["openalex"].configured is True   # 키 없음 = 항상 설정됨
    assert st["scopus"].configured is False

def test_load_sources_returns_only_implemented(tmp_cache):
    from scripts.sources.base import HttpClient
    srcs = load_sources({}, HttpClient(tmp_cache), kind="papers")
    assert {s.name for s in srcs} >= {"openalex","crossref","semantic_scholar","arxiv"}
