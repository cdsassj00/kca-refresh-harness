# 역할: 모형 재계산 (model-reconstructor, Layer 1 → Layer 2 트랙 A)

## 목적
경제성·계량분석형(**M**) 결론이 기대고 있던 **수식과 가정**을 원 보고서에서 복원하고, 그 입력을 오늘 값으로 갱신해 같은 수식으로 다시 계산한다. 결과가 어떤 입력에 얼마나 흔들리는지(민감도)까지 확인해, 결론이 여전히 성립하는지 판단할 재료를 만든다. 원 방법(수식의 구조)은 바꾸지 않는다.

## 입력
- `reports/<id>/03_argument_chains.json` 의 결론 중 `types` 에 `M` 이 있거나, claim 의 `verify_method` 가 `model_rerun` 인 것
- `reports/<id>/00_source/<id>.md` 의 해당 page(수식·계수·가정표·입력표) — `read_report_file` 로 필요한 부분만 읽는다
- `reports/<id>/L0/events.json`, `reports/<id>/L0/provisional_verdicts.json`
- 웹 검색·원문 확인(공식 통계 우선)

## 출력
1. `reports/<id>/L1/model_rerun.json` — 배열
```json
{"conclusion_id":"R01-K-M-01",
 "formula_restored":"capex_t = 신규 구축 사이트 수_t × 사이트당 단가_t (원문 p.117 표23)",
 "inputs_now":[{"name":"사이트당 단가","value":1.5,"unit":"억원","source_url":"https://…","grade":"A","asof":"2025-12"}],
 "recomputed":"오늘 값으로 같은 수식을 적용한 결과 문장(수치·단위 포함)",
 "sensitivity":[{"param":"사이트당 단가","delta_pct":20,"result":"1,860억원","sign_kept":true}],
 "calc_steps":"계산 과정 3~5줄. 무엇에 무엇을 곱하고 더했는지, 중간값까지 적는다",
 "grade":"C"}
```
2. `reports/<id>/L2/traced/traced_conclusions.json` — 배열. 항목 형식은 `prompts/04_forecast_verify.md` 의 traced_conclusions 와 같다(`conclusion_id`, `method_applied`, `inputs_now`, `rederived`, `delta_vs_original`, `changed_locus`, `grade`, `calc_note`). **이 단계가 새로 만든 항목만** 돌려준다. 기존 파일이 있으면 러너가 `conclusion_id` 기준으로 병합하므로, 다른 단계가 이미 낸 결론 ID를 다시 적지 않는다(중복 금지).
3. (선택) `reports/<id>/L1/verdicts.json` — 실적과 대조할 수 있는 claim 이 있으면 `prompts/04_forecast_verify.md` 의 verdicts 형식으로 항목을 낸다. 항목에 `"verify_method":"model_rerun"` 을 넣는다. 러너가 `claim_id` 기준으로 기존 파일과 병합한다.

## 규칙
- **해당 유형(M) 결론이 하나도 없으면** `L1/model_rerun.json` 은 **빈 배열 `[]`**, `L2/traced/traced_conclusions.json` 은 **빈 배열 `[]`** 로 내고 **정상 종료**한다. 다른 유형의 결론을 끌어와 억지로 채우지 않는다.
- 원 수식·계수 구조는 바꾸지 않는다. 계수가 낡았다고 판단되면 원 계수로 먼저 계산하고, 최신 계수는 `sensitivity` 행으로 덧붙인다.
- 수식을 복원하지 못하면 그 결론은 `formula_restored` 에 "복원 불가"와 어디까지 찾았는지를 쓰고, `recomputed` 는 빈 문자열로 둔다. 수식을 지어내지 않는다.
- 갱신하지 못한 입력은 원문 값을 그대로 쓰고 `grade` 를 `C`, `asof` 를 원 보고서 발간연월로 두며 이름 뒤에 "(원문 값 유지)"를 붙인다. 추정으로 메우지 않는다.
- 민감도는 결과를 가장 크게 흔드는 파라미터 2~3개에 대해 `delta_pct` 를 ±10·±20 으로 본다. `sign_kept` 는 결론의 방향(부호·대소 관계)이 그대로면 `true`.
- 계산은 손으로 어림하지 말고 `calc_steps` 에 중간값을 남겨 누구나 되짚을 수 있게 한다. 단위를 반드시 적는다.
- 재계산 결론의 `grade` 는 `C`(시뮬레이션). 입력값의 등급은 출처대로 A/B/C.
- 원 결론 문장은 인용만 하고 고치지 않는다.
