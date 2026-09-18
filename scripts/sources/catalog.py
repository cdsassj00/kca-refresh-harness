"""근거 소스 카탈로그. 이름·등급·종류·환경변수·구현 클래스를 한 곳에 선언한다."""
def _c(name, tier, kind, env_vars, impl=None):
    return {"name": name, "tier": tier, "kind": kind, "env_vars": env_vars, "impl": impl}

CATALOG = [
    # T0 키 없음
    _c("openalex", "T0", "papers", [], "scripts.sources.openalex:OpenAlexSource"),
    _c("crossref", "T0", "papers", [], "scripts.sources.crossref:CrossrefSource"),
    _c("semantic_scholar", "T0", "papers", [], "scripts.sources.semantic_scholar:SemanticScholarSource"),
    _c("arxiv", "T0", "papers", [], "scripts.sources.arxiv_src:ArxivSource"),
    # T1 무료 키·국내
    _c("data_go_kr", "T1", "stats", ["DATA_GO_KR_API_KEY"], "scripts.sources.data_go_kr:DataGoKrSource"),
    _c("kosis", "T1", "stats", ["KOSIS_API_KEY"], "scripts.sources.kosis:KosisSource"),
    _c("law_go_kr", "T1", "law", ["LAW_GO_KR_OC"], "scripts.sources.law_go_kr:LawGoKrSource"),
    _c("assembly", "T1", "bills", ["ASSEMBLY_API_KEY"], "scripts.sources.assembly:AssemblySource"),
    _c("naver_news", "T1", "news", ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]),
    _c("ecos", "T1", "stats", ["ECOS_API_KEY"], "scripts.sources.ecos:EcosSource"),
    _c("kci", "T1", "papers", ["KCI_API_KEY"], "scripts.sources.kci:KciSource"),
    _c("nanet", "T1", "papers", ["NANET_API_KEY"]),
    # T2 무료 키·선택
    _c("scienceon", "T2", "papers", ["SCIENCEON_API_KEY"]),
    _c("ieee", "T2", "papers", ["IEEE_API_KEY"]),
    _c("core", "T2", "papers", ["CORE_API_KEY"]),
    _c("springer", "T2", "papers", ["SPRINGER_API_KEY"]),
    _c("lens", "T2", "papers", ["LENS_API_TOKEN"]),
    # T3 유료·구독
    _c("scopus", "T3", "papers", ["ELSEVIER_API_KEY"]),
    _c("wos", "T3", "papers", ["WOS_API_KEY"]),
    _c("dimensions", "T3", "papers", ["DIMENSIONS_API_KEY"]),
    _c("exa", "T3", "web", ["EXA_API_KEY"]),
    _c("tavily", "T3", "web", ["TAVILY_API_KEY"]),
    _c("perplexity", "T3", "web", ["PERPLEXITY_API_KEY"]),
    _c("serpapi_scholar", "T3", "papers", ["SERPAPI_API_KEY"]),
    _c("dbpia", "T3", "papers", ["DBPIA_API_KEY"]),
    _c("bigkinds", "T3", "news", ["BIGKINDS_API_KEY"]),
]
OPTIONAL_ENV = ["OPENALEX_MAILTO", "CROSSREF_MAILTO", "S2_API_KEY", "ELSEVIER_INSTTOKEN"]
