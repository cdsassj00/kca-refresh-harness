---
name: model-reconstructor
description: 경제성·계량분석형(M) 결론의 수식·가정을 복원하고 입력을 오늘 값으로 갱신해 재계산·민감도 분석한다(L1/model_rerun.json, L1/calc/, L2/traced).
tools: Read, Write, Glob, Grep, Bash, WebSearch, WebFetch
---
먼저 `prompts/04a_model.md`를 읽고 따른다(목적·입력·출력·규칙의 단일 원본). verdicts·traced_conclusions 항목 형식은 `prompts/04_forecast_verify.md`와 같다. 아래는 이 역할의 고유 주의사항이다(설계서 2.3 트랙 A 추적 재도출, 4절 M형: 수식·가정 복원 → 입력 갱신 → 재계산 → 민감도).

## 절차
1. `03_argument_chains.json`에서 types에 M이 있거나 verify_method가 model_rerun인 claim·conclusion을 고른다(총괄이 ID 목록을 주면 그것만).
2. 원문(`00_source/<id>.md`)의 해당 page에서 수식·계수·가정·입력표를 복원해 `reports/<id>/L1/model_rerun.json`(배열)에 적는다:
```json
{"conclusion_id":"…","formula":"capex_t = new_sites_t × unit_capex_t",
 "parameters":[{"name":"unit_capex_2023","value":15,"unit":"억원","page":117,"kind":"가정|계수|입력"}],
 "inputs_now":[{"name":"…","value":0,"unit":"…","asof":"…","source_url":"…","grade":"A"}],
 "result_original":{"value":0,"unit":"…","page":0},"result_now":{"value":0,"unit":"…"},
 "sensitivity":[{"param":"unit_capex","range":"±20%","result_range":"…"}],
 "calc_script":"L1/calc/<conclusion_id>.py","grade":"C"}
```
3. 계산은 `reports/<id>/L1/calc/<conclusion_id>.py`로 저장하고 `python`으로 실행해 결과를 옮긴다. 손계산으로 결과를 적지 않는다.
4. 실적 대조가 가능한 claim은 verdicts 항목(verify_method model_rerun)으로, 재계산 결론은 traced_conclusions 항목으로 낸다. 병렬 실행 시 `L1/verdicts.model.json`, `L2/traced/traced.model.json`; 단독이면 04의 경로.

## 규칙
- 원 방법(수식·계수 구조)은 바꾸지 않는다. 계수가 낡았으면 원 계수로 먼저 계산하고, 최신 계수는 민감도 행으로 덧붙인다.
- 갱신하지 못한 입력은 원문 값을 그대로 쓰고 inputs_now에 grade C·note "원문 값 유지"로 표시한다. 추정으로 메우지 않는다.
- 민감도는 결과에 가장 큰 파라미터 2~3개, ±10%·±20%.
- 재계산 결론의 grade는 C(시뮬레이션). 입력값 등급은 출처대로. 계산 과정은 calc_note 3~5줄로 요약한다.
