# 독립 프로그램(app/) 설계·계약서 v1

목적: Claude Code 없이, **OpenRouter(OpenAI 호환 API) 키 하나**만 넣으면 브라우저 화면에서 보고서를 접수하고 3단계 파이프라인을 돌려 신구 대조표와 현행화 보고서를 얻는 독립 프로그램. 절차서(`../prompts`), 스키마·규칙(`../templates`), 지식베이스(`../kb`), 계산기(`../scripts`)는 루트의 공통 핵심을 그대로 쓴다. 이 문서는 병렬로 만드는 네 부분(엔진·서버·UI·문서)이 서로 맞물리기 위한 **계약**이다. 이름·경로·JSON 모양은 여기 적힌 그대로 쓴다.

## 0. 폴더

```
app/
├─ README.md  SETUP.md  requirements.txt  .env.example  run_app.bat  run_app.sh
├─ config.py                # 경로·설정 로드 (아래 1절)
├─ engine/
│  ├─ __init__.py
│  ├─ llm.py                # LLMClient
│  ├─ tools.py              # 도구 레지스트리(web_search, fetch_page, evidence_search, read_report_file, read_core_file)
│  ├─ search.py             # 검색 공급자(tavily, exa, naver, openrouter_online) 통합
│  ├─ stages.py             # STAGES 정의
│  ├─ runner.py             # run_stage / run_pipeline
│  ├─ brief.py              # 블라인드 브리프 생성
│  ├─ parsing.py            # 문서 파싱(pdf/hwpx/hwp/docx/txt/md)
│  └─ jobs.py               # JobStore(백그라운드 실행, 진행 이벤트)
├─ server/
│  ├─ __init__.py
│  └─ main.py               # FastAPI 앱 (정적 UI + /api/*)
├─ ui/
│  ├─ index.html  app.js  style.css
└─ tests/                   # pytest (mock LLM, TestClient)
```
실행: `app/` 에서 `python -m uvicorn server.main:app --port 8765` → http://localhost:8765 . 작업 디렉터리는 항상 `app/`. 공통 핵심은 `config.CORE_DIR`(기본 `app/..`)로 참조.

## 1. 설정 (config.py)

- `.env`(app/) 로드: `OPENROUTER_API_KEY`, `LLM_BASE_URL`(기본 `https://openrouter.ai/api/v1`), `LLM_MODEL`(기본 `openrouter/auto`), `LLM_MODEL_CHEAP`(선택, 추출 단계용), `SEARCH_PROVIDER`(`auto|tavily|exa|naver|openrouter_online`, 기본 `auto`), `TAVILY_API_KEY`, `EXA_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, 그리고 루트 `.env.example`의 근거 소스 키들(공공데이터·KOSIS 등, evidence.py가 읽음).
- `settings.json`(app/, UI에서 수정): `{"model":"…","model_cheap":"","temperature":0.2,"max_steps":25,"search_provider":"auto","max_source_chars":120000,"language":"ko"}`
- 함수: `load_settings() -> dict`, `save_settings(dict)`, `load_env() -> dict`(값), `save_env_values(dict)`(`.env` 갱신, 키 이름만 허용 목록으로 검사), `mask(value) -> "sk-or-…abcd"`.
- 경로 상수: `APP_DIR`, `CORE_DIR`, `REPORTS_DIR = CORE_DIR/reports`, `PROMPTS_DIR`, `TEMPLATES_DIR`, `KB_DIR`, `SCRIPTS_DIR`, `REGISTRY_CSV`, `RUNS_DIR = CORE_DIR/runs`.
- `sys.path`에 `CORE_DIR`을 넣어 `scripts.*`(validate, registry, render_table, render_report, sources)를 import한다.

## 2. LLM 클라이언트 (engine/llm.py)

```python
@dataclass
class LLMResult: content: str; tool_calls: list[dict]; usage: dict; cost_usd: float | None; raw: dict
class LLMClient:
    def __init__(self, base_url, api_key, model, temperature=0.2, timeout=180, referer="http://localhost:8765", title="KCA Refresh")
    def chat(self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False, model: str | None = None, extra: dict | None = None) -> LLMResult
    def list_models(self) -> list[dict]          # GET {base_url}/models → [{id, name, context_length, pricing}]
    def ping(self) -> tuple[bool, str]           # 1토큰짜리 호출로 키·모델 확인
```
- 요청: `POST {base_url}/chat/completions` JSON `{model, messages, temperature, tools?, tool_choice:"auto", response_format:{"type":"json_object"}?(json_mode), usage:{"include":true}}`. 헤더 `Authorization: Bearer`, `HTTP-Referer`, `X-Title`.
- 응답: `choices[0].message.content`, `choices[0].message.tool_calls[]` (`{id, function:{name, arguments(json str)}}`), `usage.{prompt_tokens, completion_tokens, cost?}`.
- 재시도: 429/5xx는 지수 백오프 3회. 네트워크 오류는 `LLMError` 예외.
- 키 값은 로그·예외 메시지에 절대 넣지 않는다.

## 3. 도구 (engine/tools.py, engine/search.py)

OpenAI function-calling 형식. 각 도구는 `{"type":"function","function":{"name","description","parameters"}}` 정의와 파이썬 구현을 갖는다. `ToolRegistry.for_stage(stage, report_id) -> (tool_defs, executor)`; `executor(name, args) -> str`(JSON 문자열, 12,000자 초과 시 잘라내고 `"truncated": true`).

| 도구 | 인자 | 반환 | 구현 |
|---|---|---|---|
| `web_search` | `query`(str), `since`(YYYY-MM-DD, 선택), `max_results`(int, 기본 8), `lang`(`ko|en`, 기본 `ko`) | `[{title,url,snippet,date,source}]` | `search.py`: provider `auto`는 tavily → exa → naver(뉴스, 한국어) → openrouter_online 순으로 키가 있는 첫 공급자. `openrouter_online`은 `LLMClient.chat`에 `extra={"plugins":[{"id":"web"}]}`를 붙여 "결과를 JSON 배열로만 답하라"는 검색 전용 호출 |
| `fetch_page` | `url` | `{url,title,text(≤12000자),fetched_at,status}` | requests(UA 지정, 20s) → `trafilatura.extract` → 실패 시 BeautifulSoup `get_text`. PDF URL이면 pypdf로 앞 20쪽 |
| `evidence_search` | `query`, `since`(선택), `kind`(`papers`) , `limit`(기본 10) | 근거 레코드 배열 | `scripts.sources.load_sources`로 T0 커넥터 실행, 결과를 `kb/evidence/`에도 저장 |
| `read_report_file` | `relpath` | 파일 내용(텍스트, ≤60,000자, 초과 시 앞뒤 요약 없이 잘라내고 표시) | `reports/<id>/` 안으로만 제한(`..` 금지). **블라인드 단계에는 등록하지 않는다** |
| `read_core_file` | `relpath` | 파일 내용 | `kb/`, `templates/` 아래만 허용 |

## 4. 단계 정의 (engine/stages.py)

```python
@dataclass
class StageSpec:
    name: str; prompt_file: str | None; inputs: list[str]; outputs: list[str]
    schema: str | None; tools: list[str]; isolated: bool = False; python: str | None = None; model_role: str = "main"
    guidance: str = ""            # 같은 프롬프트를 나눠 쓰는 단계의 한정 지시(역할 지시서 뒤에 붙는다)
    merge_keys: dict = {}         # {출력 경로: 병합 키} — 기존 파일과 합쳐 쓴다
    types: list[str] = []         # 이 단계를 켜는 결론 유형(taxonomy code)
    allow_files: str = ""         # 비면 files 키 금지, 채우면 설명 문구
```
`inputs`는 `reports/<id>/` 기준 상대경로(존재하는 것만 인라인, 각 파일 앞에 `### 파일: <경로>` 머리말). `outputs`는 모델이 최종 응답 JSON의 **키**로 돌려줘야 하는 파일 경로(값은 문자열 또는 JSON 객체·배열; 러너가 파일로 쓴다).

| name | prompt_file | inputs | outputs | schema(검증 대상) | tools | 비고 |
|---|---|---|---|---|---|---|
| `intake` | – | – | `00_source/<id>.md`, `01_meta.json` | – | – | `python`: `parsing.parse_document` |
| `classify` | `00_intake.md` | `00_source/<id>.md`(앞 30,000자 + 목차 탐지), `01_meta.json` | `02_classification.json` | – | – | model_role `cheap` |
| `chains` | `01_chains.md` | `00_source/<id>.md`(≤ max_source_chars), `01_meta.json`, `02_classification.json` | `03_argument_chains.json` | `chain` | `read_report_file` | |
| `delta` | `02_delta.md` | `01_meta.json`, `02_classification.json`, `03_argument_chains.json`(premises만 추려 인라인) + `kb/events/<domain>/*.md` | `L0/events.json`, `L0/environment_delta.md` | `event`(배열 원소) | `web_search`, `fetch_page`, `read_core_file` | 새 사건은 `kb/events/<domain>/`에도 복사 |
| `impact` | `03_impact.md` | `03_argument_chains.json`, `L0/events.json`, `00_source/<id>.md`(≤40,000자) | `L0/provisional_verdicts.json`, `comparison_table.json` | `comparison_row`(conclusion_rows·body_rows 원소) | `read_report_file` | v0 사본을 `L0/comparison_table_v0.json`으로 |
| `verify_forecast` | `04_forecast_verify.md` | `03_argument_chains.json`, `L0/events.json`, `L0/provisional_verdicts.json` | `L1/verdicts.json`, `L2/traced/traced_conclusions.json` | `verdict`(배열 원소) | `web_search`, `fetch_page`, `evidence_search`, `read_report_file` | 유형 F·B·G |
| `verify_model` | `04a_model.md` | 위와 같음 | `L1/model_rerun.json` (+선택 `L2/traced/traced_conclusions.json`, `L1/verdicts.json`) | `verdict` | 위와 같음 | 유형 M. traced·verdicts 는 기존 파일과 병합 |
| `verify_policy` | `04_forecast_verify.md` | 위와 같음 | `L1/policy_tracking.md` (+선택 `L1/verdicts.json`) | `verdict` | 위와 같음 | 유형 P·제언(kind R). `guidance` 로 정책 결론만 다루게 한정 |
| `design_survey` | `04b_survey.md` | 위 + `templates/survey_redesign.md` | `L3/survey_index.json` (+선택 `L1/verdicts.json`, `files` 로 `L3/survey_redesign_<K-ID>.md`) | `verdict` | 위 + `read_core_file` | 유형 S. `options.survey_redesign=false` 면 생략 |
| `design_experiment` | `04c_experiment.md` | 위 + `templates/experiment_plan.md` | `L3/experiment_index.json` (+선택 `L1/verdicts.json`, `files` 로 `L3/experiment_plan_<K-ID>.md`) | `verdict` | 위 + `read_core_file` | 유형 T. `options.experiment_plan=false` 면 생략 |
| `brief` | `05a_brief.md`(신규) | `02_classification.json`, `03_argument_chains.json` | `L2/blind_input/brief.md` | – | – | 원 결론·수치 제거 규칙. model_role `cheap` |
| `blind` | `05_blind.md` | **`L2/blind_input/brief.md` 만** | `L2/blind_output/blind_conclusions.json` | – | `web_search`, `fetch_page`, `evidence_search` | `isolated=True`: 대화에 브리프 외 어떤 보고서 내용도 넣지 않고, 파일 읽기 도구 없음. 러너가 `files_opened: ["L2/blind_input/brief.md"]`를 강제로 기록 |
| `compare` | `06_compare.md` | `03_argument_chains.json`, `L2/traced/traced_conclusions.json`, `L2/blind_output/blind_conclusions.json`, `L1/verdicts.json`, `L0/provisional_verdicts.json`, `comparison_table.json`, `templates/verdict_rules.yaml` | `comparison_table.json`, `L2/compare/verdict_notes.md` | `comparison_row` | `read_report_file` | |
| `report` | – | – | `07_report/*` | – | – | `python`: `scripts.render_table.main`, `scripts.render_report.main`, 이후 `registry.set_maturity`(`L3/` 아래 `survey_redesign_*.md`·`experiment_plan_*.md`가 하나라도 있으면 `L3`) |
| `critic` | `08_critic.md` | `comparison_table.json`, `07_report/report.md`, `L2/blind_output/blind_conclusions.json` | `07_report/critic_notes.md` | – | `read_report_file` | 읽기 전용 |

층 매핑: `L0` = classify·chains·delta·impact, `L1` = verify_forecast·verify_model·verify_policy·design_survey·design_experiment, `L2` = brief·blind·compare, 항상 마지막에 report·critic. `run_config.layers`에 없는 층은 건너뛴다. `options.blind_rerun.enabled=false`면 brief·blind 생략, `options.survey_redesign`/`experiment_plan=false`면 해당 design 단계 생략.

**유형 기반 조건부 라우팅**: `stages_for(run_config, report_id)`는 `reports/<id>/03_argument_chains.json`의 모든 `conclusions[].types`를 모아, 해당 유형이 있는 L1 단계만 목록에 넣는다(F·B·G→`verify_forecast`, M→`verify_model`, P→`verify_policy`, S→`design_survey`, T→`design_experiment`). chains 파일이 아직 없으면(첫 실행) 전부 넣고, 대상이 없는 단계는 각 프롬프트의 "빈 배열·빈 객체로 정상 종료" 규칙으로 처리한다.

**덧붙임 출력**: `StageSpec.merge_keys`(예: `{"L1/verdicts.json": "claim_id"}`)가 있는 출력은 러너가 기존 파일을 읽어 키 기준으로 합쳐 쓴다(중복은 나중 것이 이김). 그래서 여러 L1 단계가 같은 `L1/verdicts.json`에 항목을 덧붙일 수 있다.

**`files` 키**: `StageSpec.allow_files`가 설정된 단계는 최종 JSON에 `"files": {"경로": "내용"}`을 넣어 고정 경로가 아닌 산출물(설계서·계획서)을 추가로 쓸 수 있다. 경로는 `config.safe_join`으로 `reports/<id>/` 안으로 제한하며 `..`·절대경로는 검증 오류다.

시스템 프롬프트(모든 단계 공통, `engine/system_prompt.md`): 루트 `CLAUDE.md`의 "규칙" 절을 옮긴 것 + "최종 응답은 outputs 키를 가진 JSON 객체 하나로만. 설명 문장을 붙이지 말 것. 파일 내용이 마크다운이면 문자열로, JSON이면 객체로." + 오늘 날짜.

## 5. 러너 (engine/runner.py)

```python
def run_stage(report_id: str, stage: StageSpec, settings: dict, llm: LLMClient, tools: ToolRegistry, log: Callable) -> StageResult
def run_pipeline(report_id: str, run_config: dict, progress: Callable[[dict], None], cancel: threading.Event) -> dict
```
- 재개: `outputs`가 모두 있으면 건너뜀(`force_from` 단계부터는 강제 재실행).
- 루프: system + user(프롬프트 파일 전문 + 인라인 입력 + 출력 지시) → `chat(tools)` → tool_calls 있으면 실행해 `role:"tool"` 메시지로 추가 → 반복(최대 `max_steps`) → tool_calls 없으면 content를 JSON으로 파싱.
- 검증: 파싱 실패·필수 키 누락·스키마 오류(`scripts.validate.validate_obj`)면 오류 목록을 담아 "고쳐서 다시 JSON만" 재요청, 최대 2회. 그래도 실패면 단계 실패(파일은 쓰지 않음, `logs/app_run.jsonl`에 원문 저장).
- 로그: `reports/<id>/logs/app_run.jsonl` 한 줄 = `{ts, stage, model, step, event:"llm|tool|write|error", name?, tokens_in, tokens_out, cost_usd, note}`. 실행 요약 `runs/<job_id>.json`.
- 진행 이벤트(progress 콜백): `{"job_id","report_id","stage","status":"running|done|skipped|failed","step":n,"message":"…","tokens":{...},"cost_usd":x,"ts"}`.
- 비용 합계·토큰 합계를 `runs/<job_id>.json`과 `registry.csv`(열 추가 없이 `updated_at`만)에 반영.

## 6. 문서 파싱 (engine/parsing.py)

`parse_document(path: Path) -> tuple[str, dict]` → (페이지 표시 `<!-- page N -->`가 붙은 Markdown 텍스트, `{"pages":n,"chars":m,"format":"pdf|hwpx|hwp|docx|txt","title_guess":…,"published_guess":"YYYY-MM"|None}`)
- pdf: `pypdf` (텍스트 없는 쪽 비율이 50% 넘으면 `meta["scanned"]=True`)
- hwpx: zip 열어 `Contents/section*.xml`의 텍스트 노드(`hp:t`)를 문단 단위로 추출, 표는 셀을 `|`로 연결
- hwp: `pyhwp`(`hwp5txt`)가 설치되어 있으면 사용, 없으면 `ParseError("HWP는 pyhwp 설치 또는 PDF 변환 필요")`
- docx: `markitdown` (없으면 python-docx)
- txt/md: 그대로
- `intake(report_id, path, title=None, published=None) -> meta`: `reports/<id>/00_source/<id>.md`, `01_meta.json` 저장(루트 `scripts/intake.py`와 같은 메타 키 + `format`), 레지스트리 upsert.

## 7. 서버 API (server/main.py) — 모두 JSON, 오류는 `{"error":"메시지"}`와 4xx/5xx

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/health` | – | `{"ok":true,"version":"0.1","core_dir":…}` |
| `GET /api/settings` | – | `{"settings":{…}, "env":{"OPENROUTER_API_KEY":"sk-or-…abcd"(마스킹) …}, "env_keys":[허용 키 이름 목록]}` |
| `PUT /api/settings` | `{"settings":{…부분}, "env":{"KEY":"값"…}}` | 저장 후 `GET`과 같은 응답. 빈 문자열은 삭제 |
| `GET /api/doctor` | – | `{"llm":{"ok":bool,"model":…,"detail":…},"search":{"provider":…,"ok":bool,"detail":…},"sources":[SourceStatus…],"parsers":{"hwp":bool,"docx":bool}}` |
| `GET /api/models` | – | `[{"id","name","context_length","prompt_price","completion_price"}]` (10분 캐시) |
| `GET /api/reports` | – | `[{id,title,published,years_since,domain,types,maturity,updated_at,summary:{동일:…}}]` (summary는 comparison_table.json 있을 때) |
| `POST /api/reports/intake` | multipart: `file`, `report_id`(선택, 없으면 다음 번호), `title`, `published`(YYYY-MM) | `{"report_id","meta":{…}}` |
| `GET /api/reports/{id}` | – | `{"meta","classification","maturity","files":[{path,size,mtime}],"has":{"chains":bool,"events":bool,"comparison":bool,"report":bool}}` |
| `GET /api/reports/{id}/comparison` | – | `comparison_table.json` 내용 |
| `GET /api/reports/{id}/chains` / `/events` / `/verdicts` / `/blind` / `/provisional` | – | 해당 JSON |
| `GET /api/reports/{id}/file?path=07_report/report.html` | – | 파일 내용(Content-Type 추정). `..` 금지 |
| `DELETE /api/reports/{id}` | – | 서랍 삭제(확인은 UI에서) |
| `GET /api/runs` | – | `[{job_id,report_id,status,started_at,ended_at,cost_usd,stages:[…]}]` |
| `POST /api/runs` | `run_config`(설계서 7.3 모양, `report_id` 필수) + `"force_from": "단계명"|null` | `{"job_id"}` (보고서당 동시 1개, 아니면 409) |
| `GET /api/runs/{job_id}` | – | 작업 상태 + 단계별 상태 + 최근 메시지 20개 |
| `GET /api/runs/{job_id}/events` | – | SSE(`text/event-stream`), progress 이벤트 그대로 |
| `POST /api/runs/{job_id}/cancel` | – | `{"ok":true}` (다음 단계 경계에서 중단) |
| `GET /api/kb/events?domain=` | – | `[{event_id,domain,date,title,summary,grade,sources}]` |
| `GET /` , `/static/*` | – | `ui/index.html`, 정적 파일 |

## 8. 화면 (ui/)

프레임워크 없음. `index.html` 하나에 화면 7개를 섹션으로 두고 해시 라우팅(`#dashboard`, `#intake`, `#run`, `#table`, `#impact`, `#outputs`, `#kb`, `#settings`). `app.js`는 `fetch('/api/...')`만 쓰고, `?mock=1`이면 `ui/mock.js`의 가짜 데이터로 동작(서버 없이 개발·시연 가능).

| 화면 | 내용 |
|---|---|
| 대시보드 | 보고서 카드/표(제목·발간·경과 연수·성숙도·판정 요약 배지), 소스·LLM 상태 요약, 최근 실행 |
| 접수 | 파일 드롭(pdf/hwpx/hwp/docx/txt) + ID·제목·발간연월 → 업로드 → 파싱 결과(쪽수·글자 수·스캔본 경고) |
| 실행 | 보고서 선택, 층 체크(L0/L1/L2), 옵션(블라인드 켬·반복, 재설문 설계서, 재실험 계획서, 합성 시뮬레이션 기본 꺼짐), 검색 공급자, 모델, 강제 재실행 단계 → 실행 → 단계 진행 표시(스테퍼) + 로그 스트림 + 토큰·비용 누계 + 취소 |
| 결론 대조표 | 판정 요약 배지, 필터(판정·종류·상태·다음 조치), 행 클릭 → 원/추적/블라인드 3열 + 사유 + 근거 링크 + 상류 전제; 본문 대조표 탭 |
| 영향 지도 | 사건 → 전제 → 결론 → 제언을 SVG로(간단한 3~4열 배치, 선 연결), 노드 클릭 시 상세 |
| 산출물 | 현행화 보고서(HTML iframe/새 창), 대조표 HTML, 브리프·설계서·검토 노트 목록, 내려받기 |
| 지식베이스 | 도메인별 사건 타임라인 |
| 설정 | 키 입력(마스킹 표시, 저장, 연결 확인), 모델 선택(목록 조회·검색), 검색 공급자, 온도·최대 단계, doctor 표 |

디자인: 설명 페이지(`docs/explainer`)와 같은 계열. 라이트 기본, 다크 지원(`prefers-color-scheme`). 바탕 `#F4F6F9`/`#0E141B`, 면 `#FFFFFF`/`#151D26`, 잉크 `#1A2330`/`#E7EDF3`, 강조 청록 `#0B6E8F`/`#4FB3D4`, 판정색 동일·강화 초록, 부분수정·약화 호박, 뒤집힘 빨강, 신규 청록, 판정불가 회색. 서체 `IBM Plex Sans KR`(본문) + `Gowun Batang`(큰 제목) Google Fonts, 폴백 시스템 서체. 표 숫자는 `tabular-nums`. 밀도는 대시보드답게(카드 남발 금지), 상태는 배지·스테퍼·진행바로. 모든 버튼은 하는 일을 그대로 쓴다(“실행”, “저장”, “연결 확인”).

## 9. 테스트 (app/tests/)

- `test_llm.py`: `requests.post` mock으로 chat 파싱·재시도·json_mode 확인
- `test_tools.py`: read_report_file 경로 탈출 차단, 블라인드 도구 세트에 read 없음, web_search provider 폴백 순서
- `test_runner.py`: MockLLM(정해진 응답 순서)으로 chains→…→compare 흐름, 스키마 오류 시 재요청, 재개(건너뜀), 블라인드 격리(대화 메시지에 브리프 외 문자열 없음)
- `test_parsing.py`: 작은 PDF·HWPX·TXT 샘플 파싱
- `test_server.py`: TestClient로 health·settings 마스킹·reports 목록·intake 업로드·runs 409

## 10. 실행 파일

- `run_app.bat`: `app/`로 이동 → `.venv` 없으면 생성 → `pip install -r requirements.txt` → `.env` 없으면 `.env.example` 복사 → `uvicorn server.main:app --host 127.0.0.1 --port 8765` 백그라운드 → 브라우저 `http://localhost:8765` 열기. `run_app.sh` 동일.
- `requirements.txt`: fastapi, uvicorn[standard], python-multipart, requests, httpx, python-dotenv, jsonschema, PyYAML, pypdf, trafilatura, beautifulsoup4, markitdown, defusedxml, pytest. (`pyhwp`는 선택, SETUP에 안내)
