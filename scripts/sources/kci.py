"""KCI(한국학술지인용색인) 논문 기본정보 OpenAPI.

발간 이후에 나온 **국내 학술 논문**을 찾는 데 쓴다. 제목 검색과 발행년월 범위를
함께 줄 수 있어, "이 보고서가 나온 뒤 같은 주제로 무엇이 발표됐나"를 묻기에 맞는다.

창구가 둘이라 헷갈리기 쉽다.
  - **여기(KCI 자체 OpenAPI)** `KCI_API_KEY`. 제목·초록·키워드로 **검색**이 된다. 응답은 XML.
  - 공공데이터포털 경유(`DATA_GO_KR_API_KEY`)는 논문 서지가 아니라 원문 매핑 목록이 와서
    후속 문헌 조사에는 쓸 수 없다. 논문은 이쪽을 쓴다.

확인한 공식 명세(요청 변수·응답 구조·오류 문구)는 `docs/api_specs.md` 2절에 정리해 두었다.
  요청 https://open.kci.go.kr/po/openapi/openApiSearch.kci?apiCode=articleSearch&key=...&title=...
  출력 MetaData > outputData > result/total, record* > journalInfo + articleInfo

미확인: 실제 호출로 응답을 확인하지 못했다(키 미발급). 아래 파싱은 공식 명세 기준이며,
        구조가 달라도 죽지 않도록 `.//` 로 느슨하게 찾고 없는 값은 비워 둔다.
미확인: title 과 keyword 를 함께 주면 AND 인지 OR 인지 모른다. 함께 보내면 결과가
        지나치게 좁아질 수 있어 **title 만** 보낸다.
"""
from __future__ import annotations

import re

from defusedxml import ElementTree as ET

from .base import BaseSource

API = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
ARTICLE_PAGE = "https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId="

MAX_DISPLAY = 100  # 명세상 한 번에 받을 수 있는 최대 건수

# 서버가 오류일 때 돌려주는 안내 문구. 구조가 아니라 문구로 알아본다(명세에 XML 구조가 없다).
ERROR_PHRASES = (
    "등록되지 않은 key",
    "사용기간이 종료",
    "등록되지 않은 서비스",
    "검색 조건이 없습니다",
    "필수 요청 파라미터",
    "범위가 맞지 않습니다",
)


def _yyyymm(d) -> str | None:
    """`2023-01-01`·`202301`·`2023` 을 KCI 가 받는 6자리 `YYYYMM` 으로. 못 읽으면 None."""
    s = re.sub(r"[^0-9]", "", str(d or ""))
    if len(s) >= 6:
        return s[:6]
    if len(s) == 4:
        return s + "01"
    return None


def _text(node, path: str) -> str:
    """하위 요소의 글자를 꺼낸다. 없으면 빈 문자열."""
    if node is None:
        return ""
    el = node.find(path)
    return (el.text or "").strip() if el is not None and el.text else ""


def _pick_lang(node, path: str, prefer=("original", "korean")) -> str:
    """제목·초록처럼 언어별로 여러 개 오는 요소에서 하나를 고른다.

    우리 산출물이 한국어이므로 원문(한국어)을 먼저 쓰고, 없으면 아무거나 첫 번째를 쓴다.
    """
    if node is None:
        return ""
    els = node.findall(path)
    if not els:
        return ""
    by_lang = {(e.get("lang") or "").lower(): (e.text or "").strip() for e in els}
    for lang in prefer:
        if by_lang.get(lang):
            return by_lang[lang]
    for e in els:
        if e.text and e.text.strip():
            return e.text.strip()
    return ""


class KciSource(BaseSource):
    name = "kci"
    tier = "T1"
    kind = "papers"
    env_vars = ["KCI_API_KEY"]
    default_grade = "A"  # 등재 학술지에 실린 논문 서지. 1차 자료로 본다

    # ── 공통 -----------------------------------------------------------------
    def _call(self, params: dict):
        """XML 을 받아 뿌리 요소를 돌려준다. 오류 문구가 보이면 그대로 알려 준다."""
        p = {"apiCode": "articleSearch", "key": self.env.get("KCI_API_KEY", "")}
        p.update({k: v for k, v in params.items() if v not in (None, "")})
        body = self.http.get_text(API, params=p)
        for phrase in ERROR_PHRASES:
            if phrase in body:
                raise RuntimeError(f"KCI 가 거절했습니다: {self._error_line(body, phrase)}")
        try:
            return ET.fromstring(body)
        except ET.ParseError as e:
            raise RuntimeError(f"KCI 응답이 XML 이 아닙니다({e}). 키와 apiCode 를 확인하세요") from e

    @staticmethod
    def _error_line(body: str, phrase: str) -> str:
        """오류 문구가 들어 있는 한 줄을 꺼내 사람에게 그대로 보여 준다."""
        for line in body.splitlines():
            if phrase in line:
                return re.sub(r"<[^>]+>", " ", line).strip()[:120]
        return phrase

    # ── 논문 검색 -------------------------------------------------------------
    def search(self, query, since=None, until=None, limit=20):
        """논문 **제목**으로 찾는다. 레코드 하나 = 논문 하나.

        `since`/`until` 은 **발행년월** 기준이며 서버에 `dateFrom`/`dateTo`(YYYYMM)로 보낸다.
        서버 필터가 안 먹어도 결과가 어긋나지 않게 받아 온 뒤 한 번 더 거른다.
        """
        if not (query or "").strip():
            raise ValueError("KCI 는 제목 검색어가 반드시 있어야 합니다(title 이 필수 변수)")
        root = self._call({
            "title": query,
            "dateFrom": _yyyymm(since),
            "dateTo": _yyyymm(until),
            "page": 1,
            "displayCount": min(max(limit, 1), MAX_DISPLAY),
        })
        lo, hi = _yyyymm(since), _yyyymm(until)
        out = []
        for rec in root.findall(".//record"):
            j, a = rec.find("journalInfo"), rec.find("articleInfo")
            if a is None:
                continue
            ym = (_text(j, "pub-year") + _text(j, "pub-mon").zfill(2)) if j is not None else ""
            ym = ym if len(ym) == 6 else ""
            if ym and ((lo and ym < lo) or (hi and ym > hi)):
                continue
            cc = a.find("citation-count")
            url = _text(a, "url")
            art_id = (a.get("article-id") or "").strip()
            out.append(self.record(
                id=art_id,
                url=url or (ARTICLE_PAGE + art_id if art_id else API),
                title=_pick_lang(a, "title-group/article-title"),
                date=f"{ym[:4]}-{ym[4:]}" if ym else (_text(j, "pub-year") or None),
                snippet=_pick_lang(a, "abstract-group/abstract")[:1000],
                query=query,
                extra={
                    "doi": _text(a, "doi") or None,
                    "uci": _text(a, "uci") or None,
                    "저자": ", ".join(
                        (e.text or "").strip() for e in a.findall("author-group/author") if e.text),
                    "학술지명": _text(j, "journal-name"),
                    "발행기관": _text(j, "publisher-name"),
                    "권": _text(j, "volume"), "호": _text(j, "issue"),
                    "쪽": "-".join(x for x in [_text(a, "fpage"), _text(a, "lpage")] if x),
                    "연구분야": _text(a, "article-categories"),
                    "피인용_KCI": (cc.get("kci") if cc is not None else None),
                    "피인용_WOS": (cc.get("wos") if cc is not None else None),
                    "확인여부": _text(a, "verified"),
                    "레코드종류": "논문",
                }))
        return out[:limit]

    # ── 상태 -----------------------------------------------------------------
    def ping(self):
        if not self.env.get("KCI_API_KEY"):
            return False, "KCI_API_KEY 가 비어 있습니다"
        try:
            root = self._call({"title": "전파", "displayCount": 1})
        except (RuntimeError, ValueError) as e:
            return False, str(e)
        total = _text(root, ".//result/total") or _text(root, ".//total")
        if not root.findall(".//record") and not total:
            return False, "응답에 record 도 total 도 없습니다. 키와 서비스 승인 상태를 확인하세요"
        return True, f"OK, 총 {total or '?'}건 검색"
