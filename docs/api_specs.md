# 국내 API 명세 메모

커넥터를 만들 때 참고하는 실무 메모다. **실제로 호출해 확인한 것**과 **공식 문서를 옮긴 것**을 구분해 적는다.
포털 문서는 사라지거나 바뀌므로, 여기에 요청·응답의 뼈대를 남겨 둔다.

---

## 1. 행정안전부 정책연구 과제정보 (PRISM) — **실호출 확인 2026-09-19**

보고서 발간 이후 **주무부처가 같은 주제로 후속 연구를 발주했는지** 확인하는 데 쓴다.
후속 발주 자체가 "당시 결론이 재검토 대상이었다"는 근거가 된다.

- 창구: 공공데이터포털(`DATA_GO_KR_API_KEY`)
- Base URL: `https://apis.data.go.kr/1741000/prism_v3`
- 형식: REST, JSON (`type=json`)
- 한도: 개발계정 1,000회/일

| 엔드포인트 | 용도 |
|---|---|
| `GET /getResearchList_v3` | 기관별·기간별 과제 목록 |
| `GET /getResearchDetail_v3` | 과제 상세 (`research_id`) |
| `GET /pnnMetaData_v3` | 공통 메타정보 (필수 파라미터 있음, 미확인) |

### 목록 요청
```
GET /getResearchList_v3
  serviceKey=<키>  type=json
  start_date=YYYYMMDD  end_date=YYYYMMDD
  organ_id=<기관코드>        # 없으면 전 기관
  numOfRows=<건수>  pageNo=<쪽>
```

**검색어 파라미터가 없다.** 기관과 기간으로 받아 온 뒤 제목에서 주제어로 걸러야 한다.
**실호출 확인: `numOfRows` 는 1,000 까지 받는다.** 3년치 총계가 1만 2천 건대이므로 1,000건씩 13쪽이면
기간 전체를 빠짐없이 훑는다(개발계정 하루 1,000회 한도 안에서 넉넉하다).
커넥터는 `page_size=1000`·`scan_pages=15` 로 쪽을 넘기며 훑고, 실제로 몇 건을 봤는지
레코드의 `extra["훑은건수"]` 에 남긴다. 기간을 안 주면 서버가 `NO_MANDATORY_REQUEST_PARAMETERS_ERROR`
로 거절하므로 **기본값 최근 3년**을 채워 보낸다.

### 목록 응답 (확인한 필드)
```json
{"resultCode":"0","resultMsg":"NORMAL_SERVICE","totalCount":6730,
 "research":[{"research_id":"4600000-202600074","research_name":"…","organ_name":"충청남도 홍성군",
   "researcher_name":"…","charge_person_department":"…","biz_name":"지역 및 도시",
   "research_organName":"(주)…","research_date":"2024-03-19","issued_year":"2026","report_open_yn":"공개"}]}
```

### 확인한 기관 코드
| 코드 | 기관 | 비고 |
|---|---|---|
| `1721000` | 과학기술정보통신부 | 2023-01~2026-09 기준 80건. 우리 도메인의 주무부처 |

지자체 과제가 대부분이라 **기관 코드 없이 부르면 잡음이 많다.** 도메인별로 쓸 기관 코드를 `kb/domains/*.yaml` 에 적어 두고 그것만 조회한다. 방송미디어통신위원회 등 다른 기관 코드는 미확인.

---

## 2. KCI 논문 기본정보 — **공식 문서 기준, 실호출 미확인 (커넥터 구현 완료)**

발간 이후 나온 국내 학술 논문을 찾는 데 쓴다. **제목 검색 + 발행년월 범위**를 함께 줄 수 있어 우리 용도에 맞는다.

- 창구: KCI 직접(`KCI_API_KEY`). 공공데이터포털 경유와는 별개다.
- URL: `https://open.kci.go.kr/po/openapi/openApiSearch.kci`
- 형식: **XML** (JSON 아님). 파싱은 `defusedxml` 로.

### 요청
| 파라미터 | 필수 | 설명 |
|---|---|---|
| `key` | O | 발급 인증키 |
| `apiCode` | O | `articleSearch` |
| `title` | **O** | 제목 검색어(UTF-8). **비우면 "검색 조건이 없습니다" 오류** |
| `keyword` · `abstract` · `author` · `journal` · `institution` · `affiliation` · `doi` | X | 추가 조건 |
| `dateFrom` · `dateTo` | X | 발행년월 `YYYYMM` (6자리) |
| `regDateFrom` · `regDateTo` · `modDateFrom` · `modDateTo` | X | 등록·수정일 `YYYYMMDD` (8자리) |
| `page` · `displayCount` | X | 쪽, 출력 건수(기본 10, **최대 100**) |
| `sortNm` | X | `title` · `author` · `pubiYr` (기본 정확도) |

예: `…/openApiSearch.kci?apiCode=articleSearch&key=<키>&title=%EC%BB%B4%ED%93%A8%ED%84%B0`

### 응답 뼈대
```
MetaData > outputData
  result > total                      총 건수
  record*                             결과 1건
    journalInfo
      journal-name, publisher-name, pub-year(YYYY), pub-mon(MM), volume, issue
      foreign-listed > name*          해외등재명
    articleInfo[@article-id]
      article-categories              연구분야
      title-group > article-title[@lang=original|foreign|english]
      author-group > author[@english][@orc-id]   "이름(소속)"
      abstract-group > abstract[@lang=original|english]
      fpage, lpage, orte-open-yn, doi, uci
      citation-count[@kci][@wos]      피인용 횟수
      url                             사람이 볼 수 있는 논문 주소
      verified                        Y/N
```

### 우리 쪽 대응
- 증거 등급 **A**(학술지 원문, DOI 있음). `url` 을 그대로 쓴다.
- `date` 는 `pub-year` + `pub-mon` 을 합쳐 `YYYY-MM`.
- `snippet` 은 `abstract[@lang=original]`, 없으면 영어 초록.
- `extra` 에 `journal-name`·`publisher-name`·`doi`·`citation-count(kci/wos)`·`article-categories`·`verified`.
- `since`/`until` 은 `dateFrom`/`dateTo` 로 넘긴다(6자리로 잘라서).
- `title` 이 필수이므로, 주제어가 없는 호출은 보내지 않는다(서버에 가기 전에 막는다).
- 구현: `scripts/sources/kci.py` (`KciSource`). 검사: `tests/test_kci.py` (mock 10건).
  **키를 받는 대로 `python scripts\evidence.py doctor` 로 실호출을 확인해야 한다.**

### 오류 메시지
`등록되지 않은 key 입니다` · `사용기간이 종료되었습니다` · `등록되지 않은 서비스`(apiCode 오류) ·
`검색 조건이 없습니다`(title 비었음) · `필수 요청 파라미터가 없음` · `#파라미터# 범위가 맞지 않습니다`
→ `ping()` 에서 이 문구를 그대로 사람에게 보여 준다.

---

## 3. 그 밖에 확인한 것

| 소스 | 상태 | 메모 |
|---|---|---|
| NAVER 검색 | **실호출 확인** | API HUB 이관. `https://naverapihub.apigw.ntruss.com/search/v1/{news,webkr}`, 헤더 `X-NCP-APIGW-API-KEY-ID`/`X-NCP-APIGW-API-KEY`. 신청 안 한 API 는 401 "활성화되어 있지 않습니다" |
| 한국은행 ECOS | 연결 확인, 검색 미흡 | 한글 검색어로는 0건. **통계표 코드**를 알아야 한다. 지표별 코드를 `kb/domains/*.yaml` 에 적어야 함 |
| KOSIS | **실호출 확인** | 유효기간 2년. 만료되면 같은 키로도 `err 12` 가 온다. 마이페이지에서 연장(만료 한 달 전부터) 또는 재신청하면 **키 값 그대로** 살아난다. 계정당 인증키는 하나 |
| 법제처 | 미확인 | OC 값은 `open.law.go.kr/LSO/usr/usrOcInfoMod.do` 의 "현재 API인증키(OC)" |
| 열린국회정보 | 미확인 | API 포털은 `open.assembly.go.kr/portal/openapi/main.do` (최상위 주소에는 메뉴 없음) |

## 공통 원칙

이 포털들은 **검색엔진이 아니다.** 통계표 코드·기관 코드·데이터셋 ID를 알고 값을 꺼내 오는 구조다.
그래서 지표마다 "어느 표의 어느 항목인지"를 `kb/domains/*.yaml` 에 적어 두고 커넥터가 그것을 참조해야 한다.
자유 검색어로 부르면 0건이 나오는 것이 정상이다.
