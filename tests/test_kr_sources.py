"""국내 공식자료 커넥터 5종(KOSIS·공공데이터포털·법제처·한국은행·열린국회정보) 검사.

실제 호출은 하지 않는다. 모든 응답은 mock 이다. 소스마다 다섯 가지를 본다.
  ① 정상 응답 → 레코드 필드·등급·URL·extra
  ② 근거 레코드 스키마 통과
  ③ 빈 결과
  ④ 키 오류일 때 ping() 이 한국어로 사유를 알려 줌
  ⑤ since/until 기간 필터
"""
import json
from unittest.mock import patch

import pytest

from scripts.sources.base import HttpClient
from scripts.sources.assembly import AssemblySource
from scripts.sources.data_go_kr import DataGoKrSource
from scripts.sources.ecos import EcosSource
from scripts.sources.kosis import KosisSource
from scripts.sources.law_go_kr import LawGoKrSource
from scripts.validate import validate_obj


def _ok(rec):
    """근거 레코드 스키마를 통과하고 등급이 A(1차 출처)인지 확인한다."""
    assert validate_obj(rec.to_json(), "evidence_record") == []
    assert rec.grade == "A"
    assert rec.url.startswith("http")
    return rec


# ────────────────────────────── KOSIS ──────────────────────────────
KOSIS_SEARCH = json.dumps([{
    "ORG_ID": "101", "ORG_NM": "통계청", "TBL_ID": "DT_1IN1502", "TBL_NM": "인구총조사 총조사인구",
    "STAT_ID": "1962001", "STAT_NM": "인구총조사", "CONTENTS": "성별 인구",
    "STRT_PRD_DE": "2015", "END_PRD_DE": "2024",
}], ensure_ascii=False)
KOSIS_DATA = json.dumps([{
    "ORG_ID": "101", "TBL_ID": "DT_1IN1502", "TBL_NM": "인구총조사 총조사인구",
    "C1_NM": "전국", "ITM_ID": "T10", "ITM_NM": "총인구", "UNIT_NM": "명",
    "PRD_SE": "Y", "PRD_DE": "2024", "DT": "51234567", "LST_CHN_DE": "2025-07-01",
}], ensure_ascii=False)


def _kosis(tmp_cache):
    return KosisSource({"KOSIS_API_KEY": "KEY-SECRET"}, HttpClient(tmp_cache))


def test_kosis_search_makes_table_record(tmp_cache):
    s = _kosis(tmp_cache)
    with patch.object(s.http, "get_text", return_value=KOSIS_SEARCH) as g:
        r = _ok(s.search("인구", limit=5)[0])
    assert r.source == "kosis" and r.title.startswith("인구총조사")
    assert r.url == "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN1502"
    assert r.date == "2024-12-31"
    assert r.extra["tbl_id"] == "DT_1IN1502" and r.extra["org_id"] == "101"
    # 인증키는 질의 문자열로만 보내고(캐시에는 해시로만 남는다) jsonVD 를 반드시 켠다
    assert g.call_args.kwargs["params"]["jsonVD"] == "Y"
    assert g.call_args.kwargs["params"]["method"] == "getList"
    assert g.call_args.kwargs["params"]["apiKey"] == "KEY-SECRET"


def test_kosis_fetch_series_carries_time_and_value(tmp_cache):
    s = _kosis(tmp_cache)
    with patch.object(s.http, "get_text", return_value=KOSIS_DATA) as g:
        r = _ok(s.fetch_series("101", "DT_1IN1502", itm_id="T10", obj_l=("ALL",),
                               prd_se="Y", start_prd_de="2015", end_prd_de="2024")[0])
    assert r.extra["prd_de"] == "2024" and r.extra["value"] == "51234567"
    assert r.extra["itm_nm"] == "총인구" and r.extra["unit"] == "명"
    assert r.date == "2024-12-31" and r.extra["레코드종류"] == "시계열값"
    assert g.call_args.kwargs["params"]["objL1"] == "ALL"


def test_kosis_empty_result_is_not_an_error(tmp_cache):
    s = _kosis(tmp_cache)
    with patch.object(s.http, "get_text", return_value='{"err":"30","errMsg":"자료가 없습니다"}'):
        assert s.search("없는통계") == []
        assert s.ping() == (True, "OK, 키는 정상(검색 결과 0건)")


def test_kosis_ping_explains_key_error_in_korean(tmp_cache):
    s = _kosis(tmp_cache)
    with patch.object(s.http, "get_text", return_value='{"err":"10","errMsg":"invalid key"}'):
        ok, msg = s.ping()
    assert ok is False and "인증키" in msg


def test_kosis_since_until_filters_by_coverage(tmp_cache):
    s = _kosis(tmp_cache)
    with patch.object(s.http, "get_text", return_value=KOSIS_SEARCH):
        assert s.search("인구", since="2025-01-01") == []   # 수록 종료가 2024 라 제외
        assert s.search("인구", until="2014-12-31") == []   # 수록 시작이 2015 라 제외
        assert len(s.search("인구", since="2020-01-01", until="2026-12-31")) == 1


# ────────────────────────────── ECOS ──────────────────────────────
ECOS_TABLES = json.dumps({"StatisticTableList": {"list_total_count": 2, "row": [
    {"P_STAT_CODE": "", "STAT_CODE": "722Y001", "STAT_NAME": "1.3.1. 한국은행 기준금리",
     "CYCLE": "M", "SRCH_YN": "Y", "ORG_NAME": "한국은행"},
    {"P_STAT_CODE": "", "STAT_CODE": "901Y009", "STAT_NAME": "소비자물가지수",
     "CYCLE": "M", "SRCH_YN": "Y", "ORG_NAME": "통계청"},
]}}, ensure_ascii=False)
ECOS_SERIES = json.dumps({"StatisticSearch": {"list_total_count": 1, "row": [
    {"STAT_CODE": "722Y001", "STAT_NAME": "한국은행 기준금리", "ITEM_CODE1": "0101000",
     "ITEM_NAME1": "한국은행 기준금리", "UNIT_NAME": "%", "TIME": "202506", "DATA_VALUE": "2.5"},
]}}, ensure_ascii=False)


def _ecos(tmp_cache):
    return EcosSource({"ECOS_API_KEY": "KEY-SECRET"}, HttpClient(tmp_cache))


def test_ecos_search_filters_tables_by_name_and_hides_key_from_cache(tmp_cache):
    s = _ecos(tmp_cache)
    with patch.object(s.http, "get_text", return_value=ECOS_TABLES) as g:
        recs = s.search("기준금리", limit=5)
    r = _ok(recs[0])
    assert len(recs) == 1 and r.extra["통계표코드"] == "722Y001" and r.extra["주기"] == "M"
    # 인증키가 주소 경로에 들어가므로 캐시에 남길 주소에서는 지워져야 한다
    cache_url = g.call_args.kwargs["cache_url"]
    assert "KEY-SECRET" not in cache_url and "/KEY/json/kr/" in cache_url
    assert "KEY-SECRET" in g.call_args.args[0]  # 실제 호출 주소에는 들어 있다


def test_ecos_fetch_series_carries_time_and_value(tmp_cache):
    s = _ecos(tmp_cache)
    with patch.object(s.http, "get_text", return_value=ECOS_SERIES):
        r = _ok(s.fetch_series("722Y001", cycle="M", start="202401", end="202506")[0])
    assert r.extra["시점"] == "202506" and r.extra["값"] == "2.5" and r.extra["단위"] == "%"
    assert r.extra["통계표코드"] == "722Y001" and r.date == "2025-06-01"


def test_ecos_empty_result_is_not_an_error(tmp_cache):
    s = _ecos(tmp_cache)
    empty = '{"RESULT":{"CODE":"INFO-200","MESSAGE":"해당하는 데이터가 없습니다."}}'
    with patch.object(s.http, "get_text", return_value=empty):
        assert s.search("없는통계") == []
        assert s.fetch_series("000Y000", cycle="A", start="2020", end="2025") == []
        assert s.ping() == (True, "OK, 키는 정상(자료 0건)")


def test_ecos_series_requires_both_dates(tmp_cache):
    """ECOS 는 자리로 뜻이 정해지는 주소라 기간 한쪽만 주면 뒤가 밀린다. 미리 막는다."""
    with pytest.raises(ValueError, match="종료일자"):
        _ecos(tmp_cache).fetch_series("722Y001", cycle="M", start="202401")


def test_ecos_ping_explains_key_error_in_korean(tmp_cache):
    s = _ecos(tmp_cache)
    bad = '{"RESULT":{"CODE":"INFO-100","MESSAGE":"Invalid Auth Key"}}'
    with patch.object(s.http, "get_text", return_value=bad):
        ok, msg = s.ping()
    assert ok is False and "인증키가 유효하지 않습니다" in msg


def test_ecos_series_period_goes_into_the_request(tmp_cache):
    """ECOS 는 기간을 주소 경로로 받는다. since/until 대신 fetch_series 인자로 넘어간다."""
    s = _ecos(tmp_cache)
    with patch.object(s.http, "get_text", return_value=ECOS_SERIES) as g:
        s.fetch_series("722Y001", cycle="M", start="202401", end="202506")
    assert "/722Y001/M/202401/202506" in g.call_args.kwargs["cache_url"]


# ───────────────────────────── 법제처 ─────────────────────────────
LAW_SEARCH = json.dumps({"LawSearch": {"target": "law", "totalCnt": "1", "page": "1", "law": [{
    "법령일련번호": "241234", "현행연혁코드": "현행", "법령명한글": "전파법", "법령약칭명": "",
    "법령ID": "001234", "공포일자": "20240109", "공포번호": "20001",
    "제개정구분명": "일부개정", "소관부처명": "과학기술정보통신부", "법령구분명": "법률",
    "시행일자": "20240710", "자법타법여부": "N",
    "법령상세링크": "/DRF/lawService.do?OC=myoc&target=law&MST=241234&type=HTML",
}]}}, ensure_ascii=False)


def _law(tmp_cache):
    return LawGoKrSource({"LAW_GO_KR_OC": "myoc"}, HttpClient(tmp_cache))


def test_law_search_makes_public_url_and_extra(tmp_cache):
    s = _law(tmp_cache)
    with patch.object(s.http, "get_text", return_value=LAW_SEARCH) as g:
        r = _ok(s.search("전파법", limit=5)[0])
    assert r.title == "전파법" and r.id == "001234"
    assert r.url.startswith("https://www.law.go.kr/%EB%B2%95%EB%A0%B9/")  # 공개 화면 주소
    assert r.date == "2024-07-10"
    assert r.extra["법령ID"] == "001234" and r.extra["시행일자"] == "2024-07-10"
    assert r.extra["공포일자"] == "2024-01-09" and r.extra["개정구분"] == "일부개정"
    assert "OC=***" in r.extra["법령상세링크"] and "myoc" not in r.extra["법령상세링크"]
    assert g.call_args.kwargs["params"]["type"] == "JSON"


def test_law_empty_result(tmp_cache):
    s = _law(tmp_cache)
    with patch.object(s.http, "get_text", return_value='{"LawSearch":{"totalCnt":"0"}}'):
        assert s.search("없는법") == []
        assert s.ping() == (True, "OK, 총 0건 검색")


def test_law_ping_explains_bad_oc_in_korean(tmp_cache):
    s = _law(tmp_cache)
    with patch.object(s.http, "get_text", return_value="<html>인증 실패</html>"):
        ok, msg = s.ping()
    assert ok is False and "OC" in msg and "승인" in msg


def test_law_ping_without_oc(tmp_cache):
    ok, msg = LawGoKrSource({}, HttpClient(tmp_cache)).ping()
    assert ok is False and "LAW_GO_KR_OC" in msg


def test_law_since_until_filters_by_effective_date(tmp_cache):
    s = _law(tmp_cache)
    with patch.object(s.http, "get_text", return_value=LAW_SEARCH) as g:
        assert s.search("전파법", since="2025-01-01") == []      # 시행 2024-07-10
        assert s.search("전파법", until="2024-01-01") == []
        assert len(s.search("전파법", since="2024-01-01", until="2024-12-31")) == 1
    assert g.call_args.kwargs["params"]["efYd"] == "20240101~20241231"


def test_law_fetch_law_needs_an_identifier(tmp_cache):
    with pytest.raises(ValueError):
        _law(tmp_cache).fetch_law()


# ──────────────────────────── 열린국회정보 ────────────────────────────
BILLS = json.dumps({"nzmimeepazxkubdpn": [
    {"head": [{"list_total_count": 1},
              {"RESULT": {"CODE": "INFO-000", "MESSAGE": "정상 처리되었습니다."}}]},
    {"row": [{
        "BILL_ID": "PRC_X2Y", "BILL_NO": "2201234", "BILL_NAME": "전파법 일부개정법률안",
        "COMMITTEE": "과학기술정보방송통신위원회", "PROPOSE_DT": "2024-03-15",
        "PROC_RESULT": "원안가결", "PROC_DT": "2024-06-20", "AGE": "22",
        "DETAIL_LINK": "https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_X2Y",
        "PROPOSER": "홍길동의원 등 10인", "RST_PROPOSER": "홍길동",
    }]},
]}, ensure_ascii=False)


def _bills(tmp_cache):
    return AssemblySource({"ASSEMBLY_API_KEY": "KEY-SECRET"}, HttpClient(tmp_cache))


def test_assembly_search_makes_bill_record(tmp_cache):
    s = _bills(tmp_cache)
    with patch.object(s.http, "get_text", return_value=BILLS) as g:
        r = _ok(s.search("전파법", limit=5)[0])
    assert r.id == "PRC_X2Y" and r.title == "전파법 일부개정법률안"
    assert r.url.startswith("https://likms.assembly.go.kr/bill/billDetail.do")
    assert r.date == "2024-03-15"
    assert r.extra["의안번호"] == "2201234" and r.extra["제안일"] == "2024-03-15"
    assert r.extra["처리결과"] == "원안가결" and r.extra["대표발의자"] == "홍길동"
    assert g.call_args.kwargs["params"]["Type"] == "json"


def test_assembly_empty_result(tmp_cache):
    s = _bills(tmp_cache)
    empty = '{"RESULT":{"CODE":"INFO-200","MESSAGE":"해당하는 데이터가 없습니다."}}'
    with patch.object(s.http, "get_text", return_value=empty):
        assert s.search("없는법안") == []
        assert s.ping() == (True, "OK, 키는 정상(자료 0건)")


def test_assembly_ping_explains_key_error_in_korean(tmp_cache):
    s = _bills(tmp_cache)
    bad = '{"RESULT":{"CODE":"INFO-100","MESSAGE":"Invalid KEY"}}'
    with patch.object(s.http, "get_text", return_value=bad):
        ok, msg = s.ping()
    assert ok is False and "인증키가 유효하지 않습니다" in msg


def test_assembly_traffic_limit_is_explained(tmp_cache):
    s = _bills(tmp_cache)
    over = '{"RESULT":{"CODE":"ERROR-337","MESSAGE":"traffic"}}'
    with patch.object(s.http, "get_text", return_value=over):
        ok, msg = s.ping()
    assert ok is False and "한도" in msg


def test_assembly_since_until_filters_by_propose_date(tmp_cache):
    s = _bills(tmp_cache)
    with patch.object(s.http, "get_text", return_value=BILLS):
        assert s.search("전파법", since="2025-01-01") == []
        assert s.search("전파법", until="2024-01-01") == []
        assert len(s.search("전파법", since="2024-01-01", until="2024-12-31")) == 1


# ─────────────────────────── 공공데이터포털 ───────────────────────────
DGK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE</resultMsg></header>
<body><items><item><artiId>ART001</artiId><title>전파자원 이용 효율화 연구</title>
<pubDate>20240501</pubDate></item></items><totalCount>1</totalCount></body></response>"""
DGK_BAD_KEY = """<?xml version="1.0" encoding="UTF-8"?>
<OpenAPI_ServiceResponse><cmmMsgHeader>
<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>
<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"""
DGK_NO_DATA = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>03</resultCode><resultMsg>NODATA_ERROR</resultMsg></header>
<body/></response>"""
DGK_JSON = json.dumps({"response": {
    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
    "body": {"items": {"item": [
        {"bill_id": "PRC_A1", "bill_name": "전파법 일부개정법률안", "propose_dt": "2024-03-15"},
    ]}, "totalCount": 1}}}, ensure_ascii=False)
# PRISM 은 표준 봉투가 아니라 최상위에 결과 코드와 목록이 납작하게 온다(실호출 확인).
DGK_PRISM = json.dumps({
    "resultCode": "0", "resultMsg": "NORMAL_SERVICE", "totalCount": 2,
    "research": [
        {"research_id": "1721000-202400012", "research_name": "전파자원 이용 효율화 방안 연구",
         "organ_name": "과학기술정보통신부", "research_organName": "정보통신정책연구원",
         "research_date": "2024-03-19", "issued_year": "2024", "report_open_yn": "공개"},
        {"research_id": "1721000-202400099", "research_name": "재난안전통신망 운영 개선 연구",
         "organ_name": "과학기술정보통신부", "research_date": "2024-05-02"},
    ]}, ensure_ascii=False)


def _dgk(tmp_cache, dataset="kci_article"):
    return DataGoKrSource({"DATA_GO_KR_API_KEY": "KEY-SECRET"}, HttpClient(tmp_cache), dataset)


def test_data_go_kr_default_dataset_is_prism(tmp_cache):
    """하네스가 가장 자주 쓰는 건 후속 연구 발주 추적(PRISM)이다."""
    s = DataGoKrSource({"DATA_GO_KR_API_KEY": "k"}, HttpClient(tmp_cache))
    assert s.dataset == "prism_research"


def test_data_go_kr_prism_flat_envelope_and_title_filter(tmp_cache):
    s = _dgk(tmp_cache, "prism_research")
    with patch.object(s.http, "get_text", return_value=DGK_PRISM) as g:
        recs = s.search("전파", since="2024-01-01", until="2024-12-31",
                        limit=5, organ_id="1721000")
    r = _ok(recs[0])
    assert len(recs) == 1                       # 제목에 "전파"가 든 과제만 남는다
    assert r.id == "1721000-202400012" and r.title == "전파자원 이용 효율화 방안 연구"
    assert r.date == "2024-03-19" and r.extra["데이터셋"] == "prism_research"
    p = g.call_args.kwargs["params"]
    assert p["type"] == "json" and p["organ_id"] == "1721000"
    assert p["start_date"] == "20240101" and p["end_date"] == "20241231"


def test_data_go_kr_parses_xml_items(tmp_cache):
    s = _dgk(tmp_cache)
    with patch.object(s.http, "get_text", return_value=DGK_XML) as g:
        r = _ok(s.search("전파", limit=5)[0])
    assert r.id == "ART001" and r.title == "전파자원 이용 효율화 연구" and r.date == "2024-05-01"
    assert r.url == "https://www.data.go.kr/data/15085348/openapi.do"
    assert r.extra["데이터셋"] == "kci_article"
    assert r.extra["검색어_전달"].startswith("아니오")   # 이 상세기능에는 검색어 변수가 없다
    assert g.call_args.kwargs["params"]["ServiceKey"] == "KEY-SECRET"


def test_data_go_kr_parses_json_items_and_sends_query(tmp_cache):
    s = _dgk(tmp_cache, "assembly_bill")
    with patch.object(s.http, "get_text", return_value=DGK_JSON) as g:
        r = _ok(s.search("전파법", limit=5)[0])
    assert r.id == "PRC_A1" and r.date == "2024-03-15"
    assert g.call_args.kwargs["params"]["bill_name"] == "전파법"
    assert r.extra["검색어_전달"] == "예"


def test_data_go_kr_empty_result(tmp_cache):
    s = _dgk(tmp_cache)
    with patch.object(s.http, "get_text", return_value=DGK_NO_DATA):
        assert s.search("없는자료") == []
        assert s.ping() == (True, "OK, 키는 정상(자료 0건)")


def test_data_go_kr_ping_explains_key_error_in_korean(tmp_cache):
    s = _dgk(tmp_cache)
    with patch.object(s.http, "get_text", return_value=DGK_BAD_KEY):
        ok, msg = s.ping()
        with pytest.raises(RuntimeError, match="인증키"):
            s.search("전파")
    assert ok is False and "인증키" in msg and "Decoding" in msg


def test_data_go_kr_since_until_filters_by_date(tmp_cache):
    s = _dgk(tmp_cache, "assembly_bill")
    with patch.object(s.http, "get_text", return_value=DGK_JSON):
        assert s.search("전파법", since="2025-01-01") == []
        assert s.search("전파법", until="2024-01-01") == []
        assert len(s.search("전파법", since="2024-01-01", until="2024-12-31")) == 1


# ─────────────────────── evidence.py 하위 명령 ───────────────────────
@pytest.mark.parametrize("cmd,kind", [("stats", "stats"), ("law", "law"), ("bills", "bills")])
def test_cli_subcommands_use_the_right_kind(cmd, kind, tmp_path, tmp_cache):
    """`evidence.py stats|law|bills` 가 papers 와 같은 방식(JSONL 저장·건수 표)으로 돈다."""
    from scripts import evidence
    from scripts.sources.base import EvidenceRecord

    rec = EvidenceRecord(source="x", id="1", url="https://x", title="t", date="2024-01-01",
                         snippet="s", grade="A", retrieved_at="x", query="q")

    class Fake:
        name = "x"
        def search(self, *a, **k): return [rec]

    seen = {}

    def fake_load_sources(env, http, kind=None, only=None):
        seen["kind"] = kind
        return [Fake()]

    out = tmp_path / "o.jsonl"
    with patch.object(evidence, "load_sources", fake_load_sources), \
         patch.object(evidence, "load_env", return_value={}):
        rc = evidence.main([cmd, "--q", "전파", "--out", str(out), "--cache-dir", str(tmp_cache)])
    assert rc == 0 and seen["kind"] == kind
    assert json.loads(out.read_text(encoding="utf-8").strip())["source"] == "x"


# ─────────────────────────── 공통 약속 ───────────────────────────
@pytest.mark.parametrize("cls,env,kind", [
    (KosisSource, {"KOSIS_API_KEY": "k"}, "stats"),
    (EcosSource, {"ECOS_API_KEY": "k"}, "stats"),
    (DataGoKrSource, {"DATA_GO_KR_API_KEY": "k"}, "stats"),
    (LawGoKrSource, {"LAW_GO_KR_OC": "k"}, "law"),
    (AssemblySource, {"ASSEMBLY_API_KEY": "k"}, "bills"),
])
def test_class_attributes_match_catalog(cls, env, kind, tmp_cache):
    from scripts.sources.catalog import CATALOG
    c = next(c for c in CATALOG if c["name"] == cls.name)
    assert (cls.tier, cls.kind, cls.env_vars) == (c["tier"], kind, c["env_vars"])
    assert cls.default_grade == "A"            # 정부·공공기관 1차 출처
    assert cls(env, HttpClient(tmp_cache)).is_configured() is True
    assert cls({}, HttpClient(tmp_cache)).is_configured() is False


# ── KOSIS 분류축 자동 맞춤 ────────────────────────────────────────────────
# 통계표마다 분류축(objL) 개수가 다른데, 검색 결과에는 그 개수가 나오지 않는다.
# 모자라면 err 20, 넘치면 err 21 이라 호출하는 쪽이 맞힐 방법이 없다.
# 그래서 전부 "ALL" 로 맡긴 경우에는 커넥터가 스스로 늘려 가며 맞춘다.
def test_kosis_fetch_series_finds_axis_count_by_itself(tmp_cache):
    s = _kosis(tmp_cache)
    axis_counts = []

    def fake(url, params=None, **kw):
        axis_counts.append(len([k for k in (params or {}) if k.startswith("objL")]))
        if axis_counts[-1] < 2:
            return json.dumps({"err": "20", "errMsg": "축 부족"}, ensure_ascii=False)
        return KOSIS_DATA

    with patch.object(s.http, "get_text", side_effect=fake):
        rows = s.fetch_series("101", "DT_1IN1502", obj_l=("ALL",), newest_count=1)
    assert axis_counts == [1, 2]          # 1개로 물어보고, 모자라니 2개로 다시 물어봤다
    assert rows and rows[0].extra["value"] == "51234567"


def test_kosis_does_not_guess_when_axes_are_given_explicitly(tmp_cache):
    """축 값을 직접 지정하면 뜻이 바뀌므로 임의로 늘리지 않고 그대로 알려 준다."""
    s = _kosis(tmp_cache)
    err20 = json.dumps({"err": "20", "errMsg": "축 부족"}, ensure_ascii=False)
    with patch.object(s.http, "get_text", return_value=err20) as g:
        with pytest.raises(RuntimeError, match="분류축"):
            s.fetch_series("101", "DT_1IN1502", obj_l=("13102871A",), newest_count=1)
    assert g.call_count == 1


def test_kosis_axis_search_stops_at_the_limit(tmp_cache):
    """objL 은 8개까지다. 계속 모자라다고 하면 8번에서 멈추고 사유를 알려 준다."""
    s = _kosis(tmp_cache)
    err20 = json.dumps({"err": "20", "errMsg": "축 부족"}, ensure_ascii=False)
    with patch.object(s.http, "get_text", return_value=err20) as g:
        with pytest.raises(RuntimeError, match="늘려 봤습니다"):
            s.fetch_series("101", "DT_1IN1502", obj_l=("ALL",), newest_count=1)
    assert g.call_count == 8
