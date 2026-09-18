"""공공데이터포털(data.go.kr) 오픈API 공통 커넥터.

포털 하나에 API 가 수천 개라 **한 데이터셋만 고정해서는 쓸모가 없다.** 그래서
"요청 규칙이 같고 응답 봉투가 같다"는 점만 공통으로 잡고, 데이터셋은 표(DATASETS)로 둔다.
새 데이터셋은 표에 한 줄 더하면 끝이다.

확인한 공식 문서
  - 한국연구재단_KCI 논문정보서비스: https://www.data.go.kr/data/15085348/openapi.do
      상세기능 https://apis.data.go.kr/B552540/KCIOpenApi/artiInfo/openApiD217List
      요청 ServiceKey(필수) recordCnt(필수) pageNo(필수) artiId(선택) · 응답은 XML
  - 국회사무처_국회의원 발의법률안: https://www.data.go.kr/data/15125946/openapi.do
  - 인증키: 마이페이지 → 데이터활용 → Open API → 인증키 발급현황의 **일반 인증키(Decoding)**
      (활용신청은 API 마다 따로, 인증키는 계정에 하나)

공통 규칙
  - 질의 문자열에 `serviceKey` 를 붙인다. Decoding 키를 쓰면 requests 가 알아서 인코딩한다.
  - 성공/실패 모두 HTTP 200 이 올 수 있다. 실패는 아래 두 가지 봉투 중 하나다.
      <OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode>...
      <response><header><resultCode>03</resultCode><resultMsg>NO_DATA</resultMsg>...
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import defusedxml.ElementTree as ET

from .base import BaseSource

# 기간이 **필수**인 데이터셋(PRISM 등)에 넣을 기본 조회 폭.
# 비워 두면 NO_MANDATORY_REQUEST_PARAMETERS_ERROR 가 온다. 우리 하네스가 다루는 보고서가
# 대개 3년 이상 된 것이라, 발간 이후 후속 발주를 훑기에 3년을 기본으로 둔다.
DEFAULT_WINDOW_YEARS = 3


def _as_date(s):
    """`2023-01-01`·`20230101`·`2023` 을 날짜로. 못 읽으면 None."""
    d = re.sub(r"[^0-9]", "", str(s or ""))
    if len(d) == 4:
        d += "0101"
    try:
        return datetime.strptime(d[:8], "%Y%m%d") if len(d) >= 8 else None
    except ValueError:
        return None


def _window(since, until) -> tuple[str, str]:
    """요청에 넣을 YYYYMMDD 두 개. 안 주셨으면 최근 DEFAULT_WINDOW_YEARS 년."""
    hi = _as_date(until) or datetime.now()
    lo = _as_date(since) or (hi - timedelta(days=365 * DEFAULT_WINDOW_YEARS))
    return f"{lo:%Y%m%d}", f"{hi:%Y%m%d}"

# 포털 공통 오류 코드 → 한국어 설명(공공데이터포털 공통 에러코드).
REASON_KO = {
    "1": "제공기관 시스템 오류입니다",
    "01": "제공기관 시스템 오류입니다",
    "4": "HTTP 오류입니다",
    "12": "폐기되었거나 없는 API 입니다",
    "20": "이 API 에 대한 활용신청이 승인되지 않았습니다. 상세 페이지에서 활용신청을 하세요",
    "22": "요청 한도를 넘었습니다(개발계정 기본 하루 1,000회). 운영계정 전환을 신청하세요",
    "30": "등록되지 않은 인증키입니다. 마이페이지의 **일반 인증키(Decoding)** 를 넣었는지 확인하세요",
    "31": "활용기간이 만료된 인증키입니다",
    "32": "등록되지 않은 IP 입니다",
    "33": "서명되지 않은 호출입니다",
    "99": "알 수 없는 오류입니다",
}
RESULT_KO = {
    "00": "정상 처리되었습니다",
    "03": "조건에 맞는 자료가 없습니다(오류가 아니라 0건입니다)",
    "10": "잘못된 요청 변수입니다",
    "20": "이 API 에 대한 활용신청이 승인되지 않았습니다",
    "22": "요청 한도를 넘었습니다",
    "30": "등록되지 않은 인증키입니다",
    "31": "활용기간이 만료된 인증키입니다",
}

# 데이터셋 표. 한 줄이 API 하나다. 뜻은 이렇다.
#   query_param  검색어를 넣을 요청 변수. None 이면 그 API 는 검색어를 못 받는다(우리가 제목으로 거른다)
#   rows_key     응답이 표준 봉투(response>body>items>item)가 아닐 때, 목록이 들어 있는 최상위 키
#   since/until_param  기간을 넣을 요청 변수(YYYYMMDD)
#   page_size    한 번에 받을 건수. 포털 기본은 100 이고, API 마다 더 받을 수 있다
#   scan_pages   검색어 변수가 없을 때 최대 몇 쪽까지 훑을지(제목 거르기는 우리 쪽에서 하므로
#                훑은 만큼만 찾을 수 있다. 다 훑으면 그 기간은 빠짐없이 본 것이다)
# 미확인: 상세기능의 요청 변수 이름은 포털 화면 기준이며, 제공기관이 바꾸면 여기만 고치면 된다.
DATASETS = {
    "prism_research": {
        # 보고서 발간 뒤 **주무부처가 같은 주제로 후속 연구를 발주했는지** 보는 데 쓴다.
        # 후속 발주 자체가 "그때 결론이 재검토 대상이었다"는 근거가 된다.
        # 실호출로 확인(2026-09-19, docs/api_specs.md 1절). 응답이 표준 봉투가 아니라
        # {"resultCode":"0","totalCount":N,"research":[...]} 꼴이라 rows_key 를 쓴다.
        "이름": "행정안전부_정책연구 과제정보(PRISM)",
        "endpoint": "https://apis.data.go.kr/1741000/prism_v3/getResearchList_v3",
        "portal": "https://www.data.go.kr/data/15080254/openapi.do",
        "key_param": "serviceKey", "page_param": "pageNo", "size_param": "numOfRows",
        "query_param": None,          # 검색어 변수가 없다. 과제명으로 우리가 거른다
        "format_param": "type",       # type=json
        "rows_key": "research",
        "since_param": "start_date", "until_param": "end_date",
        # 실호출로 확인: numOfRows=1000 까지 받는다. 3년치 총계가 1만 2천 건대라
        # 15쪽이면 기간 전체를 덮는다(개발계정 하루 1,000회 한도 안에서 넉넉하다).
        "page_size": 1000, "scan_pages": 15,
    },
    "kci_article": {
        "이름": "한국연구재단_KCI 논문정보서비스",
        "endpoint": "https://apis.data.go.kr/B552540/KCIOpenApi/artiInfo/openApiD217List",
        "portal": "https://www.data.go.kr/data/15085348/openapi.do",
        "key_param": "ServiceKey", "page_param": "pageNo", "size_param": "recordCnt",
        # 미확인: 이 상세기능은 논문명 검색 변수를 공개하지 않는다(artiId 로 한 건씩 조회).
        #         실제 응답도 논문 서지가 아니라 매핑 목록(NUM·FTID·XMLFILE·MAPART)이었다.
        #         논문 제목으로 찾으려면 KCI 자체 OpenAPI(KCI_API_KEY) 쪽이 맞다.
        "query_param": None,
        "format_param": None,  # XML 만 제공
    },
    "assembly_bill": {
        "이름": "국회사무처_국회의원 발의법률안",
        "endpoint": "https://apis.data.go.kr/9710000/BillInfoService2/getBillInfoList",
        "portal": "https://www.data.go.kr/data/15125946/openapi.do",
        "key_param": "serviceKey", "page_param": "pageNo", "size_param": "numOfRows",
        "query_param": "bill_name",  # 미확인: 변수 이름은 제공기관 가이드 PDF 기준
        "format_param": None,
    },
}
DEFAULT_DATASET = "prism_research"  # 하네스가 가장 자주 쓰는 API

TITLE_KEYS = ("research_name", "title", "TITLE", "artiTitle", "논문명",
              "bill_name", "BILL_NAME", "name", "제목")
DATE_KEYS = ("research_date", "pubDate", "PUB_DATE", "propose_dt", "PROPOSE_DT",
             "regDate", "INDATE", "date", "일자")
ID_KEYS = ("research_id", "artiId", "ARTI_ID", "bill_id", "BILL_ID", "id", "NUM", "seq")


def _to_iso(d) -> str | None:
    s = str(d or "").strip()
    m = re.match(r"^(\d{4})[-./]?(\d{2})[-./]?(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return f"{s}-12-31" if re.fullmatch(r"\d{4}", s) else None


def _first(d: dict, keys) -> str | None:
    for k in keys:
        if d.get(k) not in (None, ""):
            return str(d[k])
    return None


class DataGoKrSource(BaseSource):
    name = "data_go_kr"
    tier = "T1"
    kind = "stats"
    env_vars = ["DATA_GO_KR_API_KEY"]
    default_grade = "A"  # 정부·공공기관 1차 자료

    def __init__(self, env, http, dataset: str = DEFAULT_DATASET):
        super().__init__(env, http)
        self.dataset = dataset if dataset in DATASETS else DEFAULT_DATASET

    # ── 응답 해석 -------------------------------------------------------------
    @staticmethod
    def _parse(text: str, rows_key: str | None = None) -> tuple[list, str, str]:
        """(행 목록, 코드, 한국어 설명). 코드가 성공이 아니면 행 목록은 빈 값이다."""
        t = (text or "").lstrip()
        if t.startswith("{") or t.startswith("["):
            try:
                data = json.loads(t)
            except json.JSONDecodeError:
                return [], "PARSE", "응답을 JSON 으로 읽지 못했습니다"
            if not isinstance(data, dict):
                return [], "PARSE", "예상 밖의 JSON 모양입니다"
            resp = data.get("response", data)
            head = (resp.get("header") if isinstance(resp, dict) else None) or {}
            # 표준 봉투는 header 에, PRISM 같은 납작한 응답은 최상위에 결과 코드가 있다.
            code = str(head.get("resultCode") or data.get("resultCode") or "").strip()
            msg = head.get("resultMsg") or data.get("resultMsg") or ""
            if code and code not in ("00", "0"):
                return [], code, RESULT_KO.get(code, msg or f"오류 코드 {code}")
            if rows_key:
                rows = data.get(rows_key)
                return (rows if isinstance(rows, list) else
                        [rows] if isinstance(rows, dict) else []), code or "00", "정상 처리되었습니다"
            body = (resp.get("body") if isinstance(resp, dict) else None) or {}
            items = body.get("items") if isinstance(body, dict) else None
            if isinstance(items, dict):
                items = items.get("item")
            rows = items if isinstance(items, list) else ([items] if isinstance(items, dict) else [])
            return rows, code or "00", "정상 처리되었습니다"
        # XML
        try:
            root = ET.fromstring(t)
        except Exception:
            return [], "PARSE", "응답을 XML 로 읽지 못했습니다"
        reason = root.findtext(".//returnReasonCode")
        if reason:
            auth = root.findtext(".//returnAuthMsg") or ""
            return [], str(reason), REASON_KO.get(str(reason), auth or f"오류 코드 {reason}")
        code = (root.findtext(".//resultCode") or "").strip()
        if code and code not in ("00", "0"):
            msg = root.findtext(".//resultMsg") or ""
            return [], code, RESULT_KO.get(code, msg or f"오류 코드 {code}")
        rows = []
        for item in root.iter():
            if item.tag.split("}")[-1] != "item":
                continue
            rows.append({c.tag.split("}")[-1]: (c.text or "").strip() for c in item})
        return rows, code or "00", "정상 처리되었습니다"

    # ── 호출 ------------------------------------------------------------------
    def fetch(self, dataset: str | None = None, params: dict | None = None,
              page: int = 1, size: int = 20) -> tuple[list, str, str]:
        """데이터셋 하나를 부른다. (행 목록, 코드, 한국어 설명)."""
        ds = DATASETS[dataset or self.dataset]
        p = {ds["key_param"]: self.env.get("DATA_GO_KR_API_KEY", ""),
             ds["page_param"]: page, ds["size_param"]: size}
        if ds.get("format_param"):
            p[ds["format_param"]] = "json"
        p.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
        return self._parse(self.http.get_text(ds["endpoint"], params=p), ds.get("rows_key"))

    # ── 검색 ------------------------------------------------------------------
    def search(self, query, since=None, until=None, limit=20, **extra_params):
        """기본 데이터셋을 검색어로 조회한다. 레코드 하나 = 자료 한 건.

        검색어 변수가 없는 데이터셋(query_param=None)은 검색어를 보내지 않고 목록을 받아
        **제목에 검색어가 든 것만** 남긴다. 그래서 받아 오는 건수를 limit 보다 넉넉히 잡는다.
        기간 변수가 있는 데이터셋은 since/until 을 요청에 실어 보낸다(YYYYMMDD).
        extra_params 로 기관 코드(organ_id) 같은 데이터셋별 조건을 덧붙일 수 있다.
        """
        ds = DATASETS[self.dataset]
        qp = ds.get("query_param")
        p = dict(extra_params)
        if qp:
            p[qp] = query
        period = None
        if ds.get("since_param"):
            # 이 데이터셋은 기간이 필수다. 한쪽만 주셔도 나머지를 채워 보낸다.
            lo, hi = _window(since, until)
            p[ds["since_param"]], p[ds["until_param"]] = lo, hi
            period = f"{lo}~{hi}"
        if qp:
            pages, size = 1, min(max(limit, 1), ds.get("page_size", 100))
        else:
            # 검색어를 못 보내는 API 는 목록을 받아 우리가 제목으로 거른다.
            # 훑지 않은 쪽에 있는 과제는 찾을 수 없으므로 정해진 쪽수까지 넘겨 가며 본다.
            pages, size = ds.get("scan_pages", 1), ds.get("page_size", 100)
        rows, code, msg, scanned = [], "00", "", 0
        for page in range(1, max(pages, 1) + 1):
            got, code, msg = self.fetch(params=p, page=page, size=size)
            rows += got
            scanned += len(got)
            if len(got) < size:
                break        # 마지막 쪽이다
        if not rows:
            if code in ("00", "0", "03", "PARSE"):
                return []
            raise RuntimeError(f"공공데이터포털 조회 실패: {msg}")
        q = (query or "").strip()
        out = []
        for r in rows:
            title = (_first(r, TITLE_KEYS) or "").strip()
            if not qp and q and q not in title:
                continue        # 검색어 변수가 없는 API 는 제목으로 우리가 거른다
            d = _to_iso(_first(r, DATE_KEYS))
            if since and d and d < since:
                continue
            if until and d and d > until:
                continue
            out.append(self.record(
                id=_first(r, ID_KEYS) or "",
                url=ds["portal"],
                title=title or ds["이름"],
                date=d,
                snippet=" · ".join(f"{k}={v}" for k, v in list(r.items())[:8] if v)[:1000],
                query=query,
                extra={
                    "데이터셋": self.dataset, "데이터셋명": ds["이름"],
                    "검색어_전달": "예" if qp else "아니오(검색어 변수가 없어 제목으로 걸렀습니다)",
                    "url_종류": "포털 데이터셋 화면(자료별 공개 주소 없음)",
                    **({"조회기간": period} if period else {}),
                    **({} if qp else {"훑은건수": scanned}),
                    "원자료": r,
                }))
            if len(out) >= limit:
                break
        return out

    # ── 상태 -----------------------------------------------------------------
    def ping(self):
        ds = DATASETS[self.dataset]
        p = {}
        if ds.get("since_param"):  # 기간이 필수인 API 는 비워 두면 거절당한다
            p[ds["since_param"]], p[ds["until_param"]] = _window(None, None)
        try:
            rows, code, msg = self.fetch(params=p, size=1)
        except Exception as e:  # 네트워크 계층 오류는 위에서 상태로 바꾼다
            return False, f"호출 실패: {type(e).__name__}: {str(e)[:80]}"
        if code in ("00", "0"):
            return True, f"OK, {DATASETS[self.dataset]['이름']} {len(rows)}건 응답"
        if code == "03":
            return True, "OK, 키는 정상(자료 0건)"
        return False, msg
