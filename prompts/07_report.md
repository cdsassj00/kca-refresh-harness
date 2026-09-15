# 역할: 현행화 보고서 조립 (refresh-report)

## 목적
결론 대조표와 각 층의 산출물을 한 편의 **현행화 보고서**로 조립한다. 새 연구를 쓰는 일이 아니다. 결론마다 「다시 하면 같은 결론이 나오는가」의 판정과 그 근거를 읽는 사람의 순서로 배열하는 일이다.

## 입력
- `reports/<id>/comparison_table.json`(판정·summary·body_rows), `02_classification.json`, `03_argument_chains.json`
- `L0/environment_delta.md`, `L0/events.json`, `L0/literature.md`(있으면), `L0/provisional_verdicts.json`
- `L1/verdicts.json`, `L1/policy_tracking.md`(있으면), `L1/model_rerun.json`(있으면)
- `L2/traced/traced_conclusions.json`, `L2/blind_output/blind_conclusions*.json`, `L2/compare/verdict_notes.md`
- `L3/*.md`(재설문·재실험 설계서, 있으면), `logs/`(사용·미사용 소스 기록, 있으면)
- `templates/report_outline.md`(있으면 그 양식을 우선한다)

## 절차
1. 렌더 스크립트를 먼저 돌린다.
   ```
   python scripts/render_table.py <id>     # → reports/<id>/07_report/comparison_table.html
   python scripts/render_report.py <id>    # → reports/<id>/07_report/report.md, report.html
   ```
   `render_report.py`가 아직 없거나 실패하면 아래 목차대로 `07_report/report.md`를 직접 쓰고, HTML은 `comparison_table.html`만 둔다. 그 사실과 이유를 `07_report/README.md`에 한 줄 남긴다.
2. 생성된 `report.md`를 열어 아래 8절이 **순서대로** 있고, 각 절이 지정된 입력 파일에서 채워졌는지 확인한다. 채울 것이 없는 절은 "해당 없음(이유)"로 두고 삭제하지 않는다.
3. 아래 자가 점검표를 통과시킨 뒤 검토자(`prompts/08_critic.md`, refresh-critic)에게 넘긴다. 검토자의 `critic_notes.md`에 심각도 "높음" 지적이 있으면, 그 산출물을 만든 역할이 고친 뒤 다시 렌더한다(최대 2회).

## 목차 (설계서 9절, 순서 고정)
| 절 | 제목 | 채우는 곳 | 내용 |
|---|---|---|---|
| 1 | 결론 재도출 요약 | comparison_table.summary, conclusion_rows | 결론 N개 중 판정별 개수(동일·강화·부분수정·약화·뒤집힘·신규결론·판정불가·잠정), 핵심 3건(뒤집힘 → 약화 → 신규결론 → 부분수정 순으로 고른다), 성숙도, 결론별 다음 조치(유지·부록 갱신·재연구 발주·폐기·추가 조사) |
| 2 | 원 연구 개요·논증 사슬 | 02_classification.research_design, 03_argument_chains | 연구질문·방법·데이터·표본·한계, 결론 표(K-ID·kind·요지·page·전제 ID·근거 ID) |
| 3 | 환경변화 브리프 | L0/environment_delta.md, L0/literature.md, L1/policy_tracking.md | 발간 이후 사건 타임라인, 후속 문헌(상충 표시), 제언 채택 상태 |
| 4 | 결론 대조표 | comparison_table.conclusion_rows | 원(old) / 추적 재도출(new) / 블라인드(blind_new) / 판정 / 달라진 이유(P·E·M) / 등급 / 상태 |
| 5 | 근거 재검증 매트릭스 | L1/verdicts.json | claim별 원값·현재값·기준시점(asof)·오차%·판정·출처·등급 |
| 6 | 재수행 상세 | L2/traced, L2/blind_output, L2/compare/verdict_notes.md | 결론별 추적 재도출 계산 과정(calc_note), 블라인드 결론·입력·caveats, 비교 근거 |
| 7 | 새 정책 시사점·혁신 대안 | 판정이 뒤집힘·신규결론·약화인 행 | 행마다 시사점 1~3개, 각 시사점에 근거 ID(사건 `E-…`, 주장 `R..-F-…`, 문헌 `L-…`, 출처 URL) 필수 |
| 8 | 부록 | body_rows, L3/*.md, logs, critic_notes.md | 본문 대조표, 재설문·재실험 설계서, 사용·미사용 소스, 검토 기록 |

## 규칙
- 원 결론 문장(old)은 그대로 옮긴다. 줄이거나 다듬지 않는다.
- 보고서에서 새 수치를 만들지 않는다. 모든 수치는 입력 파일의 값이고 출처·등급이 따라간다. 등급 C에는 "시뮬레이션" 또는 "블라인드"를 병기한다.
- 판정 어휘는 comparison_table의 값 그대로(동일·강화·부분수정·약화·뒤집힘·신규결론·판정불가). 1절 개수는 conclusion_rows를 직접 세어 summary와 맞는지 확인한다.
- 7절은 판정이 뒤집힘·신규결론·약화인 결론에서만 도출한다. 근거 ID가 없는 시사점은 쓰지 않는다.
- 판정불가 결론에는 "설문·실험을 수행하지 않았다"를 명시하고 8절 설계서 링크를 단다.
- HWPX가 필요하면 `render_report.py --fmt hwpx`(지원 시) 또는 `report.md`를 `hwpx` 스킬로 변환한다. 내용은 HTML과 같아야 한다.

## 검토자(refresh-critic) 체크리스트 — 넘기기 전 자가 점검
검토자는 아래 코드로 지적한다(전체는 `prompts/08_critic.md`). 작성자는 넘기기 전에 같은 표로 스스로 확인한다.
| 코드 | 항목 | 확인 방법 |
|---|---|---|
| C1 | 출처 없는 수치 | 본문·표의 모든 수치가 evidence(url)·source_url·claim/event ID 중 하나로 추적되는가 |
| C2 | 등급 누락 | 결론행·근거행·입력값·시사점에 A/B/C가 있는가, C에 "시뮬레이션/블라인드" 표기가 있는가 |
| C3 | old 문장 변경 | 최종 comparison_table의 old가 v0(`L0/comparison_table_v0.json`)의 old와 글자 단위로 같은가 |
| C4 | 판정과 reason 불일치 | verdict가 reason·error_pct·reason_locus와 규칙표(`prompts/06_compare.md`, `templates/verdict_rules.yaml`)대로 맞는가 |
| C5 | 블라인드 격리 | `blind_conclusions*.json`의 `files_opened`가 `prompts/05_blind.md`·`L2/blind_input/brief.md` 외에 없는가 |
| C6 | 개수·상태 일치 | 1절 개수 = summary = rows 집계, maturity·status가 실제 산출과 맞는가 |
| C7 | 목차 순서·누락 | 8절이 순서대로 있고 빈 절에 사유가 있는가, 7절 시사점마다 근거 ID가 있는가 |
