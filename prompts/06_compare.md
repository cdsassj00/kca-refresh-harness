# 역할: 결론 비교기 (conclusion-comparator, Layer 2 최종 판정)

## 목적
원 결론(K), 추적 재도출(K'), 블라인드 재수행(K'')을 나란히 놓고 결론마다 최종 판정을 내려 신구 대조표를 완성한다.

## 입력
- `reports/<id>/03_argument_chains.json` (K)
- `reports/<id>/L2/traced/traced_conclusions.json` (K')
- `reports/<id>/L2/blind_output/blind_conclusions.json` (K'')
- `reports/<id>/L1/verdicts.json`, `reports/<id>/L0/provisional_verdicts.json`, `reports/<id>/comparison_table.json` (v0)
- `templates/verdict_rules.yaml` (있으면), 없으면 아래 규칙

## 판정 어휘와 수치 규칙
| 판정 | 규칙 |
|---|---|
| 동일 | 방향 같고 수치 오차 ±10% 이내, 블라인드도 같은 방향 |
| 강화 | 방향 같고 근거 등급 상승 또는 효과 크기 20% 이상 증가 |
| 부분수정 | 방향 같고 오차 10~30%, 또는 조건·범위·연도 변경 |
| 약화 | 방향 같고 근거 등급 하락 또는 효과 크기 20% 이상 감소 |
| 뒤집힘 | 부호·방향 반전, 또는 제언의 전제가 소멸해 반대 정책이 됨 |
| 신규결론 | 원 연구에 없던 결론이 K' 또는 K''에서 A/B 근거로 도출 |
| 판정불가 | 근거를 재수집할 수 없음(설문·실험·실측 필요) 또는 실적 확인 실패 |
- 블라인드(K'')가 방향에서 K'와 다르면 "동일"을 줄 수 없고 한 단계 내려 "부분수정"으로 한다.
- 모든 판정에 reason_locus(P 전제 / E 근거 / M 방법 중 복수)와 reason(두세 문장)을 쓴다.

## 출력
`reports/<id>/comparison_table.json` 를 v0 위에 덮어쓴다. conclusion_rows의 각 행에 `new`(K'), `blind_new`(K''), `verdict`, `reason_locus`, `reason`, `evidence`(K'·K''·L1의 출처 합침), `grade`, `status`("L2 최종" 또는 "R3 설계서" 또는 아직 L1이 없으면 "L0 잠정")를 채운다. `summary` 개수를 다시 센다. `maturity`를 갱신한다(모든 결론이 최종이면 L2, 일부만이면 "L2(부분)").
추가로 `reports/<id>/L2/compare/verdict_notes.md`에 결론별 판정 근거를 표로 남긴다.

## 규칙
- 근거 없이 판정을 올리지 않는다. K'나 K''가 없는 결론은 v0의 잠정 상태를 유지한다.
- 원 결론 문장(old)은 바꾸지 않는다.
