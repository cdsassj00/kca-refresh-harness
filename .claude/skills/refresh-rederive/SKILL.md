---
name: refresh-rederive
description: Layer 2만 실행. 블라인드 브리프 작성 → 원문을 보지 않은 에이전트의 블라인드 재수행 → (추적 재도출이 없으면 보완) → 원·추적·블라인드 비교로 최종 판정 → 판정불가 결론에 재설문·재실험 설계서. "R01 결론 다시 내봐", "블라인드", "최종 판정", "L2" 요청에 사용.
argument-hint: <report_id> [--blind-only|--compare-only] [--repeats N] [--redo]
---

# refresh-rederive — 결론 다시 내보기 (Layer 2)

전체 절차·블라인드 브리프 규칙·격리 검사·서브에이전트 호출 방식은 `.claude/skills/refresh-run/SKILL.md`의 **3절 "l1 ∥ l2 블라인드"의 L2 부분, "l2 비교·설계서", 4절 "블라인드 브리프 작성 규칙"** 을 따른다. 이 문서는 L2만 돌릴 때의 전제와 순서다.

## 전제 확인
- 필수: `03_argument_chains.json`, `L0/provisional_verdicts.json`, `comparison_table.json`(v0 이상), `L0/comparison_table_v0.json`(없으면 지금 복사).
- 권장: `L1/verdicts.json`, `L2/traced/traced_conclusions.json`. 없으면 비교기는 K'가 없는 결론을 잠정 상태로 유지한다(`prompts/06_compare.md`). 추적 재도출까지 원하면 `refresh-verify`를 먼저 돌린다.
- `run_config.json`의 `blind_rerun`(기본 켬, repeats 1)·`survey_redesign`·`experiment_plan`(기본 켬, R3에만)·`synthetic_sim`(기본 꺼짐)을 읽는다. `--repeats`는 파일 값을 덮어쓴다.

## 순서
1. **브리프**: 총괄이 refresh-run 4절 규칙대로 `L2/blind_input/brief.md`와 `L2/compare/question_map.json`을 쓴다. 실제 예 `reports/R01/L2/blind_input/brief.md`. 쓰고 나서 원 수치 검사(4절 마지막 항목)를 반드시 한다.
2. **블라인드**: blind-rerunner를 Agent 도구로 띄운다. 프롬프트에는 `prompts/05_blind.md` 경로와 brief 경로, 출력 경로만. repeats>1이면 별도 에이전트를 추가로 띄우고 `blind_conclusions_run<n>.json`. 끝나면 `files_opened` 격리 검사(위반 시 1회 재실행, 재위반 시 블라인드 없음 처리). `--blind-only`면 여기서 멈춘다.
3. **비교**: conclusion-comparator(`prompts/06_compare.md`)에 입력 목록 + `question_map.json` + 반복 파일을 준다. 출력 `comparison_table.json`(덮어쓰기), `L2/compare/verdict_notes.md`. `--compare-only`면 1~2를 건너뛰고 기존 블라인드 산출물로 비교만 한다.
4. **설계서**(옵션이 켜진 경우, 대상이 있을 때만, 동시에): status `R3 설계서` 또는 verdict `판정불가`인 결론을 types로 나눠 survey-redesigner(S) → `L3/survey_redesign_<K-ID>.md`, experiment-planner(T) → `L3/experiment_plan_<K-ID>.md`. `synthetic_sim`이 꺼져 있으면 시뮬레이션 절을 만들지 말라고 명시한다.
5. 총괄: old 불변 확인(`L0/comparison_table_v0.json`과 대조), summary 재집계 확인, `python scripts/render_table.py <id>`.
6. `scripts.registry.set_maturity(path, "<id>", "L2")` (모든 판정불가·R3에 설계서가 붙었으면 `"L3"`).

## 주의
- 이 세션(총괄)은 원문과 사슬을 읽으므로, 블라인드 결론을 직접 쓰거나 고치지 않는다. 블라인드 산출물의 수정은 오직 새 blind-rerunner 재실행으로만 한다.
- 비교기와 설계서 작성자는 웹을 열지 않는다(비교기)거나 설문·실험을 하지 않는다(설계자). 결과에 새 수치가 생겼으면 출처를 의심하고 critic에 넘긴다.

## 끝나면
판정별 개수, 뒤집힘·약화·신규결론 목록, 블라인드 격리 결과, 설계서 목록을 보고한다. 다음은 `refresh-report`.
