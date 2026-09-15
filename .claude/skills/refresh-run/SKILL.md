---
name: refresh-run
description: 보고서 ID를 받아 접수→분류→결론·사슬→L0(사건 조사·영향 전파·잠정 판정)→L1(전망 검증·정책 추적)→L2(추적 재도출·블라인드·비교)→보고서 조립→검토 순으로 실행하는 총괄 절차서. 단계별 재개 가능(산출 파일이 이미 있으면 건너뜀, --from/--to 인수로 범위 지정). "refresh-run R01", "R03 현행화 돌려줘", "결론 재도출 실행" 요청에 사용.
argument-hint: <report_id> [<pdf>] [--from <단계>] [--to <단계>]
---

# refresh-run — 결론 재도출 총괄 절차

이 문서는 **순서와 연결**만 정한다. 각 단계의 규칙·출력 형식은 `prompts/NN_*.md`가 단일 원본이며, 서브에이전트에게는 "그 파일을 읽고 따르라"고 지시한다. 여기에 규칙을 옮겨 적지 않는다.

## 0. 인수와 준비
- `<report_id>`: `R` + 두 자리 숫자. 샘플은 `R01`~`R07`, 새 보고서는 `R08`부터. `<pdf>`는 접수(intake) 단계가 필요할 때만.
- `output`의 `hwpx`는 아직 렌더러가 없다(다음 단계). 지금은 `html`·Markdown만 생성되며 `hwpx`가 있어도 오류 없이 건너뛴다.
- `--from <단계>` 그 단계부터 강제로 다시 실행(이전 단계는 산출물이 있어야 함). `--to <단계>` 그 단계까지만 실행.
- 단계 이름(고정): `intake` `classify` `chains` `l0` `l1` `l2` `report` `critic`
- 시작 전에 `CLAUDE.md`의 규칙을 읽는다. 특히: 근거 없는 수치 금지·등급 필수, 작성자/검토자 분리, 블라인드에 원문 경로 금지, 설문·실험 미수행, old 문장 불변.
- 실행 로그: 단계마다 `reports/<id>/logs/refresh_run.log`에 한 줄(시각 | 단계 | 실행/건너뜀 | 담당 | 산출 파일) 추가. `logs/`는 git 제외 폴더다.

## 1. run_config.json
`reports/<id>/run_config.json`이 **있으면** 읽어 층·옵션을 정한다. 없으면 아래 기본값(설계서 7.3)으로 간다. UI 없이 파일만 편집해도 같은 효과다.
```json
{"report_id":"R01","layers":["L0","L1","L2"],
 "options":{"blind_rerun":{"enabled":true,"repeats":1},"survey_redesign":true,"experiment_plan":true,
            "synthetic_sim":{"enabled":false,"panel_size":200},"l0_rewrite_scope":"env_and_desk_updatable"},
 "sources":["openalex","kosis","data_go_kr","law","naver","web"],
 "output":["hwpx","html"],"period":{"since":"<발간일 다음 달>","until":"today"}}
```
- `layers`에 없는 층은 건너뛴다(예: `["L0"]`이면 l1·l2를 하지 않고 report·critic으로 간다).
- `blind_rerun.enabled=false`면 블라인드를 건너뛰고 비교기는 K''를 빈 값으로 둔다(이때 "동일" 판정은 나올 수 없다, `prompts/06_compare.md`).
- `survey_redesign`·`experiment_plan`은 R3 결론이 있을 때만 작동한다. `synthetic_sim`은 **기본 꺼짐**이며, 켜져 있어도 C등급·"시뮬레이션" 표기가 강제된다.
- `period.since`가 비어 있으면 `01_meta.json`의 `published` 다음 달로 잡는다.
- 스키마가 있으면 `python scripts/validate.py reports/<id>/run_config.json --schema run_config`로 확인한다.

## 2. 단계표와 재개 규칙
| 단계 | 프롬프트 원본 | 담당(서브에이전트) | 입력 | 산출(모두 있으면 건너뜀) |
|---|---|---|---|---|
| intake | `prompts/00_intake.md` 1단계 | 총괄이 직접(`python scripts/intake.py`) | PDF | `00_source/<id>.md`, `01_meta.json` |
| classify | `prompts/00_intake.md` 2단계 | general-purpose | 00_source, 01_meta | `02_classification.json` |
| chains | `prompts/01_chains.md` | general-purpose | 00_source, 01_meta, 02_classification | `03_argument_chains.json` |
| l0 | `02_delta.md`, `03_impact.md` (+ literature-scanner 규칙) | delta-researcher ∥ literature-scanner → impact-propagator | 01, 02, 03 | `L0/events.json`, `L0/environment_delta.md`, `L0/literature.json`(선택), `L0/provisional_verdicts.json`, `comparison_table.json`(v0), `L0/comparison_table_v0.json` |
| l1 | `04_forecast_verify.md` (+ policy·model 규칙) | forecast-verifier ∥ model-reconstructor ∥ policy-tracker | 03, L0 | `L1/verdicts.json` (+ `L1/policy_tracking.md`, `L1/model_rerun.json`, `L2/traced/traced_conclusions.json`) |
| l2 | `05_blind.md`, `06_compare.md` (+ survey·experiment 규칙) | 총괄(브리프) → blind-rerunner ∥ (L1 병행) → conclusion-comparator → survey-redesigner/experiment-planner | 03, L0, L1 | `L2/blind_input/brief.md`, `L2/compare/question_map.json`, `L2/blind_output/blind_conclusions.json`, `L2/traced/traced_conclusions.json`, `L2/compare/verdict_notes.md`, `comparison_table.json`(maturity L2), `L3/*.md`(R3만) |
| report | `prompts/07_report.md` | 총괄(스크립트) → general-purpose(조립·점검) | 전부 | `07_report/comparison_table.html`, `07_report/report.md`, `07_report/report.html` |
| critic | `prompts/08_critic.md` | refresh-critic | 전부(읽기만) | `07_report/critic_notes.md` |

재개 규칙
- `--from`이 없으면 단계마다 "산출" 열의 파일이 **모두** 있는지 본다. 있으면 건너뛰고 로그에 "건너뜀"을 남긴다. 일부만 있으면 그 단계를 다시 실행한다(부분 산출은 덮어쓴다).
- `--from X`는 X 이전 단계를 검사만 하고(없으면 중단·안내), X부터 끝(또는 `--to`)까지 산출물이 있어도 다시 실행한다.
- 다시 실행하는 단계는 기존 파일을 `<파일명>.bak.<시각>`으로 옮긴 뒤 쓴다. 단, `comparison_table.json`의 `old` 열과 `L0/comparison_table_v0.json`은 어떤 재실행에서도 바꾸지 않는다.
- 서브에이전트는 Agent 도구로 부른다. `subagent_type`은 `.claude/agents/<이름>`이 로드돼 있으면 그 이름, 아니면 `general-purpose`에 같은 지시를 준다. 담당이 "총괄이 직접"인 것만 이 세션에서 한다.

## 3. 단계별 실행 상세

### intake · classify
1. `python scripts/intake.py <id> <pdf>` (총괄이 직접). PDF가 아니면 `prompts/00_intake.md`의 변환 안내를 사용자에게 보여주고 중단한다.
2. classify: general-purpose에 지시 — "`prompts/00_intake.md`의 2단계를 읽고 `<id>`의 `02_classification.json`을 만들라. 입력 `reports/<id>/00_source/<id>.md`, `01_meta.json`."

### chains ∥ l0 사건 조사 (병렬)
classify가 끝나면 다음 셋을 **동시에** 띄운다(서로 입력이 겹치지 않는다).
- **chains** (general-purpose): "`prompts/01_chains.md`를 읽고 `<id>`의 `03_argument_chains.json`을 만들라. `02_classification.json`은 이미 있으니 읽기만 하고 덮어쓰지 말라(research_design 보강이 필요하면 필드 추가만)."
- **delta-researcher**: "`prompts/02_delta.md`를 읽고 따르라. 보고서 `<id>`, 발간일 `<published>`, 도메인 `<domains>`, 조사 기간 `<since>`~`<until>`. 도메인 키워드는 `kb/domains/<domain>.yaml`(있으면). 조사 전 `kb/events/<domain>/`을 읽고, 새 사건은 같은 형식으로 거기에도 남기라. 출력 `reports/<id>/L0/events.json`, `L0/environment_delta.md`."
- **literature-scanner**: "`.claude/agents/literature-scanner.md`의 규칙대로 `<id>`의 `L0/literature.json`·`literature.md`를 만들라. 입력 `01_meta.json`, `02_classification.json`." (chains가 아직 없으면 결론 연결은 rq 기준으로 두고, 끝난 뒤 총괄이 conclusion_id를 채우게 한다.)

delta-researcher는 `03_argument_chains.json`의 premises가 있으면 더 정확하다. chains가 먼저 끝나면 delta 프롬프트에 그 경로를 덧붙여 주고, 아니면 없이 시작한다.

### l0 영향 전파
chains와 delta가 모두 끝나면 **impact-propagator**: "`prompts/03_impact.md`를 읽고 따르라. 입력 `03_argument_chains.json`, `L0/events.json`, (있으면) `L0/literature.json`, 원문 `00_source/<id>.md`는 환경분석 장 인용에만. 출력 `L0/provisional_verdicts.json`, `comparison_table.json`(v0). `l0_rewrite_scope`가 `env_only`면 body_rows는 환경분석 장만."
끝나면 총괄이:
1. `comparison_table.json`을 `L0/comparison_table_v0.json`으로 복사한다(이미 있으면 건너뜀). 이것이 old 불변 검사의 기준이다.
2. `python scripts/render_table.py <id>` → `07_report/comparison_table.html`을 `07_report/comparison_table_v0_L0.html`로도 복사해 둔다.
3. `layers`에 L1·L2가 없으면 report로 간다.

### l1 근거 갱신 ∥ l2 블라인드 (병렬)
L0가 끝나면 아래를 **동시에** 띄운다. L1은 원문·사슬을 읽고, 블라인드는 브리프만 읽으므로 서로 오염되지 않는다.

**L1 — verify_method별로 나눠 병렬**(`03_argument_chains.json`의 claims를 verify_method로 묶어 각 담당에 ID 목록을 준다):
- **forecast-verifier**: backtest · case_refresh · kpi_track. "`prompts/04_forecast_verify.md`를 읽고 따르라. 대상 claim/conclusion: `<ID 목록>`. 병렬 실행이므로 출력은 `L1/verdicts.forecast.json`, `L2/traced/traced.forecast.json`."
- **model-reconstructor**: model_rerun(types M). 출력 `L1/model_rerun.json`, `L1/verdicts.model.json`, `L2/traced/traced.model.json`, 계산 스크립트 `L1/calc/`.
- **policy-tracker**: policy_track · standard_track(kind R, types P). 출력 `L1/verdicts.policy.json`, `L1/policy_tracking.md`.
- survey_map(types S)은 `survey_redesign` 옵션이 켜져 있으면 **survey-redesigner**가 대체 조사 탐색(R2)까지 여기서 하고 `L1/verdicts.survey.json`을 낸다. 재설문 설계서(R3)는 비교 뒤에 쓴다.
- 담당이 하나뿐이면 부분 파일 없이 04의 경로에 바로 쓴다.
- 모두 끝나면 총괄이 `L1/verdicts.*.json`을 claim_id 기준으로 합쳐 `L1/verdicts.json`, `L2/traced/traced.*.json`을 conclusion_id 기준으로 합쳐 `L2/traced/traced_conclusions.json`을 만든다(중복 ID는 나중 것이 아니라 등급이 높은 것). 스키마가 있으면 `python scripts/validate.py … --schema verdict`.

**L2 트랙 B — 블라인드**(`blind_rerun.enabled`일 때):
1. 총괄이 `L2/blind_input/brief.md`를 쓴다(아래 4절 규칙). 함께 `L2/compare/question_map.json`(`{"Q1":["<K-ID>", …]}`)을 **blind_input 바깥**에 둔다.
2. **blind-rerunner**를 Agent 도구로 부른다. 프롬프트에는 다음만 넣는다: "`prompts/05_blind.md`를 읽고 따르라. 입력은 `reports/<id>/L2/blind_input/brief.md` 하나. 출력 `reports/<id>/L2/blind_output/blind_conclusions.json`." 보고서 제목·발간기관·원문 경로·결론·수치·판정 어휘를 **절대 넣지 않는다**. `repeats`가 2 이상이면 같은 프롬프트로 별도 에이전트를 추가로 띄우고 출력은 `blind_conclusions_run2.json`… 으로 한다.
3. 끝나면 총괄이 격리 검사: 배열 마지막 원소의 `files_opened`가 `{prompts/05_blind.md, reports/<id>/L2/blind_input/brief.md}`의 부분집합인지 확인한다. 위반이면 그 파일을 `.rejected.<시각>.json`으로 옮기고 **새 에이전트**로 1회 재실행한다. 두 번째도 위반이면 블라인드 없음으로 처리하고 로그·critic에 남긴다.

### l2 비교·설계서
L1 합본과 블라인드가 모두 끝나면:
1. **conclusion-comparator**: "`prompts/06_compare.md`를 읽고 따르라. 입력은 그 파일의 목록 + `L2/compare/question_map.json` + 블라인드 반복 파일(있으면). `L0/comparison_table_v0.json`의 old를 보존하라. 출력 `comparison_table.json`(덮어쓰기), `L2/compare/verdict_notes.md`."
2. 비교 결과에서 status가 `R3 설계서`이거나 verdict가 `판정불가`인 결론을 types별로 나눠, 옵션이 켜진 것만 **동시에**:
   - types S → **survey-redesigner** → `L3/survey_redesign_<K-ID>.md`
   - types T → **experiment-planner** → `L3/experiment_plan_<K-ID>.md`
   - 두 옵션이 모두 꺼져 있거나 대상이 없으면 건너뛴다. `synthetic_sim`이 꺼져 있으면 시뮬레이션 절을 만들지 말라고 명시한다.
3. `python scripts/render_table.py <id>`로 대조표 HTML을 다시 만든다.

### report
1. 총괄이 `python scripts/render_table.py <id>`, `python scripts/render_report.py <id>`(있으면)를 실행한다.
2. general-purpose에 지시 — "`prompts/07_report.md`를 읽고 따르라. `<id>`의 `07_report/report.md`·`report.html`을 목차 8절대로 점검·보완하고 자가 점검표를 통과시켜라. old 문장과 수치는 입력 파일에서 그대로 옮기고 새로 만들지 말라."
3. `output`에 `hwpx`가 있으면 07의 HWPX 안내를 따른다(지원 스크립트가 없으면 로그에 "HWPX 미생성" 기록).

### critic
1. **refresh-critic**: "`prompts/08_critic.md`를 읽고 따르라. 대상 `<id>`. 출력은 `07_report/critic_notes.md` 하나."
2. 결과가 FAIL이면 지적의 "담당 역할"별로 해당 서브에이전트에 지적 표를 붙여 재작업을 시키고(원본 프롬프트를 다시 읽게 함), 영향받는 뒷단계(비교 → 렌더 → 보고서)를 다시 돌린 뒤 critic을 다시 부른다. 최대 2회. 그래도 FAIL이면 중단하고 사용자에게 critic_notes.md를 보여준다.
3. 총괄은 지적을 스스로 고치지 않는다(작성자/검토자 분리). 파일 복사·합치기·렌더만 한다.

## 4. 블라인드 브리프 작성 규칙 (총괄이 직접 쓴다)
실제 예: `reports/R01/L2/blind_input/brief.md`. 그 구조(연구질문 / 방법의 구조 / 답해야 할 항목 / 기간)를 그대로 쓴다.
- 재료는 `02_classification.json`의 `research_design.rq`·`methods`와 `03_argument_chains.json`의 `conclusions[].method`뿐이다. `statement`·`claims[].original_value`·`premises`의 수치는 보지 않은 것처럼 쓴다.
- **금지**: 원 결론 문장·요지, 원 수치(전망값·비율·계수·단가·CAGR), 시나리오별 값, 판정 어휘, 보고서 제목·발간기관·저자, 원문 page. 방법에 나오는 파라미터는 "값은 스스로 정한다"로 바꾼다.
- **허용**: 연구질문, 방법의 뼈대(무엇을 무엇에 곱하는지), 시나리오 개수와 이름, 답해야 할 항목(연도·단위 지정), 오늘 날짜와 "최신 공식 발표치를 쓰고 asof를 적으라"는 지시, 환경 변화의 **주제**(수치 없이).
- 항목(Q)은 결론마다 하나 이상이 대응되게 만들되, 결론 ID는 브리프에 쓰지 않고 `L2/compare/question_map.json`에 둔다.
- 쓰고 나서 확인: `claims[].original_value.value`의 값과 `conclusions[].statement`에 나오는 두 자리 이상 숫자(연도 제외)가 brief.md에 하나도 없어야 한다. 있으면 지우고 다시 확인한다.

## 5. 마무리
1. 성숙도 결정: 잠정 판정만 있으면 `L0`, `L1/verdicts.json`까지 있으면 `L1`, `comparison_table.json`의 maturity가 `L2`·`L2(부분)`이면 `L2`, 판정불가·R3 결론 모두에 `L3/` 설계서가 붙었으면 `L3`. critic이 PASS일 때만 갱신한다.
2. 레지스트리 갱신: `scripts/registry.py`의 `set_maturity(path, "<id>", "<레벨>")`를 호출한다(예: `python -c "from scripts.registry import set_maturity, DEFAULT; set_maturity(DEFAULT, '<id>', '<레벨>')"`). 스크립트가 아직 없으면 로그에 "registry 미갱신"을 남기고 실패로 치지 않는다.
3. 사용자에게 보고: 판정 요약(summary), 핵심 3건, critic 결과, 산출 파일 경로, 건너뛴 단계, 미사용 소스.

## 6. 실패·중단 처리
- 서브에이전트가 산출 파일을 만들지 못하면 같은 지시로 1회 재시도, 그래도 실패면 그 단계에서 멈추고 로그와 함께 사용자에게 알린다. 다음 단계로 넘어가지 않는다.
- 스크립트(`scripts/*.py`)가 없거나 실패하면 그 단계의 프롬프트에 적힌 대체 방법(수동 조립 등)을 쓰고 로그에 남긴다.
- 층별로만 돌리고 싶으면 `refresh-l0` `refresh-verify` `refresh-rederive` `refresh-report` 스킬을 쓴다. 각 스킬은 이 문서의 해당 절을 참조한다.
