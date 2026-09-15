# KCA 연구보고서 결론 재도출·현행화 하네스 — 설계 v4 (확정)

작성일: 2026-09-15 / 상태: **확정** (사용자 결정 반영: 블라인드 재수행 기본 켬·서브에이전트 추가 사용 허용, UI는 FastAPI+HTML, UI가 로컬 하네스를 직접 실행, 유료 논문 API 커넥터 실제 구현)
다음 단계: `writing-plans`로 구현 계획 작성 → P0 착수

---

## 0. 한 줄 정의

> 어떤 KCA 연구보고서를 넣어도, 보고서의 **결론·발견·제언 하나하나에 대해** 「오늘 같은 연구를 다시 하면 같은 결론이 나오는가」를 판정한다. 결론이 서 있는 **논증 사슬(전제→근거→방법→결론)** 을 복원하고, 전제(환경)와 근거(데이터)를 현재로 갱신한 뒤, 원 방법으로 **추적 재도출**하고 원 결론을 모르는 에이전트가 **블라인드 재수행**하여 세 결론(원·추적·블라인드)을 비교한다. 결과는 결론 대조표와 현행화 보고서(HWPX·HTML)로 나오고, 재설문·재실험이 필요한 결론은 판정 불가로 표시하고 설계서를 붙인다. 로컬 웹 UI에서 층·옵션·소스·포맷을 고르고 실행·열람한다.

**자료 최신화 ≠ 결론 재도출.** 자료 최신화는 같은 문장에 새 숫자를 넣는 일이고, 결론 재도출은 새 숫자·새 환경에서 같은 방법을 다시 돌렸을 때 결론이 유지되는지 묻는 일이다. 최종 산출물은 항상 후자의 판정이며, 전자는 입력이다.

---

## 1. 요구사항과 확정 사항

| 요구 | 설계 |
|---|---|
| 같은 결론이 나오는가가 핵심 | 결론 세트 → 논증 사슬 → 추적 재도출 + 블라인드 재수행 → 비교 판정 7종. 보고서 첫 장이 판정 요약 |
| 환경 변화가 본문을 바꾼다 | 논증 사슬 = 의존 그래프. 사건 → 전제 → 결론으로 영향 전파 |
| 신구 대조표 출력 | 결론 대조표(상단) + 본문 대조표(하단). HWPX·HTML |
| 즉시 적용 가능한 부분은 즉시 | Layer 0 = 전제 갱신·제언 추적·후속문헌·영향 전파 → 결론별 잠정 판정 |
| 유형별 최신화, 재설문·재실험 | 유형 분류 + R1/R2/R3, R3는 판정불가 + 설계서 |
| 다른 보고서도 같은 경로 | `reports/<id>/`, 레지스트리, 성숙도 L0~L3, 공유 지식베이스 |
| 논문·통계·법령 API, 유료 포함 | 소스 커넥터 + `.env` + `doctor`. **T3 유료 커넥터도 구현**(키 있으면 활성) |
| 무료 API 발급 문서 | `docs/api_keys_guide.md`(초안 있음, P0에서 검증) |
| HWPX·HTML | render.py가 같은 JSON에서 두 포맷 |
| UI | **FastAPI + 단일 HTML 앱**. UI 서버가 로컬에서 `claude -p`(헤드리스 Claude Code)를 서브프로세스로 실행하고 로그를 스트리밍 |
| 블라인드 재수행 | 기본 켬. 결론당 서브에이전트 1회 추가 허용 |

### 가정
- A1. 실행·시연은 같은 PC의 Claude Code(데스크톱, CLI 2.1.x 설치 확인) + 로컬 UI(`http://localhost:8765`).
- A2. 딥리서치 = WebSearch/WebFetch 서브에이전트 + API 커넥터 + 공유 지식베이스.
- A3. 실제 설문·실험은 수행하지 않는다. 합성 시뮬레이션은 UI 옵션, 기본 꺼짐, C등급.
- A4. 첫 배치 7편. 시연은 7편 L0 + R01 L2.
- A5. API 키는 사용자가 `.env`에 직접 입력. UI는 상태만 표시.

---

## 2. 뼈대: 결론 단위 재도출

### 2.1 결론 세트와 논증 사슬
classify 직후 결론 세트 K를 뽑는다: 연구질문(RQ), 핵심 발견(F), 전망(Fc), 정책제언(R). 각 K_i에 대해:
```
K_i ← M(방법) ← P[](전제: 환경분석의 사실·가정) + E[](근거: 데이터·조사결과·파라미터·사례)
```
저장 `03_argument_chains.json`(K, M, P[], E[], 원문 위치). 명시 인용은 규칙 추출, 암묵 재사용(같은 수치·가정)은 후보 생성 후 LLM 판정. 이것이 의존 그래프이며 영향 전파의 경로다.

### 2.2 세 층은 모두 K_i 판정에 근거를 공급한다
| 층 | 갱신 대상 | K_i에 주는 것 | 판정 수준 |
|---|---|---|---|
| Layer 0 | 전제 P, 제언 R의 채택 상태, 후속 문헌 | 무효화된 전제, 외부 재도출 증거 → **잠정 판정** | 잠정 |
| Layer 1 | 근거 E(실적·최신 조사·재계산 파라미터) | 결론을 떠받치던 숫자의 현재 값 | 근거 갱신 |
| Layer 2 | 결론 K | 추적 재도출 + 블라인드 재수행 → 비교 → **최종 판정** | 최종 |

### 2.3 Layer 2 두 트랙과 비교기
- **트랙 A 추적 재도출**: 원 방법 M을 현재 P'·E'에 적용해 K'_i. 무엇이 바뀌어 결론이 달라졌는지 설명.
- **트랙 B 블라인드 재수행**: `blind-rerunner` 서브에이전트가 **원 결론·원 본문 없이** RQ + M + 현재 데이터·환경 브리프만 받아 K''_i. 격리: 입력은 `L2/blind_input/`에만 두고 원문 경로를 프롬프트에 주지 않으며, 실행 로그에서 파일 접근을 검사한다. 결론마다 1회, 필요 시 복수 실행(합의 확인).
- **비교기 `conclusion-comparator`**: K_i / K'_i / K''_i 비교 → 판정 + 달라진 이유의 위치(P/E/M).

판정 어휘: **동일 / 강화 / 부분수정 / 약화 / 뒤집힘 / 신규 결론 / 판정 불가**. 수치 규칙(templates/verdict_rules.yaml): 예측 오차 ±10% 이내 동일, 10~30% 부분수정, 부호 반전 뒤집힘, 근거 부재 판정불가 등.

### 2.4 Layer 0 다섯 작업
| 작업 | 내용 | K_i에 주는 것 |
|---|---|---|
| L0-1 환경분석 현행화 | 환경 절 단위 사건 수집(kb → API → 웹), 절별 원문 ↔ 현재 | 전제 유효/무효 |
| L0-2 배경·필요성 재평가 | 문제의식 유효/변형/해소 | RQ 유효성 |
| L0-3 제언 추적 | 채택·입법·시행·폐기·결과 | R형 결론 상태 |
| L0-4 후속 문헌 스캔 | 발간 이후 논문·보고서, 상충 문헌 표시 | 외부 재도출 증거 |
| L0-5 영향 전파 + 잠정 판정 | 사건 → P/E → K_i, 결론별 잠정 판정·예상 방향·필요 검증. 데스크리서치로 다시 쓸 수 있는 본문 절은 즉시 갱신 | 잠정 판정 |
산출물: 환경변화 브리프 + 결론 대조표 v0 + 본문 대조표 v0.

### 2.5 성숙도
L0 잠정 판정 / L1 근거 갱신 / L2 최종 판정 + 현행화 보고서 / L3 판정불가 결론에 설계서 첨부

---

## 3. 신구 대조표 (2단)
- **결론 대조표**: K-ID, 원 결론(구), 추적 재도출 결론(신), 블라인드 결론, 판정, 달라진 이유(P/E/M + 사건·근거 ID), 증거 등급, 상태
- **본문 대조표**: ID, 위치, 구, 신, 변경유형(유지/수치갱신/서술수정/폐기/신규추가/재수행필요), 사유·근거, 등급, 상태, 연결 K-ID
- 출력: `comparison_table.json` → HWPX(현행 | 현행화(안) | 비고; 결론 대조표 본문, 본문 대조표 부록) + HTML(전체 열, 판정·등급·상태·장 필터, 근거 링크, 원문 쪽 이동)

---

## 4. 유형·주장 원장·증거 등급
| 코드 | 유형 | 근거 E 갱신 방법 | 재수행 |
|---|---|---|---|
| F | 전망·예측형 | 실적 수집 → 백테스트 → 재전망 | R1 |
| M | 경제성·계량분석형 | 수식·가정 복원 → 입력 갱신 → 재계산 → 민감도 | R1~R2 |
| S | 실태조사·설문형 | 이후 공식조사 대체 → 재설문 설계서(+옵션 합성패널) | R2~R3 |
| P | 정책·제도 대안형 | 채택·입법·시행 추적 | R1 |
| T | 기술·표준·실험형 | 표준 추적 → 재실험 계획서 | R2~R3 |
| B | 사례·동향 조사형 | 사례 현재 상태 + 신규 | R1 |
| G | 기관 전략·사업형 | 실행·KPI 추적 | R1~R2 |
주장 원장 `claims.jsonl`은 E 단위 검증 항목이며 K-ID에 연결. 증거 등급 A(1차·공식) / B(2차) / C(추정·시뮬레이션·블라인드 결론). C는 본문에 "시뮬레이션" 명시.

---

## 5. 근거 소스 계층
`scripts/evidence.py {papers|stats|law|bills|news|web|doctor}` — 커넥터 `scripts/sources/<name>.py` 1파일 1소스, 공통 인터페이스 `search(query, since, until, limit) -> list[EvidenceRecord]`, 동일 JSONL 출력, 키 없는 소스 자동 비활성 + 보고서에 "미사용 소스" 기록, `kb/cache/` 공유.

- **T0 키 없음**: OpenAlex, Crossref, arXiv(기존 스킬), Semantic Scholar(키 선택), OECD, World Bank, Consensus MCP, Claude WebSearch/WebFetch
- **T1 무료 키·국내**: 공공데이터포털(KCI 논문정보 포함), KOSIS, 법제처, 열린국회정보, NAVER, ECOS, KCI 직접, 국회도서관
- **T2 무료 키·선택**: ScienceON, IEEE Xplore, CORE, Springer, Lens
- **T3 유료·구독(구현)**: Scopus, Web of Science, Dimensions, Exa, Tavily, Perplexity Sonar, SerpAPI(Scholar), DBpia, BigKinds

환경변수 이름은 `docs/api_keys_guide.md`와 `.env.example`에 고정. 우선순위: NAVER → KOSIS → 공공데이터포털 → 법제처 → 나머지.

---

## 6. 공유 지식베이스와 도메인 프로파일
`kb/events/<domain>/<yyyy-mm>_<slug>.md`(사건 1건 1파일: 날짜·요지·영향 지표·출처·등급), `kb/evidence/`, `kb/cache/`, `kb/sources.md`, `kb/domains/*.yaml`(지표 데이터 위치·법령·기관·학술지·키워드; 도메인 6: spectrum, emf_inspection, broadcast_media, network_5g6g, ict_qualification, kca_management). 보고서마다 kb 선독후기.

---

## 7. 제어 UI (FastAPI + HTML)

### 7.1 구조
- 백엔드 `ui/server.py`(FastAPI, uvicorn, `localhost:8765`), 정적 프런트 `ui/static/index.html` + `app.js` + `style.css`(프레임워크 없이 단일 페이지, 화면 전환은 해시 라우팅). 파일 기반 상태를 읽기만 하며 쓰는 것은 `run_config.json`과 `runs/` 뿐.
- API
  - `GET /api/registry` 레지스트리 + 결론 판정 요약
  - `GET /api/reports/{id}` 메타·분류·성숙도 / `GET /api/reports/{id}/comparison` / `.../chains` / `.../events` / `.../artifacts`
  - `GET /api/kb/events?domain=` / `GET /api/sources/doctor`(캐시 10분)
  - `POST /api/runs` body=run_config → `run_id`; `GET /api/runs/{run_id}/events`(SSE) ; `POST /api/runs/{run_id}/cancel`
  - `GET /api/reports/{id}/download?fmt=hwpx|html&doc=comparison|report|brief`
- 실행 방식: `subprocess.Popen(["claude","-p", f"/refresh-run {id}", "--output-format","stream-json","--verbose","--permission-mode","acceptEdits","--allowedTools", ...], cwd=PROJECT_ROOT)`. stdout의 stream-json 이벤트를 SSE로 중계하고 `reports/<id>/logs/run_<ts>.jsonl`에 저장. 보고서당 1회 실행 잠금(`runs/<id>.lock`). 실패 시 UI가 동일 명령을 복사 버튼으로 제공(Claude Code 창에서 실행).
- 헤드리스 권한: `.claude/settings.json`에 프로젝트 허용 규칙(스크립트 실행 `Bash(python scripts/*)`, `WebSearch`, `WebFetch`, `Read`, `Write`, `Edit`, `Agent`)을 두어 프롬프트 없이 진행. UI 서버는 `.env`를 읽지 않으며 키는 하네스 프로세스에서만 로드.

### 7.2 화면 7개
| 화면 | 기능 |
|---|---|
| 대시보드 | 레지스트리(보고서·도메인·유형·성숙도), 결론 판정 요약(동일/수정/뒤집힘/판정불가), 소스 상태 |
| 실행 설정 | 보고서 → 층(L0/L1/L2) → 옵션: 블라인드 재수행(기본 켬, 반복 횟수), 재설문 설계서, 재실험 계획서, 합성 시뮬레이션(끔/켬·패널 규모), L0 즉시갱신 범위 → 소스 체크(키 없는 것 비활성) → 출력(HWPX/HTML) → 기간 → 저장 → 실행(로그 스트림) |
| 결론 대조표 | 필터, 행 클릭 시 원/추적/블라인드 3열 + 논증 사슬 + 근거 링크 |
| 본문 대조표 | 장·변경유형·상태 필터, 원문 쪽 이동, 내려받기 |
| 영향 지도 | 사건 → 전제/근거 → 결론 → 제언 (표 + 간단 SVG 그래프) |
| 산출물·로그 | 브리프·보고서·설계서·실행 로그 |
| 지식베이스·소스 | kb 타임라인, doctor 결과, 발급 가이드 링크 |

### 7.3 run_config.json
```json
{"report_id":"R01","layers":["L0","L1","L2"],
 "options":{"blind_rerun":{"enabled":true,"repeats":1},"survey_redesign":true,"experiment_plan":true,
            "synthetic_sim":{"enabled":false,"panel_size":200},"l0_rewrite_scope":"env_and_desk_updatable"},
 "sources":["openalex","kosis","data_go_kr","law","naver","web"],
 "output":["hwpx","html"],"period":{"since":"2023-04-20","until":"today"}}
```
`refresh-run` 스킬은 이 파일을 읽어 층·옵션을 결정한다. UI 없이 파일만 편집해도 실행된다.

---

## 8. 스캐폴딩 골격
```
[프로젝트 루트]
├─ CLAUDE.md, .env.example, .env(gitignore), registry.csv, requirements.txt
├─ .claude/settings.json      # 헤드리스 허용 규칙
├─ .claude/skills/  refresh-run, refresh-intake, refresh-classify, refresh-chains, refresh-ledger,
│                   refresh-l0, refresh-verify, refresh-rederive, refresh-report
├─ .claude/agents/  delta-researcher, literature-scanner, policy-tracker, impact-propagator,
│                   forecast-verifier, model-reconstructor, survey-redesigner, experiment-planner,
│                   blind-rerunner, conclusion-comparator, refresh-critic
├─ templates/  taxonomy.yaml, verdict_rules.yaml, schemas/(conclusion, chain, claim, verdict, event, comparison_row, run_config),
│              environment_brief.md, comparison_table.md, survey_redesign.md, experiment_plan.md, report_outline.md
├─ scripts/    intake.py, evidence.py, sources/*.py, validate.py, backtest.py, render.py
├─ ui/         server.py, static/(index.html, app.js, style.css)
├─ kb/         events/ evidence/ cache/ sources.md domains/
├─ reports/<id>/  00_source 01_meta.json 02_classification.json 03_argument_chains.json 03_claims.jsonl
│                 L0/ L1/ L2/(blind_input/ blind_output/ traced/ compare/) comparison_table.json 07_report/ logs/
├─ runs/       <run_id>.json, <id>.lock
└─ docs/       superpowers/specs/, api_keys_guide.md, user_guide.md
```

---

## 9. 현행화 보고서 목차
1. 결론 재도출 요약(N개 중 판정별 개수, 핵심 3건) 2. 원 연구 개요·논증 사슬 3. 환경변화 브리프 4. 결론 대조표 5. 근거 재검증 매트릭스 6. 재수행 시뮬레이션 상세 7. 새 정책 시사점·혁신 대안(신규·뒤집힘에서, 근거 ID) 8. 부록(본문 대조표, 설계서, 사용·미사용 소스, 검토 기록)

---

## 10. 시연 시나리오 (20분)
1. UI 대시보드: 7편 L0, 결론 잠정 판정 요약, 소스 상태
2. R01 실행 설정 → 실행(사전 로그 재생 가능)
3. R01 결론 대조표: 원/추적/블라인드 3열, 판정, 달라진 이유
4. 뒤집힌 결론의 영향 지도
5. R05 판정불가 결론의 재실험 계획서, HWPX·HTML 열기, kb 타임라인

---

## 11. 구현 단계 (writing-plans에서 작업 단위로 분해)
| 단계 | 내용 | 완료 기준 |
|---|---|---|
| P0 골격·소스·문서 (1일) | 폴더·CLAUDE.md·settings·taxonomy·verdict_rules·스키마·registry·`.env.example`·evidence.py T0+doctor·api_keys_guide 검증 | doctor T0 정상 |
| P1 intake·classify·chains·ledger (1.5일) | 7편 intake, 결론 세트·논증 사슬, R01·R04 주장 원장 | 표본 20개 검수 |
| P2 Layer 0 + 대조표 v0 (2일) | delta/literature/policy/impact, 잠정 판정, 대조표 JSON·HWPX·HTML | 7편 L0 |
| P3 UI (1.5일) | FastAPI 서버·SSE·단일 HTML 7화면·실행 | UI에서 R01 L0 실행·열람 |
| P4 Layer 1 F/M/P + T1/T3 커넥터 (1.5일) | forecast-verifier·backtest·model-reconstructor·정책 심화, 키 들어온 커넥터 활성 | R01 근거 갱신 |
| P5 Layer 2 + S/T (2일) | blind-rerunner(격리)·추적 재도출·comparator·survey/experiment planner·report·critic | R01 최종 판정 보고서, R05 계획서 |
| P6 배치·리허설 (0.5일) | 전체 재실행, 리허설 | critic 0건, 20분 내 |
합계 약 10 작업일.

---

## 12. 리스크와 대응
| 리스크 | 대응 |
|---|---|
| 블라인드 에이전트 원문 우회 | 격리 폴더만 제공, 원문 경로 미제공, 로그 파일접근 검사 |
| 논증 사슬 오복원 | 규칙+LLM 후보, 표본 검수, UI 영향 지도에서 수정 |
| 판정 어휘 남용 | verdict_rules.yaml 수치 규칙 |
| 대조표 과다 | 기본 "변경 있음"만, HWPX 본문은 결론 대조표 |
| `claude -p` 권한 프롬프트·실패 | settings.json 허용 규칙, 실패 시 명령 복사 안내 |
| API 키 지연 | T0만으로 L0 동작 |
| 숫자 환각 | 출처 없는 수치 거부, WebFetch 재확인, 등급 필수 |
| 설문·실험을 한 것처럼 보임 | R3 기본 설계서, 합성은 옵션 + C등급 + 워터마크 |
| 범위 팽창 | 7편·유형 7·도메인 6·UI 7화면 고정 |
