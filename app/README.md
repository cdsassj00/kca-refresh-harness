# 독립 프로그램 (app/)

Claude Code 없이 돌아가는 **브라우저 화면판**입니다. OpenRouter(또는 어떤 OpenAI 호환 API) 키 하나를 넣으면, 보고서를 접수하고 3단계(바뀐 것 찾기 → 숫자 다시 맞춰보기 → 결론 다시 내보기)를 돌려 신구 대조표와 현행화 보고서를 냅니다. 규칙·절차서·지식베이스·계산기는 루트의 공통 핵심을 그대로 씁니다.

- 설정 순서: [SETUP.md](SETUP.md) · 설계·계약: [DESIGN.md](DESIGN.md) · 키 발급: [../docs/api_keys_guide.md](../docs/api_keys_guide.md)
- 실행: `run_app.bat`(Windows) / `bash run_app.sh`(macOS·Linux) → http://127.0.0.1:8765

## 무엇이 다른가

| | 독립 프로그램 (`app/`) | Claude Code 하네스 (루트) |
|---|---|---|
| 필요한 것 | Python + OpenRouter 키 | Python + Claude Code 로그인(구독) |
| 모델 | OpenRouter 의 어떤 모델이든 (OpenAI·Anthropic·Google·오픈소스) | Claude |
| 화면 | 브라우저 8개 화면 | 터미널 `/refresh-run` |
| 실행 방식 | FastAPI 서버가 단계를 순서대로 LLM 에 보내고 도구(검색·열람) 호출을 중계 | Claude Code 가 스킬·서브에이전트로 실행 |
| 산출물 | 같음 (`reports/<ID>/` 의 같은 파일) | 같음 |

두 방식은 **같은 `reports/` 서랍과 `registry.csv` 를 공유**합니다. 하네스로 돌린 R01 을 프로그램에서 열어 볼 수 있고, 반대로도 됩니다.

## 화면 8개

| 화면 | 한 줄 |
|---|---|
| 대시보드 (`#dashboard`) | 보고서 목록(발간·경과 연수·성숙도·판정 요약 배지), LLM·소스 상태, 최근 실행 |
| 접수 (`#intake`) | pdf/hwpx/hwp/docx/txt 드롭 → 파싱 결과(쪽수·글자 수·스캔본 경고) |
| 실행 (`#run`) | 보고서·층(L0/L1/L2)·옵션·모델 선택 → 실행 → 스테퍼·로그·토큰·비용 누계·취소 |
| 결론 대조표 (`#table`) | 판정 배지와 필터, 행 클릭 시 원/추적/블라인드 3열 + 사유 + 근거 링크 + 상류 전제 |
| 영향 지도 (`#impact`) | 사건 → 전제 → 결론 → 제언 연결 그림(SVG), 노드 클릭 시 상세 |
| 산출물 (`#outputs`) | 현행화 보고서 HTML, 대조표 HTML, 브리프·설계서·검토 노트, 내려받기 |
| 지식베이스 (`#kb`) | 도메인별 사건 타임라인(`kb/events/`) |
| 설정 (`#settings`) | 키 입력(마스킹)·연결 확인, 모델 목록·검색, 검색 공급자, 온도·최대 단계, doctor 표 |

## 구조

```
app/
├─ run_app.bat  run_app.sh      실행 (가상환경·패키지·.env 준비 후 서버 시작)
├─ requirements.txt  .env.example  SETUP.md  README.md  DESIGN.md
├─ config.py                    경로·설정·키 로드 (CORE_DIR 로 공통 핵심 참조)
├─ engine/                      파이프라인 엔진
│  ├─ llm.py        OpenAI 호환 chat/completions 클라이언트 (재시도, 비용 집계)
│  ├─ tools.py      LLM 이 부르는 도구: web_search, fetch_page, evidence_search, read_report_file, read_core_file
│  ├─ search.py     검색 공급자 통합 (tavily → exa → naver → openrouter_online)
│  ├─ stages.py     단계 정의 11개 (intake … critic): 프롬프트 파일, 입력, 출력, 스키마, 도구
│  ├─ runner.py     단계 실행·재개·검증·로그, 파이프라인 진행 이벤트
│  ├─ brief.py      블라인드 브리프 생성
│  ├─ parsing.py    문서 파싱 (pdf/hwpx/hwp/docx/txt)
│  └─ jobs.py       백그라운드 실행과 진행 이벤트(SSE)
├─ server/main.py               FastAPI: 정적 UI + /api/* (health, settings, doctor, models, reports, runs, kb)
├─ ui/                          index.html · app.js · style.css (프레임워크 없음, 해시 라우팅, ?mock=1 시연 모드)
└─ tests/                       pytest (mock LLM, TestClient) — python -m pytest tests
```

생성되는 파일(git 제외): `.env`(키), `settings.json`(모델·옵션), `.venv/`(패키지).

## 공통 핵심을 어떻게 쓰나

`config.py` 의 `CORE_DIR`(기본 `app/..`, 환경변수 `KCA_CORE_DIR` 로 바꿀 수 있음)이 루트를 가리키고, 그 아래 경로를 상수로 둡니다.

| 상수 | 가리키는 곳 | 프로그램이 하는 일 |
|---|---|---|
| `PROMPTS_DIR` | `prompts/00~08` | 각 단계의 사용자 프롬프트로 **파일 전문을 그대로** 넣는다. 복사·수정하지 않는다(단일 원본) |
| `TEMPLATES_DIR` | `templates/schemas/*.json`, `verdict_rules.yaml` | LLM 응답을 `scripts.validate` 로 스키마 검사, 판정 규칙을 compare 단계 입력에 인라인 |
| `KB_DIR` | `kb/events/<domain>/`, `kb/evidence/` | delta 단계 전에 읽고(선독), 새 사건은 같은 형식으로 기록(후기) |
| `SCRIPTS_DIR` | `scripts/` | `validate`, `registry`, `render_table`, `render_report`, `sources` 를 **import** 해서 호출. 계산·렌더는 AI 가 아니라 이 코드가 한다 |
| `REPORTS_DIR` | `reports/<ID>/` | 하네스와 같은 서랍 구조에 같은 파일명으로 저장 |
| `REGISTRY_CSV` | `registry.csv` | 접수 시 upsert, 실행 끝에 성숙도·갱신 시각 반영 |
| `RUNS_DIR` | `runs/` | 실행 요약 `runs/<job_id>.json`, 업로드 원본 `runs/uploads/` |

`sys.path` 에 `CORE_DIR` 을 넣기 때문에 `from scripts import validate` 가 그대로 됩니다. 루트 `CLAUDE.md` 의 "규칙" 절은 `engine/system_prompt.md` 로 옮겨 모든 단계의 시스템 프롬프트가 됩니다.

## 하네스와의 관계

- **원본은 하나.** 절차서(`prompts/`)·규칙(`templates/`)·지식베이스(`kb/`)·계산기(`scripts/`)를 고치면 두 방식 모두에 반영됩니다. `app/` 에는 실행 방식만 있습니다.
- **블라인드 격리도 같은 규칙.** `blind` 단계는 `isolated=True` 로 브리프 외 어떤 보고서 내용도 대화에 넣지 않고 파일 읽기 도구를 빼며, `files_opened` 를 기록합니다.
- **검토자 분리.** `critic` 단계는 읽기 전용 도구만 갖고 `critic_notes.md` 만 씁니다.
- **역할 카드(`.claude/agents/`)는 쓰지 않습니다.** 그 본문은 `prompts/` 와 겹치므로 프로그램은 `prompts/` 만 읽습니다. 하네스 전용 포장(`.claude/`, `AGENTS.md`, `setup.bat`)은 프로그램에 영향이 없습니다.
- **키 파일은 따로.** 하네스는 루트 `.env`, 프로그램은 `app/.env`. 근거 소스 키를 두 곳에 같이 두어도 됩니다.

## 개발

```
cd app
python -m pytest tests            # mock LLM·TestClient 테스트
python -m uvicorn server.main:app --reload --port 8765   # 코드 수정 시 자동 재시작
```
브라우저에서 `http://127.0.0.1:8765/?mock=1` 을 열면 서버 API 없이 가짜 데이터로 화면만 봅니다.
