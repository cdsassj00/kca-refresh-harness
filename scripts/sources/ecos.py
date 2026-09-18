"""한국은행 ECOS(경제통계시스템) Open API. 거시지표 시계열.

확인한 공식 문서
  - 포털·개발가이드: https://ecos.bok.or.kr/api/  (개발명세서는 포털에서 내려받는 PDF)

주소 규칙 — **인증키가 질의 문자열이 아니라 경로에 들어간다.**
  https://ecos.bok.or.kr/api/{서비스명}/{인증키}/{json|xml}/{kr|en}/{시작건수}/{종료건수}/...
  예) .../StatisticSearch/{키}/json/kr/1/100/{통계표코드}/{주기}/{시작일자}/{종료일자}/{항목코드1}
  그래서 캐시에 키가 남지 않도록 `cache_url`(키를 KEY 로 가린 주소)을 함께 넘긴다.

응답
  성공: {"StatisticSearch": {"list_total_count": N, "row": [ ... ]}}
  실패: {"RESULT": {"CODE": "INFO-100", "MESSAGE": "..."}}
"""
from __future__ import annotations

import json

from .base import BaseSource

BASE = "https://ecos.bok.or.kr/api"
PORTAL = "https://ecos.bok.or.kr/"  # 사람이 보는 공개 화면(통계표별 고정 주소는 미확인)

# 결과 코드 → 한국어 설명.
# 미확인: 공식 개발명세서 PDF 를 화면으로 확인하지 못했다. 아래는 ECOS 안내와 여러 공개 구현에서
#         반복 확인되는 값이며, 표에 없는 코드는 서버가 준 MESSAGE 를 그대로 보여 준다.
CODE_KO = {
    "INFO-000": "정상 처리되었습니다",
    "INFO-100": "인증키가 유효하지 않습니다. ECOS 에서 발급받은 값을 확인하세요",
    "INFO-200": "조건에 맞는 자료가 없습니다(오류가 아니라 0건입니다)",
    "ERROR-100": "필수 값(인증키 등)이 빠졌습니다",
    "ERROR-101": "주기와 날짜 형식이 맞지 않습니다(연 YYYY · 분기 YYYYQn · 월 YYYYMM · 일 YYYYMMDD)",
    "ERROR-200": "파일 형식이 잘못되었습니다",
    "ERROR-300": "필수 요청 변수가 빠졌습니다",
    "ERROR-301": "주기 값이 잘못되었습니다",
    "ERROR-400": "데이터베이스 조회에 실패했습니다",
    "ERROR-500": "서버 오류입니다. 잠시 뒤 다시 하세요",
    "ERROR-600": "데이터베이스 연결에 실패했습니다",
    "ERROR-601": "조회 문장에 오류가 있습니다",
    "ERROR-602": "호출이 너무 잦습니다(일일 한도 초과). 잠시 뒤 다시 하세요",
}


def _to_iso(t: str | None) -> str | None:
    """ECOS 시점(2024 · 2024Q3 · 202412 · 20241231)을 ISO 날짜로. 못 읽으면 None."""
    s = (t or "").strip().upper()
    if len(s) == 4 and s.isdigit():
        return f"{s}-12-31"
    if len(s) == 6 and s[:4].isdigit() and s[4] == "Q":
        return f"{s[:4]}-{('03', '06', '09', '12')[int(s[5]) - 1]}-01" if s[5] in "1234" else None
    if len(s) == 6 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-01" if "01" <= s[4:6] <= "12" else None
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


class EcosSource(BaseSource):
    name = "ecos"
    tier = "T1"
    kind = "stats"
    env_vars = ["ECOS_API_KEY"]
    default_grade = "A"  # 한국은행 1차 자료

    # ── 공통 -----------------------------------------------------------------
    def _call(self, service: str, *parts) -> dict:
        """ECOS 호출. 항상 dict 를 돌려준다(오류면 {"RESULT": {...}}).

        ECOS 는 **자리로 뜻을 정하는** 주소라서 중간을 비우면 뒤가 밀려 엉뚱한 값이 된다.
        그래서 None 만 걸러내고 나머지는 받은 차례 그대로 이어 붙인다.
        """
        key = self.env.get("ECOS_API_KEY", "")
        tail = "/".join(str(p) for p in parts if p is not None)
        url = f"{BASE}/{service}/{key}/json/kr/{tail}"
        safe = f"{BASE}/{service}/KEY/json/kr/{tail}"  # 캐시에는 키를 지운 주소만 남긴다
        text = self.http.get_text(url, cache_url=safe)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"RESULT": {"CODE": "PARSE", "MESSAGE": (text or "")[:200]}}
        return data if isinstance(data, dict) else {"RESULT": {"CODE": "PARSE", "MESSAGE": "예상 밖의 응답"}}

    @staticmethod
    def _result_text(data: dict) -> tuple[str, str]:
        r = data.get("RESULT") or {}
        code = str(r.get("CODE") or r.get("Code") or "")
        msg = r.get("MESSAGE") or r.get("Message") or ""
        return code, CODE_KO.get(code, msg or f"알 수 없는 응답({code})")

    @staticmethod
    def _rows(data: dict, service: str) -> list:
        body = data.get(service) or {}
        rows = body.get("row") if isinstance(body, dict) else None
        return rows if isinstance(rows, list) else []

    # ── 통계표 찾기 -----------------------------------------------------------
    def search(self, query, since=None, until=None, limit=20):
        """검색어로 통계표를 찾는다. 레코드 하나 = 통계표 하나.

        ECOS 에는 통계표 이름 검색 API 가 따로 없다. 그래서 통계표 목록(StatisticTableList)을
        받아 이름에 검색어가 든 것만 남긴다. `since`/`until` 은 이 단계에서 쓸 수 있는
        수록기간 정보가 없어 적용하지 않고, `fetch_series` 에서 기간으로 거른다.
        """
        data = self._call("StatisticTableList", 1, max(limit * 20, 200))
        if "StatisticTableList" not in data:
            code, msg = self._result_text(data)
            if code == "INFO-200":
                return []
            raise RuntimeError(f"ECOS 통계표 목록 실패: {msg}")
        q = (query or "").strip()
        out = []
        for r in self._rows(data, "StatisticTableList"):
            name = (r.get("STAT_NAME") or "").strip()
            code = str(r.get("STAT_CODE") or "")
            if q and q not in name:
                continue
            out.append(self.record(
                id=code, url=PORTAL, title=name, date=None,
                snippet=f"{code} {name} (주기 {r.get('CYCLE') or '?'} · 출처 {r.get('ORG_NAME') or '한국은행'})",
                query=query,
                extra={
                    "통계표코드": code, "주기": r.get("CYCLE"), "시점": None, "값": None,
                    "단위": None, "통계명": name, "상위통계표코드": r.get("P_STAT_CODE"),
                    "검색가능여부": r.get("SRCH_YN"), "출처": r.get("ORG_NAME"),
                    "레코드종류": "통계표",
                    "url_종류": "포털 첫 화면(통계표별 공개 주소 형식은 미확인)",
                    "시계열_조회법": {"메서드": "fetch_series", "통계표코드": code},
                }))
            if len(out) >= limit:
                break
        return out

    # ── 시계열 ---------------------------------------------------------------
    def fetch_series(self, stat_code, cycle="A", start=None, end=None,
                     item_codes=(), limit=1000, query=""):
        """통계표의 시점별 값을 받는다. 레코드 하나 = 관측치 하나.

        cycle: A(연) · Q(분기) · M(월) · SM(반월) · D(일).
        start/end 는 주기에 맞춘 형식(연 2015 · 분기 2015Q1 · 월 201501 · 일 20150101)이며
        주소의 자리로 뜻이 정해지므로 **둘 다 있어야 한다.**
        item_codes 는 통계항목코드 1~4개. 비우면 통계표 전체를 부른다.
        """
        if not start or not end:
            raise ValueError("ECOS 통계 조회는 검색 시작일자와 종료일자가 둘 다 있어야 합니다")
        parts = [1, limit, stat_code, cycle, start, end, *[c for c in list(item_codes)[:4] if c]]
        data = self._call("StatisticSearch", *parts)
        if "StatisticSearch" not in data:
            code, msg = self._result_text(data)
            if code == "INFO-200":
                return []
            raise RuntimeError(f"ECOS 통계 조회 실패: {msg}")
        out = []
        for r in self._rows(data, "StatisticSearch"):
            t = str(r.get("TIME") or "")
            items = [r.get(f"ITEM_NAME{i}") for i in (1, 2, 3, 4) if r.get(f"ITEM_NAME{i}")]
            out.append(self.record(
                id=f"{r.get('STAT_CODE') or stat_code}/{'-'.join(str(r.get(f'ITEM_CODE{i}') or '') for i in (1, 2, 3, 4)).strip('-')}/{t}",
                url=PORTAL,
                title=" · ".join(str(x) for x in [r.get("STAT_NAME") or stat_code, *items]),
                date=_to_iso(t),
                snippet=f"{t} {r.get('DATA_VALUE')} {r.get('UNIT_NAME') or ''}".strip(),
                query=query or str(stat_code),
                extra={
                    "통계표코드": str(r.get("STAT_CODE") or stat_code),
                    "주기": cycle, "시점": t or None,
                    "값": r.get("DATA_VALUE"), "단위": r.get("UNIT_NAME"),
                    "통계명": r.get("STAT_NAME"), "항목명": items,
                    "항목코드": [r.get(f"ITEM_CODE{i}") for i in (1, 2, 3, 4) if r.get(f"ITEM_CODE{i}")],
                    "레코드종류": "시계열값",
                    "url_종류": "포털 첫 화면(통계표별 공개 주소 형식은 미확인)",
                }))
        return out[:limit]

    # ── 상태 -----------------------------------------------------------------
    def ping(self):
        data = self._call("StatisticTableList", 1, 1)
        if "StatisticTableList" in data:
            return True, f"OK, 통계표 {len(self._rows(data, 'StatisticTableList'))}건 응답"
        code, msg = self._result_text(data)
        if code == "INFO-200":
            return True, "OK, 키는 정상(자료 0건)"
        return False, msg
