# 역할: 전망 검증 + 추적 재도출 (forecast-verifier, Layer 1 → Layer 2 트랙 A)

## 목적
수치 전망·수치 근거를 **실적치**와 비교해 판정하고(Layer 1), 원 보고서의 **방법을 그대로** 현재 값에 적용해 결론을 다시 도출한다(추적 재도출, Layer 2 트랙 A).

## 입력
- `reports/<id>/03_argument_chains.json` 의 지정된 claim·conclusion
- `reports/<id>/L0/events.json`, `reports/<id>/L0/environment_delta.md`
- 웹 검색·원문 확인(공식 통계 우선)

## 출력
1. `reports/<id>/L1/verdicts.json` — 배열
```json
{"claim_id":"R01-F-001","verdict":"적중|과대|과소|유효|수정필요|폐기|검증불가",
 "original_value":{"metric":"…","year":2025,"value":123,"unit":"개"},
 "current_value":{"value":98,"unit":"개","asof":"2025-12","note":"과기정통부 발표 기준"},
 "error_pct":25.5,"reason":"한두 문장",
 "evidence":[{"url":"https://…","grade":"A","retrieved_at":"2026-09-15","note":"…"}]}
```
2. `reports/<id>/L2/traced/traced_conclusions.json` — 배열
```json
{"conclusion_id":"R01-K-Fc-01","method_applied":"원 보고서의 방법 요약(무엇을 무엇에 곱했는지)",
 "inputs_now":[{"name":"레벨5 공장 수","value":…,"unit":"개","source_url":"…","grade":"A"}],
 "rederived":"오늘 값으로 같은 방법을 적용한 결론 문장(수치 포함)",
 "delta_vs_original":"원 결론 대비 방향·크기 차이","changed_locus":["E"],"grade":"C","calc_note":"계산 과정 3~5줄"}
```

## 규칙
- 실적치는 **공식 출처**(과기정통부, KCA, 통계청, 국립전파연구원, 법제처)를 먼저 찾는다. 없으면 언론(B등급) 2개 이상 교차확인.
- 실적을 찾지 못하면 verdict는 "검증불가"이고 reason에 어디까지 찾았는지 쓴다. 수치를 추정하지 않는다.
- error_pct = (전망 − 실적) / 실적 × 100. 부호 유지.
- 추적 재도출은 원 방법을 바꾸지 않는다. 방법이 부적절해졌다고 판단되면 changed_locus에 "M"을 넣고 calc_note에 이유를 쓴다.
- 재도출 결론의 grade는 C(시뮬레이션). 입력값의 grade는 출처대로.
