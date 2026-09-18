"""KOSIS 국가통계포털 공유서비스(OpenAPI). 통계표 검색 + 통계자료 시계열.

확인한 공식 문서
  - 통계자료:     https://kosis.kr/openapi/devGuide/devGuide_0201List.do
  - KOSIS통합검색: https://kosis.kr/openapi/devGuide/devGuide_0701List.do
  - 개발가이드 PDF: https://kosis.kr/openapi/file/openApi_manual_v1.0.pdf

기억할 점 세 가지
  1. `jsonVD=Y` 를 빼면 따옴표 없는 자바스크립트 객체가 돌아와 JSON 으로 못 읽는다.
  2. 성공이든 실패든 HTTP 200 이다. 성공은 **배열**, 실패는 `{"err":..., "errMsg":...}` **객체**.
  3. 통계자료(statisticsParameterData)는 분류축(objL1~objL8) 개수가 통계표의 축 수와
     정확히 같아야 한다. 모자라면 err 20, 넘치면 err 21.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from .base import BaseSource

SEARCH_API = "https://kosis.kr/openapi/statisticsSearch.do"          # KOSIS통합검색
DATA_API = "https://kosis.kr/openapi/Param/statisticsParameterData.do"  # 통계자료(통계표선택)
TABLE_PAGE = "https://kosis.kr/statHtml/statHtml.do"                 # 사람이 보는 통계표 화면

# 오류 코드 → 한국어 설명.
# 미확인: 공식 PDF 의 전체 코드표를 화면으로 확인하지 못했다. 아래는 개발가이드·현장 사례에서
#         반복 확인되는 값이며, 표에 없는 코드는 원문 errMsg 를 그대로 보여 준다.
ERR_KO = {
    "10": "인증키가 올바르지 않습니다. KOSIS 에서 발급받은 값을 그대로 넣었는지 확인하세요",
    "11": "인증키가 만료되었거나 아직 승인되지 않았습니다",
    "20": "분류축(objL) 개수가 통계표의 축 수보다 모자랍니다",
    "21": "분류축(objL) 개수가 통계표의 축 수보다 많습니다",
    "30": "조건에 맞는 자료가 없습니다(오류가 아니라 0건입니다)",
    "31": "한 번에 요청할 수 있는 셀 4만 개를 넘었습니다. 기간을 나눠 부르세요",
    "40": "분당 호출 한도(200회)를 넘었습니다. 잠시 뒤 다시 하세요",
    "42": "이 인증키에는 해당 서비스 권한이 없습니다",
}


def _to_iso(prd_de: str | None) -> str | None:
    """KOSIS 수록시점(2024 · 202412 · 20241231)을 ISO 날짜로. 못 읽으면 None."""
    s = (prd_de or "").strip()
    if len(s) == 4 and s.isdigit():
        return f"{s}-12-31"
    if len(s) == 6 and s.isdigit():
        m = s[4:6]
        # 분기(Q1~Q4)가 아니라 월이면 그 달의 말일 대신 1일로 둔다(월 단위 비교면 충분).
        return f"{s[:4]}-{m}-01" if "01" <= m <= "12" else f"{s[:4]}-12-31"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


class KosisSource(BaseSource):
    name = "kosis"
    tier = "T1"
    kind = "stats"
    env_vars = ["KOSIS_API_KEY"]
    default_grade = "A"  # 통계청 1차 자료

    # ── 공통 -----------------------------------------------------------------
    def _call(self, url: str, params: dict):
        """KOSIS 호출. 성공이면 list, 실패면 {"err":..,"errMsg":..} 를 돌려준다."""
        # method=getList 는 KOSIS 가 주소에 붙여 안내하는 고정 값이다. 빠지면 아무것도 안 온다.
        p = {"method": "getList", "apiKey": self.env.get("KOSIS_API_KEY", ""),
             "format": "json", "jsonVD": "Y"}
        p.update({k: v for k, v in params.items() if v not in (None, "")})
        text = self.http.get_text(url, params=p)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # jsonVD 가 먹지 않았거나 점검 안내 HTML 이 온 경우.
            return {"err": "parse", "errMsg": (text or "")[:200]}
        if isinstance(data, dict):
            return data  # 오류 객체
        return data if isinstance(data, list) else []

    @staticmethod
    def _err_text(obj: dict) -> str:
        code = str(obj.get("err", ""))
        return ERR_KO.get(code, obj.get("errMsg") or f"알 수 없는 오류(err={code})")

    @staticmethod
    def _table_url(org_id: str, tbl_id: str) -> str:
        return f"{TABLE_PAGE}?{urlencode({'orgId': org_id, 'tblId': tbl_id})}"

    # ── 통계표 검색 -----------------------------------------------------------
    def search(self, query, since=None, until=None, limit=20):
        """검색어로 통계표를 찾는다. 레코드 하나 = 통계표 하나.

        KOSIS통합검색에는 기간 필터가 없다. 그래서 `since`/`until` 은 **수록기간이 겹치는
        통계표만 남기는** 조건으로 쓴다(끝시점 < since 이면 버리고, 시작시점 > until 이면 버린다).
        """
        rows = self._call(SEARCH_API, {
            "searchNm": query, "sort": "RANK",
            "startCount": 1, "resultCount": min(max(limit, 1), 100),
        })
        if isinstance(rows, dict):
            if str(rows.get("err")) == "30":
                return []
            raise RuntimeError(f"KOSIS 검색 실패: {self._err_text(rows)}")
        out = []
        for r in rows:
            org_id, tbl_id = str(r.get("ORG_ID") or ""), str(r.get("TBL_ID") or "")
            strt, end = str(r.get("STRT_PRD_DE") or ""), str(r.get("END_PRD_DE") or "")
            end_iso, strt_iso = _to_iso(end), _to_iso(strt)
            if since and end_iso and end_iso < since:
                continue
            if until and strt_iso and strt_iso > until:
                continue
            out.append(self.record(
                id=f"{org_id}/{tbl_id}" if tbl_id else (r.get("STAT_ID") or ""),
                url=self._table_url(org_id, tbl_id) if tbl_id else (r.get("TBL_VIEW_URL") or TABLE_PAGE),
                title=(r.get("TBL_NM") or r.get("STAT_NM") or "").strip(),
                date=end_iso,
                snippet=(r.get("CONTENTS") or r.get("STAT_NM") or "")[:1000],
                query=query,
                extra={
                    "tbl_id": tbl_id, "org_id": org_id, "org_nm": r.get("ORG_NM"),
                    "stat_id": r.get("STAT_ID"), "stat_nm": r.get("STAT_NM"),
                    "strt_prd_de": strt or None, "end_prd_de": end or None,
                    "레코드종류": "통계표",
                    # 시점별 값은 아래 fetch_series 로 받는다. 통계표마다 분류축(objL) 개수와
                    # 항목(itmId)이 달라 검색 결과만으로는 자동으로 부를 수 없다.
                    "시계열_조회법": {"메서드": "fetch_series", "org_id": org_id, "tbl_id": tbl_id},
                }))
        return out[:limit]

    # ── 시계열 ---------------------------------------------------------------
    def fetch_series(self, org_id, tbl_id, itm_id="ALL", obj_l=("ALL",), prd_se="Y",
                     start_prd_de=None, end_prd_de=None, newest_count=None,
                     limit=1000, query=""):
        """통계표의 시점별 수치를 받는다. 레코드 하나 = 셀 하나(시점 × 항목 × 분류).

        obj_l: 분류축 값의 차례(objL1, objL2, ...). 통계표의 축 수와 개수가 같아야 한다.
        기간은 start_prd_de~end_prd_de(예: "2015"~"2025") 또는 newest_count(최근 n개) 중 하나.
        """
        p = {"orgId": org_id, "tblId": tbl_id, "itmId": itm_id, "prdSe": prd_se,
             "startPrdDe": start_prd_de, "endPrdDe": end_prd_de,
             "newEstPrdCnt": newest_count}
        for i, v in enumerate(obj_l or (), start=1):
            p[f"objL{i}"] = v
        rows = self._call(DATA_API, p)
        if isinstance(rows, dict):
            if str(rows.get("err")) == "30":
                return []
            raise RuntimeError(f"KOSIS 통계자료 실패: {self._err_text(rows)}")
        url = self._table_url(str(org_id), str(tbl_id))
        cls_names = [f"C{i}_NM" for i in range(1, 9)]
        out = []
        for r in rows:
            prd_de = str(r.get("PRD_DE") or "")
            itm_nm = (r.get("ITM_NM") or "").strip()
            cls = [str(r[k]) for k in cls_names if r.get(k)]
            title_bits = [(r.get("TBL_NM") or tbl_id)] + cls + ([itm_nm] if itm_nm else [])
            out.append(self.record(
                id=f"{org_id}/{tbl_id}/{prd_de}/{r.get('ITM_ID') or ''}/{'-'.join(cls)}",
                url=url,
                title=" · ".join(str(b) for b in title_bits if b),
                date=_to_iso(prd_de),
                snippet=f"{prd_de} {itm_nm} {r.get('DT')} {r.get('UNIT_NM') or ''}".strip(),
                query=query or f"{org_id}/{tbl_id}",
                extra={
                    "tbl_id": str(tbl_id), "prd_de": prd_de or None, "itm_nm": itm_nm or None,
                    "unit": r.get("UNIT_NM"), "value": r.get("DT"),
                    "org_id": str(org_id), "itm_id": r.get("ITM_ID"),
                    "prd_se": r.get("PRD_SE") or prd_se, "분류": cls,
                    "최종수정일": r.get("LST_CHN_DE"), "레코드종류": "시계열값",
                }))
        return out[:limit]

    # ── 상태 -----------------------------------------------------------------
    def ping(self):
        rows = self._call(SEARCH_API, {"searchNm": "인구", "sort": "RANK",
                                       "startCount": 1, "resultCount": 1})
        if isinstance(rows, dict):
            if str(rows.get("err")) == "30":
                return True, "OK, 키는 정상(검색 결과 0건)"
            return False, self._err_text(rows)
        return True, f"OK, 통계표 검색 {len(rows)}건 응답"
