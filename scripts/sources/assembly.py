"""열린국회정보 Open API. 의안 발의·처리 추적(제언이 법안이 됐는지 본다).

확인한 공식 문서
  - 포털·인증키:   https://open.assembly.go.kr/portal/openapi/main.do
  - 사용방법:      https://open.assembly.go.kr/portal/openapi/openApiDevPage.do
                  (공통 인자 KEY·Type·pIndex·pSize, Type 기본값은 xml)
  - 국회의원 발의법률안(nzmimeepazxkubdpn) 요청·출력 필드:
      https://gittykite.github.io/python/billcrawling/ 의 정리 및 포털 상세화면
      출력 BILL_ID BILL_NO BILL_NAME COMMITTEE PROPOSE_DT PROC_RESULT AGE
           DETAIL_LINK PROPOSER MEMBER_LIST RST_PROPOSER PUBL_PROPOSER COMMITTEE_ID

주소 규칙
  https://open.assembly.go.kr/portal/openapi/{서비스명}?KEY=..&Type=json&pIndex=1&pSize=100
응답(json)
  {"<서비스명>": [{"head": [{"list_total_count": N}, {"RESULT": {"CODE": "..", "MESSAGE": ".."}}]},
                  {"row": [ ... ]}]}
  자료가 없거나 오류면 {"RESULT": {"CODE": "..", "MESSAGE": ".."}} 만 온다.
"""
from __future__ import annotations

import json
import re

from .base import BaseSource

BASE = "https://open.assembly.go.kr/portal/openapi/"
BILL_SERVICE = "nzmimeepazxkubdpn"  # 국회의원 발의법률안
PORTAL = "https://open.assembly.go.kr/portal/openapi/main.do"

# 결과 코드 → 한국어 설명.
# 미확인: 포털의 결과코드 표를 화면으로 확인하지 못했다(안내 페이지가 표를 내주지 않는다).
#         아래는 열린국회정보 응답에서 반복 확인되는 값이며, 표에 없으면 MESSAGE 를 그대로 쓴다.
CODE_KO = {
    "INFO-000": "정상 처리되었습니다",
    "INFO-100": "인증키가 유효하지 않습니다. 열린국회정보에서 발급받은 값을 확인하세요",
    "INFO-200": "조건에 맞는 자료가 없습니다(오류가 아니라 0건입니다)",
    "INFO-300": "유효하지 않은 값이 들어 있습니다",
    "ERROR-290": "인증키가 비활성 상태입니다. 포털에서 상태를 확인하세요",
    "ERROR-300": "필수 요청 변수가 빠졌습니다",
    "ERROR-333": "요청 위치 값의 형식이 맞지 않습니다",
    "ERROR-336": "한 번에 1,000건을 넘게 요청할 수 없습니다",
    "ERROR-337": "일별 호출 한도를 넘었습니다. 내일 다시 하세요",
    "ERROR-500": "서버 오류입니다. 잠시 뒤 다시 하세요",
    "ERROR-600": "데이터베이스 연결에 실패했습니다",
    "ERROR-601": "조회 문장에 오류가 있습니다",
}


def _to_iso(d) -> str | None:
    s = re.sub(r"[^0-9]", "", str(d or ""))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


class AssemblySource(BaseSource):
    name = "assembly"
    tier = "T1"
    kind = "bills"
    env_vars = ["ASSEMBLY_API_KEY"]
    default_grade = "A"  # 국회사무처 1차 자료

    # ── 공통 -----------------------------------------------------------------
    def _call(self, service: str, params: dict) -> dict:
        p = {"KEY": self.env.get("ASSEMBLY_API_KEY", ""), "Type": "json",
             "pIndex": 1, "pSize": 100}
        p.update({k: v for k, v in params.items() if v not in (None, "")})
        text = self.http.get_text(BASE + service, params=p)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"RESULT": {"CODE": "PARSE", "MESSAGE": (text or "")[:200]}}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _result(data: dict, service: str) -> tuple[str, str]:
        """결과 코드와 한국어 설명을 뽑는다."""
        r = data.get("RESULT")
        if not isinstance(r, dict):
            for blk in data.get(service) or []:
                for h in (blk or {}).get("head") or []:
                    if isinstance(h, dict) and isinstance(h.get("RESULT"), dict):
                        r = h["RESULT"]
                        break
        r = r if isinstance(r, dict) else {}
        code = str(r.get("CODE") or "")
        return code, CODE_KO.get(code, r.get("MESSAGE") or f"알 수 없는 응답({code or '코드 없음'})")

    @staticmethod
    def _rows(data: dict, service: str) -> list:
        for blk in data.get(service) or []:
            rows = (blk or {}).get("row")
            if isinstance(rows, list):
                return rows
        return []

    # ── 의안 검색 -------------------------------------------------------------
    def search(self, query, since=None, until=None, limit=20, age=None):
        """의안명으로 발의법률안을 찾는다. 레코드 하나 = 의안 하나.

        `since`/`until` 은 **제안일(PROPOSE_DT)** 기준이며 서버에 기간 필터가 없어
        받아 온 뒤에 거른다. 그래서 요청 건수는 limit 보다 넉넉히 잡는다.
        """
        service = BILL_SERVICE
        data = self._call(service, {"BILL_NAME": query, "AGE": age,
                                    "pSize": min(max(limit * 5, 20), 1000)})
        rows = self._rows(data, service)
        if not rows:
            code, msg = self._result(data, service)
            if code in ("INFO-200", ""):
                return []
            if code == "INFO-000":
                return []
            raise RuntimeError(f"열린국회정보 조회 실패: {msg}")
        out = []
        for r in rows:
            d = _to_iso(r.get("PROPOSE_DT"))
            if since and d and d < since:
                continue
            if until and d and d > until:
                continue
            out.append(self.record(
                id=str(r.get("BILL_ID") or r.get("BILL_NO") or ""),
                url=str(r.get("DETAIL_LINK") or PORTAL),
                title=(r.get("BILL_NAME") or "").strip(),
                date=d,
                snippet=" · ".join(str(x) for x in [
                    f"의안번호 {r.get('BILL_NO')}" if r.get("BILL_NO") else None,
                    f"대표발의 {r.get('RST_PROPOSER')}" if r.get("RST_PROPOSER") else None,
                    r.get("COMMITTEE"), f"처리결과 {r.get('PROC_RESULT') or '계류'}"] if x),
                query=query,
                extra={
                    "의안번호": r.get("BILL_NO"),
                    "제안일": d,
                    "처리결과": r.get("PROC_RESULT"),
                    "대표발의자": r.get("RST_PROPOSER"),
                    "의안ID": r.get("BILL_ID"), "대수": r.get("AGE"),
                    "소관위원회": r.get("COMMITTEE"), "제안자": r.get("PROPOSER"),
                    "공동발의자": r.get("PUBL_PROPOSER"), "처리일": _to_iso(r.get("PROC_DT")),
                    "레코드종류": "의안",
                }))
            if len(out) >= limit:
                break
        return out

    # ── 상태 -----------------------------------------------------------------
    def ping(self):
        data = self._call(BILL_SERVICE, {"pSize": 1})
        code, msg = self._result(data, BILL_SERVICE)
        if self._rows(data, BILL_SERVICE) or code == "INFO-000":
            return True, f"OK, 의안 목록 응답({code or 'INFO-000'})"
        if code == "INFO-200":
            return True, "OK, 키는 정상(자료 0건)"
        return False, msg
