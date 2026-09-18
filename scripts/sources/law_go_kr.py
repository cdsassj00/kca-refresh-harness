"""법제처 국가법령정보 공동활용 OPEN API. 법령 목록·본문·개정 이력.

확인한 공식 문서
  - 현행법령(공포일) 목록 조회 API:
    https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwListGuide
      요청 http://www.law.go.kr/DRF/lawSearch.do?target=law
      변수 OC(필수) target(필수) type(필수) search query display page sort date efYd
           ancYd ancNo rrClsCd nb org knd lsChapNo gana popYn
      출력 법령일련번호 현행연혁코드 법령명한글 법령약칭명 법령ID 공포일자 공포번호
           제개정구분명 소관부처명 소관부처코드 법령구분명 공동부령구분 시행일자
           자법타법여부 법령상세링크
  - 법령 본문 조회 API:
    https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwInfoGuide
      요청 http://www.law.go.kr/DRF/lawService.do?target=law  (ID 또는 MST 중 하나 필수)

인증값은 긴 키가 아니라 **OC** 라는 짧은 기관 아이디다(open.law.go.kr 의 API인증키관리 화면 값).
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from .base import BaseSource

SEARCH_API = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_API = "https://www.law.go.kr/DRF/lawService.do"
# 사람이 보는 공개 화면. `https://www.law.go.kr/법령/전파법` 을 주소로 남길 때 어디서나 깨지지 않게
# 경로의 한글("법령")까지 미리 퍼센트 인코딩해 둔다.
LAW_PAGE = "https://www.law.go.kr/%EB%B2%95%EB%A0%B9/"


def _to_iso(d) -> str | None:
    """공포일자·시행일자(20240131 또는 2024-01-31)를 ISO 날짜로. 못 읽으면 None."""
    s = re.sub(r"[^0-9]", "", str(d or ""))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


def _mask_oc(link: str | None) -> str | None:
    """법령상세링크에 우리 OC 가 섞여 오면 지운다(키 값을 기록하지 않는다)."""
    if not link:
        return None
    return re.sub(r"(?i)(OC=)[^&]*", r"\1***", str(link))


def _as_list(v) -> list:
    """결과가 1건이면 객체, 여러 건이면 배열로 오는 응답을 한 모양으로 맞춘다."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class LawGoKrSource(BaseSource):
    name = "law_go_kr"
    tier = "T1"
    kind = "law"
    env_vars = ["LAW_GO_KR_OC"]
    default_grade = "A"  # 법제처 1차 자료

    # ── 공통 -----------------------------------------------------------------
    def _call(self, url: str, params: dict) -> dict:
        p = {"OC": self.env.get("LAW_GO_KR_OC", ""), "type": "JSON"}
        p.update({k: v for k, v in params.items() if v not in (None, "")})
        text = self.http.get_text(url, params=p)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # OC 가 틀리거나 승인 전이면 JSON 대신 안내 HTML 이 온다.
            raise RuntimeError(
                "법제처가 JSON 대신 안내 화면을 보냈습니다. OC 값이 맞는지, "
                "OPEN API 신청이 승인됐는지 확인하세요"
            )
        return data if isinstance(data, dict) else {}

    # ── 법령 목록 -------------------------------------------------------------
    def search(self, query, since=None, until=None, limit=20):
        """법령명으로 현행법령을 찾는다. 레코드 하나 = 법령 하나.

        `since`/`until` 은 **시행일자** 기준이다. 서버에도 efYd 범위를 같이 보내고(양끝이 다 있을 때),
        받아 온 뒤에도 한 번 더 거른다(서버 필터가 안 먹어도 결과가 어긋나지 않게).
        """
        p = {"target": "law", "query": query, "display": min(max(limit, 1), 100),
             "page": 1, "sort": "ddes"}
        if since and until:
            p["efYd"] = f"{re.sub(r'[^0-9]', '', since)}~{re.sub(r'[^0-9]', '', until)}"
        rows = _as_list((self._call(SEARCH_API, p).get("LawSearch") or {}).get("law"))
        out = []
        for r in rows:
            ef = _to_iso(r.get("시행일자"))
            if since and ef and ef < since:
                continue
            if until and ef and ef > until:
                continue
            name = (r.get("법령명한글") or "").strip()
            out.append(self.record(
                id=str(r.get("법령ID") or r.get("법령일련번호") or ""),
                url=(LAW_PAGE + quote(name)) if name else SEARCH_API,
                title=name,
                date=ef or _to_iso(r.get("공포일자")),
                snippet=" · ".join(str(x) for x in [
                    r.get("법령구분명"), r.get("소관부처명"), r.get("제개정구분명"),
                    f"시행 {r.get('시행일자')}", f"공포 {r.get('공포일자')}"] if x),
                query=query,
                extra={
                    "법령ID": str(r.get("법령ID") or ""),
                    "시행일자": _to_iso(r.get("시행일자")),
                    "공포일자": _to_iso(r.get("공포일자")),
                    "개정구분": r.get("제개정구분명"),
                    "법령일련번호": str(r.get("법령일련번호") or ""),
                    "법령약칭명": r.get("법령약칭명"), "법령구분명": r.get("법령구분명"),
                    "소관부처명": r.get("소관부처명"), "공포번호": r.get("공포번호"),
                    "현행연혁코드": r.get("현행연혁코드"),
                    "법령상세링크": _mask_oc(r.get("법령상세링크")),
                    "레코드종류": "법령",
                }))
        return out[:limit]

    # ── 법령 본문 -------------------------------------------------------------
    def fetch_law(self, law_id=None, mst=None, query=""):
        """법령 본문을 받는다. 개정 이력을 따라갈 때 쓴다(레코드 1건).

        미확인: 본문 응답의 세부 구조(조문·부칙 배열의 정확한 키)는 화면으로 확인하지 못했다.
                그래서 아는 키만 방어적으로 꺼내고, 없으면 빈 값으로 둔다.
        """
        if not (law_id or mst):
            raise ValueError("법령ID(ID) 또는 법령마스터번호(MST) 중 하나는 있어야 합니다")
        data = self._call(SERVICE_API, {"target": "law", "ID": law_id, "MST": mst})
        body = data.get("법령") or data.get("Law") or data
        basic = body.get("기본정보") if isinstance(body, dict) else {}
        basic = basic if isinstance(basic, dict) else {}
        name = str(basic.get("법령명_한글") or basic.get("법령명한글") or "").strip()
        jo = body.get("조문") if isinstance(body, dict) else None
        texts = []
        for unit in _as_list((jo or {}).get("조문단위") if isinstance(jo, dict) else jo):
            if isinstance(unit, dict):
                texts.append(str(unit.get("조문내용") or ""))
        return self.record(
            id=str(law_id or mst or ""),
            url=(LAW_PAGE + quote(name)) if name else SERVICE_API,
            title=name or str(law_id or mst),
            date=_to_iso(basic.get("시행일자")) or _to_iso(basic.get("공포일자")),
            snippet=" ".join(" ".join(t.split()) for t in texts)[:1000],
            query=query or str(law_id or mst or ""),
            extra={
                "법령ID": str(basic.get("법령ID") or law_id or ""),
                "시행일자": _to_iso(basic.get("시행일자")),
                "공포일자": _to_iso(basic.get("공포일자")),
                "개정구분": basic.get("제개정구분") or basic.get("제개정구분명"),
                "소관부처명": basic.get("소관부처") or basic.get("소관부처명"),
                "조문수": len(texts), "레코드종류": "법령본문",
            })

    # ── 상태 -----------------------------------------------------------------
    def ping(self):
        if not self.env.get("LAW_GO_KR_OC"):
            return False, "LAW_GO_KR_OC 가 비어 있습니다"
        try:
            data = self._call(SEARCH_API, {"target": "law", "query": "전파법", "display": 1})
        except RuntimeError as e:
            return False, str(e)
        ls = data.get("LawSearch")
        if not isinstance(ls, dict):
            return False, "응답에 LawSearch 가 없습니다. OC 값과 승인 상태를 확인하세요"
        return True, f"OK, 총 {ls.get('totalCnt', '?')}건 검색"
