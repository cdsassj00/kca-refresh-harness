# 역할: 결론·논증 사슬 추출 (refresh-chains)

## 목적
보고서 원문에서 검증 가능한 **결론 세트**를 뽑고, 각 결론이 어떤 **전제(P)** 와 **근거(E)** 위에 어떤 **방법(M)** 으로 서 있는지 사슬을 복원한다. 이 산출물이 이후 모든 판정의 단위가 된다.

## 입력
- `reports/<id>/00_source/<id>.md` (페이지 표시 `<!-- page N -->` 포함)
- `reports/<id>/01_meta.json`

## 출력 (모두 UTF-8 JSON, ensure_ascii=False)
1. `reports/<id>/02_classification.json`
```json
{"report_id":"R01","domains":["spectrum","network_5g6g"],
 "type_mix":{"F":0.45,"M":0.30,"P":0.15,"B":0.10},
 "research_design":{"rq":"…","methods":["…"],"data":["…"],"sample":"…","limits":["…"]}}
```
2. `reports/<id>/03_argument_chains.json`
```json
{"report_id":"R01",
 "conclusions":[{"conclusion_id":"R01-K-Fc-01","kind":"Fc","statement":"원문 요지(수치 포함)","page":99,
   "method":"방법 요약","premises":["P-01"],"evidence_refs":["R01-F-001"],"types":["F"],"rerun_grade":"R1"}],
 "premises":[{"premise_id":"P-01","statement":"…","section":"제7장 1)","page":94,"indicator":"레벨5 스마트공장 수"}],
 "claims":[{"claim_id":"R01-F-001","conclusion_id":"R01-K-Fc-01","type":"F","page":99,
   "statement":"…","original_value":{"metric":"…","year":2027,"value":123,"unit":"개"},
   "assumptions":["…"],"verify_method":"backtest","data_sources_hint":["…"]}],
 "edges":[{"from":"P-01","to":"R01-K-Fc-01","relation":"premise_of","confidence":0.9}]}
```

## 규칙
- kind: RQ(연구질문) / F(핵심 발견) / Fc(수치 전망) / R(정책·사업 제언).
- types: F 전망·예측 / M 경제성·계량 / S 실태조사·설문 / P 정책·제도 / T 기술·표준·실험 / B 사례·동향 / G 기관 전략.
- rerun_grade: R1 공개자료·재계산으로 즉시 재수행 / R2 대체 데이터 / R3 설문·실험·실측 필요.
- verify_method: backtest / model_rerun / survey_map / policy_track / standard_track / case_refresh / kpi_track.
- 결론은 **8~12개**만. 수치 전망(연도·값·단위가 있는 것)과 정책·사업 제언을 우선하고, 근거가 원문 어디에 있는지 page를 반드시 적는다.
- statement는 원문 표현을 살려 쓰되 수치·연도·단위를 빠뜨리지 않는다. 원문에 없는 수치를 만들지 않는다.
- 전제는 "환경분석 장(현황·동향·정책)"에서 가져온 사실·가정만. 근거는 표·수치·조사·모형 파라미터.
- 확신이 낮은 간선은 confidence를 0.5 이하로 적는다.
- **간선의 `relation` 은 아래 어휘만 쓴다**(`templates/schemas/chain.schema.json` 과 같은 목록이며, 벗어나면 검사에서 거부된다).

| relation | 뜻 | from → to |
|---|---|---|
| `premise_of` | 전제가 결론을 떠받친다 | 전제 → 결론 |
| `evidence_for` | 근거가 결론을 뒷받침한다 | 근거 → 결론 |
| `input_to` | 값이 다른 계산·근거의 입력이 된다 | 근거 → 근거 |
| `answers` | 결론이 연구질문에 답한다 | 결론 → RQ |
| `baseline_of` | 기준선(출발 수치)이 전망의 바탕이 된다 | 근거 → 전망 결론 |
| `motivates` | 배경·문제의식이 연구질문을 낳는다 | 전제 → RQ |
| `supports` | 보조적으로 뒷받침한다(위에 안 맞을 때) | 무엇이든 |
| `cites` | 원문이 외부 문헌을 인용한다 | 결론·근거 → 문헌 |

`evidence_of` 는 `evidence_for` 의 옛 이름이다. 호환을 위해 통과시키지만 새로 쓰지 않는다.
