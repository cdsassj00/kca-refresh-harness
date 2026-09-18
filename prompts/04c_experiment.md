# 역할: 재실험 계획 (experiment-planner, Layer 1 → Layer 3)

## 목적
기술·표준·실험형(**T**) 결론에 대해, 발간 이후의 **표준·규격 변화**를 먼저 추적한다. 계산과 문헌만으로 결론의 성립 여부를 말할 수 있으면 거기서 판정하고, 실측·실험이 있어야만 말할 수 있으면 **재실험 계획서**를 써서 "지금은 판정 불가, 다시 재려면 이렇게 하라"를 남긴다. 실험은 **수행하지 않는다**.

## 입력
- `reports/<id>/03_argument_chains.json` 의 결론 중 `types` 에 `T` 가 있거나, claim 의 `verify_method` 가 `standard_track` 인 것
- `reports/<id>/00_source/<id>.md` 의 실험 조건·측정 방법·기준 값 page — `read_report_file` 로 필요한 부분만 읽는다
- `reports/<id>/L0/events.json`, `reports/<id>/L0/provisional_verdicts.json`
- `templates/experiment_plan.md` (계획서 양식) — `read_core_file` 로 읽는다
- 웹 검색·원문 확인(규격 원문 우선)

## 절차
1. **표준·규격 추적.** 결론이 기대고 있는 규격의 발간 이후 개정을 확인한다. 후보: 3GPP 릴리즈·TS/TR(3gpp.org), ITU-R/ITU-T 권고(itu.int), IEEE 표준, O-RAN Alliance 규격, 국립전파연구원 고시·기술기준(rra.go.kr), 국가표준 KS(e-ks.kr), 과기정통부 고시. **버전 번호와 발효일**을 원문에서 확인한다.
2. **계산·문헌으로 판정 가능**하면 `L1/verdicts.json` 에 판정 항목을 낸다(아래 출력 2). 규격이 바뀌었어도 공개된 규격값·시험 보고서로 결론의 수치를 확인할 수 있으면 여기서 끝낸다.
3. **실측·실험이 필요**하면 그 결론은 판정을 내리지 않고 재실험 계획서를 쓴다(아래 출력 3). 해당 결론의 판정은 **"판정불가"**, 다음 조치는 **"추가 조사(계획서)"** 로 둔다.

## 출력
1. `reports/<id>/L3/experiment_index.json` — 배열(이 단계의 결과 목록)
```json
{"conclusion_id":"R01-K-T-01","decision":"대체가능",
 "substitute_survey":{"name":"3GPP TS 38.104 v18.6.0 (2024-06)","url":"https://www.3gpp.org/…","year":2024},
 "design_file":null}
```
```json
{"conclusion_id":"R01-K-T-02","decision":"설계서필요",
 "substitute_survey":null,"design_file":"L3/experiment_plan_R01-K-T-02.md"}
```
- `decision` 은 `"대체가능"`(표준·문헌 추적만으로 판정함) 또는 `"설계서필요"`(재실험 필요) 둘 중 하나.
- `substitute_survey` 에는 판정 근거가 된 규격·문헌의 이름·URL·연도를 넣는다(대체 가능할 때만). 나머지는 `null`.

2. (판정한 결론이 있을 때) `reports/<id>/L1/verdicts.json` — 배열. 항목 형식은 `prompts/04_forecast_verify.md` 의 verdicts 와 같고, `"verify_method":"standard_track"` 을 넣는다. `current_value.value` 에는 최신 규격 버전·수치를, `note` 에는 문서명·발효일을 적는다. **이 단계가 새로 만든 항목만** 돌려주면 러너가 `claim_id` 기준으로 기존 파일과 병합한다.

3. (계획서가 필요한 결론마다) 최종 JSON 의 **`files` 키**로 개별 계획서를 낸다. `files` 는 `{"경로": "파일 내용"}` 맵이고, 경로는 `reports/<id>/` 안의 상대경로여야 한다(`..`·절대경로는 거부된다).
```json
{"L3/experiment_index.json": [...],
 "files": {"L3/experiment_plan_R01-K-T-02.md": "# 재실험 계획서 …(마크다운 전문)"}}
```
- 파일 이름은 `L3/experiment_plan_<K-ID>.md` 고정. `<K-ID>` 는 결론 ID 그대로(예: `R01-K-T-02`).
- 내용은 `templates/experiment_plan.md` 의 절 구성(머리표 → 1. 목적 → 2. 가설 → 3. 변수 → 4. 장비·환경 → 5. 절차 → 6. 판정 기준 → 7. 표준·규격 변경 반영 → 8. 일정·비용 → 9. 안전·규제 → 10. 합성 시뮬레이션)을 **그대로** 따르고, 표의 빈칸을 채운다. 채울 수 없는 칸은 "확인 불가(사유)"로 적고 비워 두지 않는다.
- 머리표의 "현재 판정 · 사유"는 `판정불가 · 실측 없이는 확인 불가(찾은 범위: …)`, 다음 조치는 `추가 조사(계획서)` 로 적는다.
- 6절 판정 기준의 수치 경계는 `templates/verdict_rules.yaml` 을 따른다(예측 오차 ±10% 동일, 10~30% 부분수정, 부호 반전 뒤집힘).

## 규칙
- **해당 유형(T) 결론이 하나도 없으면** `L3/experiment_index.json` 은 **빈 배열 `[]`**, `files` 는 **빈 객체 `{}`** 로 내고 **정상 종료**한다. 다른 유형의 결론을 끌어와 억지로 채우지 않는다.
- **실험을 수행하지 않는다.** 측정값·시험 성적서를 만들지 않으며 "측정 결과" 같은 표현을 새로 쓰지 않는다. 원 실험의 수치와 공개된 규격값만 출처와 함께 인용한다.
- 규격은 발행기관 원문 페이지를 열어 **버전·발효일**을 확인하고 A등급으로 적는다. 요약 기사·블로그만 있으면 B등급이며 2개 이상 교차확인한다. 버전을 확인하지 못하면 `검증불가` 로 두고 어디까지 찾았는지 적는다.
- 원 실험 조건(주파수 대역·출력·장비·환경)과 수치는 원문 page 와 함께 인용하고 고치지 않는다. 달라진 조건은 7절 표에 원 기준과 현재 버전을 나란히 적는다.
- 합성 시뮬레이션은 `run_config.options.synthetic_sim` 이 켜졌다고 지시받았을 때만 10절을 채우고, 모든 수치에 등급 `C` 와 "시뮬레이션"을 병기한다. 지시가 없으면 10절은 "사용 여부: 끔"으로 둔다. 시뮬레이션 결과는 판정에 쓰지 않는다.
- 모든 수치·판정에 출처 URL·조회일·등급(A 1차·공식 / B 2차 / C 추정)을 붙인다.
