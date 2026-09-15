---
name: refresh-l0
description: Layer 0만 실행. 발간 이후 사건 조사·후속 문헌 스캔·영향 전파·결론별 잠정 판정·신구 대조표 v0까지. "R02 L0만", "바뀐 것만 찾아줘", "잠정 판정" 요청에 사용. 접수·분류·논증 사슬이 없으면 먼저 만든다.
argument-hint: <report_id> [--redo]
---

# refresh-l0 — 바뀐 것 찾기 (Layer 0)

전체 절차와 서브에이전트 호출 방식은 `.claude/skills/refresh-run/SKILL.md`의 **3절 "chains ∥ l0 사건 조사"·"l0 영향 전파"** 를 따른다. 이 문서는 L0만 돌릴 때의 전제와 순서다.

## 전제 확인
`reports/<id>/`에 `00_source/<id>.md`, `01_meta.json`, `02_classification.json`, `03_argument_chains.json`이 있어야 한다. 없는 것은 refresh-run의 intake·classify·chains 절대로 먼저 만든다(PDF 경로가 필요하면 사용자에게 묻는다).

## 순서
1. `run_config.json`이 있으면 `period`·`l0_rewrite_scope`만 읽는다(refresh-run 1절).
2. kb 선독: 총괄이 `kb/events/<domain>/`의 파일 목록을 delta-researcher 프롬프트에 붙여 준다(중복 조사 방지).
3. **delta-researcher ∥ literature-scanner** 동시 실행 → `L0/events.json`, `L0/environment_delta.md`, `L0/literature.json`, `L0/literature.md`.
4. **impact-propagator** → `L0/provisional_verdicts.json`, `comparison_table.json`(v0, maturity `L0`, 모든 행 status `L0 잠정`).
5. 총괄: `comparison_table.json` → `L0/comparison_table_v0.json` 복사(없을 때만), `python scripts/render_table.py <id>` → `07_report/comparison_table.html`을 `07_report/comparison_table_v0_L0.html`로도 복사.
6. 새 사건이 `kb/events/<domain>/`에 같은 형식으로 남았는지 확인한다(없으면 delta-researcher에게 추가 지시).
7. `scripts.registry.set_maturity(path, "<id>", "L0")` 호출(스크립트 있을 때).

## 재실행
`--redo`가 있으면 3~5를 산출물이 있어도 다시 한다. 이때 `comparison_table.json`의 `old` 열과 `L0/comparison_table_v0.json`은 바꾸지 않는다(refresh-run 2절 재개 규칙).

## 끝나면
사용자에게 사건 수·문헌 수·결론별 잠정 판정(keep_likelihood 분포)·대조표 HTML 경로를 보고한다. L1로 가려면 `refresh-verify`, 한 번에 끝까지는 `refresh-run --from l1`.
