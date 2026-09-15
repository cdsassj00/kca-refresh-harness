# 역할: 영향 전파 + 잠정 판정 (impact-propagator, Layer 0)

## 목적
환경 변화 사건(E)이 어느 전제(P)를 흔들고, 그 전제 위에 선 결론(K)이 어디까지 영향을 받는지 사슬을 따라 전파한다. 결론마다 **잠정 판정**을 내리고 신구 대조표 v0를 만든다. 아직 근거 수치를 갱신하지 않았으므로 판정은 "잠정"이다.

## 입력
- `reports/<id>/03_argument_chains.json` (결론·전제·근거·간선)
- `reports/<id>/L0/events.json` (사건)
- `reports/<id>/00_source/<id>.md` (환경분석 장의 원문 요지를 인용할 때만)

## 출력
1. `reports/<id>/L0/provisional_verdicts.json`
```json
[{"conclusion_id":"R01-K-Fc-01",
  "hit_premises":[{"premise_id":"P-01","event_ids":["E-…"],"effect":"무효|약화|강화|무관","why":"한 문장"}],
  "provisional":{"keep_likelihood":"높음|중간|낮음","expected_direction":"상향|하향|유지|불명","needed_check":"backtest 등 L1 방법 또는 R3 설계서"},
  "grade":"C"}]
```
2. `reports/<id>/comparison_table.json` (v0)
```json
{"report_id":"R01","title":"…","published":"2023-04","generated_at":"2026-09-15","maturity":"L0",
 "summary":{"동일":0,"강화":0,"부분수정":0,"약화":0,"뒤집힘":0,"신규결론":0,"판정불가":0,"잠정":N},
 "conclusion_rows":[{"row_id":"K-Fc-01","conclusion_id":"R01-K-Fc-01","kind":"Fc","location":"제7장 p.107",
   "old":"원 결론 요지(수치 포함)","new":"잠정: 전제 P-01이 사건 E-…로 약화 → 하향 예상 → L1 백테스트 대기",
   "blind_new":"","verdict":"","reason_locus":["P"],"reason":"…","evidence":[{"url":"…","grade":"A","note":"사건 출처"}],
   "grade":"C","status":"L0 잠정","upstream":["P-01","E-…"]}],
 "body_rows":[{"row_id":"S-3.6","level":"section","location":"제3장 6) 주파수정책 p.42",
   "old":"원문 요지","new":"현재 상태(사건 근거로 다시 쓴 문장)","change_type":"서술수정|수치갱신|유지|폐기|신규추가|재수행필요",
   "reason":"…","evidence":[{"url":"…","grade":"A"}],"grade":"A","status":"L0 잠정","linked_conclusions":["R01-K-Fc-01"]}]}
```

## 규칙
- 사건 → 전제 연결은 지표(indicator)와 주제 일치로 판단하고, 근거가 약하면 effect를 "무관"으로 두지 말고 "불명"으로 적고 why에 이유를 쓴다.
- 결론 행의 new는 아직 "잠정" 문장이다. 새 수치를 만들어 넣지 않는다.
- 본문 행은 환경분석·현황 장 중 사건으로 **바로 다시 쓸 수 있는 절**만 5~10개 고른다. 원문 요지(old)는 원문 page를 함께 적는다.
- 잠정 판정의 grade는 항상 C. 사건 출처의 등급은 evidence에 그대로 옮긴다.
