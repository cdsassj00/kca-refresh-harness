---
name: refresh-verify
description: Layer 1만 실행. 결론을 떠받치던 수치를 실적·최신 조사·재계산으로 갱신한다(전망 백테스트, 모형 재계산, 정책 제언 추적, 설문 대체 조사 탐색). "R01 숫자 다시 맞춰봐", "근거 갱신", "L1" 요청에 사용. L0 산출물이 있어야 한다.
argument-hint: <report_id> [--only forecast|model|policy|survey] [--redo]
---

# refresh-verify — 숫자 다시 맞춰보기 (Layer 1)

전체 절차와 서브에이전트 호출 방식은 `.claude/skills/refresh-run/SKILL.md`의 **3절 "l1 근거 갱신"** 을 따른다. 이 문서는 L1만 돌릴 때의 전제와 순서다.

## 전제 확인
`03_argument_chains.json`, `L0/events.json`, `L0/environment_delta.md`, `L0/provisional_verdicts.json`이 있어야 한다. 없으면 `refresh-l0`를 먼저 돌린다.

## 순서
1. `03_argument_chains.json`의 `claims[]`를 `verify_method`로 묶어 담당별 ID 목록을 만든다.
   | verify_method | 담당 | 부분 출력 |
   |---|---|---|
   | backtest · case_refresh · kpi_track | forecast-verifier (`prompts/04_forecast_verify.md`) | `L1/verdicts.forecast.json`, `L2/traced/traced.forecast.json` |
   | model_rerun | model-reconstructor (에이전트 카드 규칙) | `L1/model_rerun.json`, `L1/verdicts.model.json`, `L2/traced/traced.model.json`, `L1/calc/*.py` |
   | policy_track · standard_track | policy-tracker (04 형식 + 카드 규칙) | `L1/verdicts.policy.json`, `L1/policy_tracking.md` |
   | survey_map | survey-redesigner의 대체 조사 탐색(R2) — `run_config.options.survey_redesign`이 켜진 경우 | `L1/verdicts.survey.json` |
   `--only`가 있으면 그 담당만 띄운다.
2. 담당들을 **동시에** 띄운다. 각 프롬프트에는 원본 프롬프트 경로, 대상 ID 목록, 부분 출력 경로, `L0/events.json`·`environment_delta.md` 경로를 넣는다. 담당이 하나뿐이면 부분 파일 없이 04의 경로에 바로 쓰게 한다.
3. 총괄이 합친다: `L1/verdicts.*.json` → `L1/verdicts.json`(claim_id 기준), `L2/traced/traced.*.json` → `L2/traced/traced_conclusions.json`(conclusion_id 기준). 중복 ID는 evidence 등급이 높은 항목을 남긴다. 스키마가 있으면 `python scripts/validate.py reports/<id>/L1/verdicts.json --schema verdict`.
4. 확인: verdict가 `검증불가`인 항목마다 reason에 "어디까지 찾았는지"가 있는지, current_value에 asof·출처·등급이 있는지 본다. 없으면 담당에게 되돌린다.
5. `comparison_table.json`의 해당 결론행 status를 `L1 근거갱신`으로 바꾸고 evidence에 L1 출처를 합친다(old·new 문장은 손대지 않는다). `python scripts/render_table.py <id>`.
6. `scripts.registry.set_maturity(path, "<id>", "L1")` 호출(스크립트 있을 때).

## 재실행
`--redo`는 부분 파일과 합본을 `.bak.<시각>`으로 옮긴 뒤 다시 만든다.

## 끝나면
claim별 판정 분포(적중·과대·과소·유효·수정필요·폐기·검증불가)와 검증불가 사유를 보고한다. 다음은 `refresh-rederive`.
