"""KCI 논문 커넥터 검사. 실제 호출은 하지 않는다(모든 응답은 mock).

보는 것
  ① 정상 응답 → 레코드 필드·등급·URL·extra
  ② 근거 레코드 스키마 통과
  ③ 빈 결과
  ④ 키·조건 오류일 때 ping() 이 한국어로 사유를 알려 줌
  ⑤ since/until 이 dateFrom/dateTo(YYYYMM)로 나가고, 범위 밖 논문은 걸러짐
"""
from unittest.mock import patch

import pytest

from scripts.sources.base import HttpClient
from scripts.sources.catalog import CATALOG
from scripts.sources.kci import KciSource
from scripts.validate import validate_obj

XML_OK = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
 <outputData>
  <result><total>2</total></result>
  <record>
   <journalInfo>
    <journal-name>한국통신학회논문지</journal-name>
    <publisher-name>한국통신학회</publisher-name>
    <pub-year>2024</pub-year><pub-mon>3</pub-mon>
    <volume>49</volume><issue>3</issue>
   </journalInfo>
   <articleInfo article-id="ART00301">
    <article-categories>공학 &gt; 전자공학</article-categories>
    <title-group>
     <article-title lang="english">Private 5G Spectrum Policy</article-title>
     <article-title lang="original">이음5G 주파수 정책 연구</article-title>
    </title-group>
    <author-group><author>신성진(중앙대)</author><author>홍길동(KCA)</author></author-group>
    <abstract-group>
     <abstract lang="original">이음5G 주파수 할당 정책의 성과를 분석하였다.</abstract>
     <abstract lang="english">We analyze the outcome.</abstract>
    </abstract-group>
    <fpage>101</fpage><lpage>115</lpage>
    <doi>10.7840/kics.2024.49.3.101</doi>
    <uci>I410-ECN-0101-2024</uci>
    <citation-count kci="7" wos="2"/>
    <url>https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART00301</url>
    <verified>Y</verified>
   </articleInfo>
  </record>
  <record>
   <journalInfo><journal-name>낡은학회지</journal-name><pub-year>2019</pub-year><pub-mon>12</pub-mon></journalInfo>
   <articleInfo article-id="ART00099">
    <title-group><article-title lang="original">옛날 주파수 논문</article-title></title-group>
   </articleInfo>
  </record>
 </outputData>
</MetaData>"""

XML_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><outputData><result><total>0</total></result></outputData></MetaData>"""

XML_BAD_KEY = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><error>등록되지 않은 key 입니다.</error></MetaData>"""


def _kci(tmp_cache, key="KEY-SECRET"):
    return KciSource({"KCI_API_KEY": key}, HttpClient(tmp_cache))


# ① 정상 응답 ② 스키마 -------------------------------------------------------
def test_search_makes_article_record(tmp_cache):
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_OK) as g:
        rows = s.search("주파수", limit=10)
    r = rows[0]
    assert validate_obj(r.to_json(), "evidence_record") == []
    assert r.grade == "A"  # 등재지 논문은 1차 자료
    assert r.source == "kci" and r.id == "ART00301"
    # 한국어 산출물이므로 원문(한국어) 제목·초록을 고른다
    assert r.title == "이음5G 주파수 정책 연구"
    assert r.snippet.startswith("이음5G 주파수 할당")
    assert r.date == "2024-03"  # pub-year + pub-mon(한 자리는 0을 채움)
    assert r.url.startswith("https://www.kci.go.kr/")
    assert r.extra["doi"] == "10.7840/kics.2024.49.3.101"
    assert r.extra["저자"] == "신성진(중앙대), 홍길동(KCA)"
    assert r.extra["학술지명"] == "한국통신학회논문지"
    assert r.extra["쪽"] == "101-115"
    assert r.extra["피인용_KCI"] == "7" and r.extra["피인용_WOS"] == "2"
    # 필수 변수와 키는 질의 문자열로만 나간다(캐시에는 해시로만 남는다)
    p = g.call_args.kwargs["params"]
    assert p["apiCode"] == "articleSearch" and p["key"] == "KEY-SECRET" and p["title"] == "주파수"


def test_url_falls_back_to_article_page_when_missing(tmp_cache):
    """<url> 이 없어도 사람이 볼 수 있는 주소를 만든다."""
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_OK):
        rows = s.search("주파수", limit=10)
    old = next(r for r in rows if r.id == "ART00099")
    assert old.url.endswith("ART00099") and old.url.startswith("http")


# ③ 빈 결과 -------------------------------------------------------------------
def test_empty_result_is_not_an_error(tmp_cache):
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_EMPTY):
        assert s.search("없는주제", limit=5) == []


# ④ 오류 안내 ------------------------------------------------------------------
def test_ping_reports_rejected_key_in_korean(tmp_cache):
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_BAD_KEY):
        ok, detail = s.ping()
    assert ok is False and "등록되지 않은 key" in detail


def test_ping_without_key_says_so(tmp_cache):
    ok, detail = KciSource({}, HttpClient(tmp_cache)).ping()
    assert ok is False and "KCI_API_KEY" in detail


def test_ping_ok_reports_total(tmp_cache):
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_OK):
        ok, detail = s.ping()
    assert ok is True and "2건" in detail


def test_empty_query_is_rejected_before_calling(tmp_cache):
    """title 이 필수라, 주제어 없이 부르면 서버에 가기 전에 막는다."""
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text") as g:
        with pytest.raises(ValueError, match="제목 검색어"):
            s.search("  ")
    g.assert_not_called()


# ⑤ 기간 ----------------------------------------------------------------------
def test_since_until_go_out_as_yyyymm_and_filter_results(tmp_cache):
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_OK) as g:
        rows = s.search("주파수", since="2023-01-01", until="2025-12-31", limit=10)
    p = g.call_args.kwargs["params"]
    assert p["dateFrom"] == "202301" and p["dateTo"] == "202512"
    # 서버 필터를 믿지 않고 한 번 더 거른다 → 2019년 논문은 빠진다
    assert [r.id for r in rows] == ["ART00301"]


def test_year_only_bounds_are_accepted(tmp_cache):
    s = _kci(tmp_cache)
    with patch.object(s.http, "get_text", return_value=XML_OK) as g:
        s.search("주파수", since="2023", limit=10)
    assert g.call_args.kwargs["params"]["dateFrom"] == "202301"


# 카탈로그 ---------------------------------------------------------------------
def test_catalog_entry_matches_class(tmp_cache):
    entry = next(c for c in CATALOG if c["name"] == "kci")
    assert entry["impl"] == "scripts.sources.kci:KciSource"
    assert (entry["tier"], entry["kind"], entry["env_vars"]) == (
        KciSource.tier, KciSource.kind, KciSource.env_vars)
