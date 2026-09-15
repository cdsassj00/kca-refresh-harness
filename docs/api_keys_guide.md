# 근거 소스 API 키 발급 가이드 (초안)

상태: **초안**. 포털 메뉴 이름·승인 시간은 2026-09 기준 기억과 공개 안내를 바탕으로 적었으며, P0 단계에서 각 포털을 실제로 열어 확인하고 `python scripts/evidence.py doctor`로 호출까지 검증한 뒤 확정본으로 바꾼다.

## 0. OpenRouter (독립 프로그램 필수) · Tavily · Exa

독립 프로그램(`app/`)은 **OpenRouter 키 하나만 있으면** 돌아간다. 아래 1~3절의 근거 소스 키는 모두 선택이다. Claude Code 하네스 방식은 OpenRouter 키가 필요 없다.

### 0-1. OpenRouter — `OPENROUTER_API_KEY` (독립 프로그램 필수)
- 발급처: https://openrouter.ai
- 절차: **가입**(Google·GitHub·이메일) → 오른쪽 위 계정 메뉴 → **Keys** → **Create Key** → 이름 입력(예: `kca-refresh`) → **Credit limit**(이 키가 쓸 수 있는 금액 상한, 월 예산으로 두기를 권장) 입력 → 생성 → `sk-or-…` 로 시작하는 키를 **그 자리에서 복사**(다시 볼 수 없음)
- 결제: 선불 크레딧. **Credits** 메뉴에서 카드로 충전(소액부터). 잔액이 0이면 호출이 거부된다.
- 넣는 곳: 브라우저 **[설정]** 화면의 `OPENROUTER_API_KEY` → 저장 → **연결 확인**. 또는 `app/.env`에 `OPENROUTER_API_KEY=sk-or-…`
- 모델: 같은 키로 OpenRouter의 모든 모델을 쓴다. [설정]의 모델 목록에서 고른다. 단가는 모델마다 다르며 목록에 표시된다.
- 데이터: 계정 설정 › **Privacy**에서 학습에 쓰는 공급자 허용 여부와 로그 보관을 정할 수 있다. 기관 방침에 맞춰 확인한다.
- 직접 연결: OpenRouter를 거치지 않고 특정 제공사(OpenAI 호환)나 사내 서버를 쓰려면 [설정]의 `LLM_BASE_URL`을 그 주소로, `OPENROUTER_API_KEY` 자리에 그 제공사 키를 넣는다.
- 소요: 즉시

### 0-2. Tavily 웹 검색 — `TAVILY_API_KEY` (선택, 검색 품질 향상)
- 발급처: https://app.tavily.com
- 절차: 가입 → 대시보드 **API Keys** → 키 복사(`tvly-…`). 무료 구간(월 호출 한도)이 있고 넘으면 유료.
- 용도: 사건·실적 검색(`web_search` 도구). 없으면 Exa → NAVER → OpenRouter 웹 플러그인 순으로 대체된다.
- 소요: 즉시

### 0-3. Exa 웹 검색 — `EXA_API_KEY` (선택)
- 발급처: https://dashboard.exa.ai
- 절차: 가입 → **API Keys** → Create → 키 복사. 무료 크레딧 후 종량제.
- 용도: 리서치 특화 검색(논문·기사 카테고리 필터). Tavily가 없을 때 두 번째 순위.
- 소요: 즉시

셋 다 [설정] 화면에서 넣고 **doctor** 표의 `llm`·`search` 행으로 확인한다.

## 공통 규칙 (근거 소스 키)
- 키는 `.env`에만 적는다. Claude Code 하네스는 프로젝트 루트 `.env`, 독립 프로그램은 `app/.env`(브라우저 [설정]에서 저장하면 여기에 쓰인다). 둘 다 `.gitignore`에 들어가며, UI나 보고서에 키가 노출되지 않는다.
- 키가 없는 소스는 하네스가 자동으로 건너뛴다. 아래 순서대로 발급하면 빨리 효과가 난다.
- 발급 후 `python scripts/evidence.py doctor` 를 실행하면 소스별 연결 상태가 표로 나온다.
- 대부분 무료이며 개인 계정으로 신청 가능하다. "기관" 표시가 있는 것만 기관 구독이 필요하다.

## 1. 권장 최소 세트 (이 넷이면 Layer 0 전체 + 전망·정책 검증이 돈다)

### 1-1. 공공데이터포털 — `DATA_GO_KR_API_KEY`
- 발급처: https://www.data.go.kr
- 절차: 회원가입 → 로그인 → 검색창에 데이터셋명 → 상세 페이지의 **활용신청** → 활용목적 입력(예: 연구·정책분석) → 대부분 즉시 자동승인 → 마이페이지 › 데이터활용 › Open API › 인증키 발급현황에서 **일반 인증키(Decoding)** 복사
- 특징: 계정당 인증키 하나로 활용신청한 모든 API에 공통 사용. 데이터셋마다 활용신청만 추가하면 된다.
- 이 프로젝트에서 활용신청할 데이터셋(1차): 한국연구재단_KCI 논문정보서비스, 한국연구재단_KCI 학술지정보서비스, 행정안전부_정책연구 과제정보(PRISM). 도메인 프로파일 확정 시 과기정통부·방송 통계 데이터셋을 추가한다.
- 한도: 개발계정 일 1,000~10,000회(데이터셋별 표기). 운영계정 전환 시 상향.
- 소요: 즉시(일부 데이터셋은 제공기관 승인 1~3일)

### 1-2. KOSIS 국가통계포털 — `KOSIS_API_KEY`
- 발급처: https://kosis.kr/openapi
- 절차: 회원가입 → 상단 **공유서비스** › OpenAPI → **활용신청** → 활용목적 입력 → 인증키 즉시 발급(마이페이지에서 확인)
- 용도: 통계표(통계자료) 시계열 조회. 전망형 결론의 백테스트에 핵심.
- 한도: 분당·일 호출 제한 있음(신청 화면 표기). HTTP는 종료, HTTPS만 사용.
- 소요: 즉시

### 1-3. 법제처 국가법령정보 공동활용 — `LAW_GO_KR_OC`
- 발급처: https://open.law.go.kr
- 절차: 회원가입 → **OPEN API 신청** → 이용목적·활용 URL 입력 → 승인 후 사용. 요청 파라미터 `OC` 값은 **회원 ID(이메일의 @ 앞부분)** 이다. 별도 키 문자열이 아니다.
- 용도: 법령 본문·개정 연혁·신구조문 대비, 행정규칙·고시. 정책제언의 채택·입법 추적에 핵심.
- 한도: 명시 한도 없음(과도 호출 시 제한)
- 소요: 보통 1~2 업무일

### 1-4. NAVER 검색 API — `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- 발급처: https://developers.naver.com
- 절차: 네이버 로그인 → Application › **애플리케이션 등록** → 이름 입력 → 사용 API에서 **검색** 선택 → 비로그인 오픈 API 서비스 환경에 WEB 설정(URL은 `http://localhost` 등 임의) → 등록 즉시 Client ID·Client Secret 표시
- 용도: 뉴스 검색으로 발간일 이후 사건 타임라인 구성
- 한도: 일 25,000회
- 소요: 즉시

## 2. 국내 추가 소스 (무료)

### 2-1. 열린국회정보 — `ASSEMBLY_API_KEY`
- 발급처: https://open.assembly.go.kr → 회원가입 → **인증키 신청** → 즉시 발급
- 용도: 의안 발의·처리 상태, 위원회 회의록 검색. 제언의 입법 추적.
- 한도: 일 호출 제한(신청 화면 표기)

### 2-2. 한국은행 ECOS — `ECOS_API_KEY`
- 발급처: https://ecos.bok.or.kr/api → 회원가입 → 인증키 신청 → 즉시
- 용도: 거시 변수(GDP·물가·환율). 경제성 분석 재계산 입력.

### 2-3. KCI 한국학술지인용색인 직접 API — `KCI_API_KEY`
- 발급처: https://www.kci.go.kr → 로그인 → OpenAPI 메뉴 → 신청 → 개발계정 트래픽 5,000 → 키 발급
- 참고: 공공데이터포털 경유(1-1)로도 같은 논문정보를 받을 수 있으므로, 1-1이 되면 생략 가능.

### 2-4. 국회도서관 Open API — `NANET_API_KEY`
- 발급처: https://www.nanet.go.kr → 도서관소개 › 정보공개 › Open API → 신청서 작성 → 승인 후 인증키
- 용도: 학술논문·정책자료 통합검색
- 한도: 1회 100건, 일 1,000회. 승인까지 최대 7 업무일

### 2-5. ScienceON (KISTI) — `SCIENCEON_API_KEY`
- 발급처: https://scienceon.kisti.re.kr/apigateway → 회원가입 → API 신청 → 승인 → 키·토큰
- 용도: 국내 논문·특허·연구보고서·NTIS 과제 통합검색. 후속 문헌 스캔 폭 확장.

## 3. 해외 논문 소스

### 3-1. 키 없이 사용
- **OpenAlex**: 키 불필요. `.env`의 `OPENALEX_MAILTO`에 이메일을 넣으면 우대 속도(polite pool). 1차 논문 검색 엔진.
- **Crossref**: 키 불필요. `CROSSREF_MAILTO` 선택.
- **arXiv**: 키 불필요. 기존 `arxiv-search` 스킬 재사용.
- **OECD / World Bank**: 키 불필요.

### 3-2. 무료 키
- **Semantic Scholar** — `S2_API_KEY`: https://www.semanticscholar.org/product/api 의 키 신청 폼 → 이메일로 발급. 없어도 동작하나 쿼터가 낮다.
- **IEEE Xplore Metadata** — `IEEE_API_KEY`: https://developer.ieee.org 회원가입 → 애플리케이션 등록 → 키. 무료 계정은 일 호출 한도가 작고, 기관 구독이 있으면 전체 메타데이터. 통신·전파 공학 논문에 유용.
- **CORE** — `CORE_API_KEY`: https://core.ac.uk/services/api 등록 → 키. 오픈액세스 원문.
- **Springer Nature** — `SPRINGER_API_KEY`: https://dev.springernature.com 등록 → 키.
- **Lens.org** — `LENS_API_TOKEN`: https://www.lens.org 계정 → API 토큰 신청(비상업 무료).

### 3-3. 유료·기관 구독 (있으면 넣고, 없으면 비워 둔다)
- **Scopus (Elsevier)** — `ELSEVIER_API_KEY`, `ELSEVIER_INSTTOKEN`: https://dev.elsevier.com. 기관 구독 IP 또는 InstToken 필요.
- **Web of Science (Clarivate)** — `WOS_API_KEY`: https://developer.clarivate.com. Starter는 제한적 무료, Expanded는 구독.
- **Dimensions** — `DIMENSIONS_API_KEY`: 구독.
- **Exa / Tavily / Perplexity Sonar** — `EXA_API_KEY` / `TAVILY_API_KEY` / `PERPLEXITY_API_KEY`: 각 사이트에서 결제 후 키. 리서치 특화 웹검색(논문 카테고리 필터). Tavily·Exa 발급 절차는 0절.
- **SerpAPI (Google Scholar)** — `SERPAPI_API_KEY`: 결제 후 키.
- **DBpia / BigKinds** — `DBPIA_API_KEY` / `BIGKINDS_API_KEY`: 기관 계약·별도 신청.

## 4. `.env` 작성 예
```
# 권장 최소 세트
DATA_GO_KR_API_KEY=
KOSIS_API_KEY=
LAW_GO_KR_OC=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
# 국내 추가
ASSEMBLY_API_KEY=
ECOS_API_KEY=
KCI_API_KEY=
NANET_API_KEY=
SCIENCEON_API_KEY=
# 해외
OPENALEX_MAILTO=
CROSSREF_MAILTO=
S2_API_KEY=
IEEE_API_KEY=
CORE_API_KEY=
SPRINGER_API_KEY=
LENS_API_TOKEN=
# 유료
ELSEVIER_API_KEY=
ELSEVIER_INSTTOKEN=
WOS_API_KEY=
DIMENSIONS_API_KEY=
EXA_API_KEY=
TAVILY_API_KEY=
PERPLEXITY_API_KEY=
SERPAPI_API_KEY=
DBPIA_API_KEY=
BIGKINDS_API_KEY=
```

## 5. 확인
```bash
python scripts/evidence.py doctor
```
소스별로 `OK / 키 없음 / 키 오류 / 한도 초과` 가 표로 나온다. `OK`인 소스만 파이프라인이 사용한다.

## 6. 발급 우선순위와 예상 소요
| 순서 | 소스 | 소요 | 이유 |
|---|---|---|---|
| 1 | NAVER 검색 | 즉시 | 사건 타임라인 즉시 가동 |
| 2 | KOSIS | 즉시 | 백테스트 |
| 3 | 공공데이터포털 | 즉시~3일 | KCI 논문 + 통계 데이터셋 |
| 4 | 법제처 | 1~2일 | 제언 추적 |
| 5 | 열린국회정보, ECOS | 즉시 | 입법·거시 |
| 6 | Semantic Scholar, IEEE, ScienceON | 수일 | 문헌 스캔 폭 |
| 7 | 국회도서관 | 최대 7일 | 정책자료 |
