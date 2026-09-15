---
name: refresh-report
description: 보고서 조립과 검토만 실행. 대조표·보고서를 HTML·Markdown(옵션 HWPX)으로 렌더하고 설계서 9절 목차로 점검한 뒤 refresh-critic 검토를 통과시킨다. "R01 보고서 만들어줘", "대조표 렌더", "검토 돌려줘" 요청에 사용.
argument-hint: <report_id> [--skip-critic] [--hwpx]
---

# refresh-report — 산출과 검토

전체 절차와 서브에이전트 호출 방식은 `.claude/skills/refresh-run/SKILL.md`의 **3절 "report"·"critic", 5절 "마무리"** 를 따른다. 규칙 원본은 `prompts/07_report.md`(조립)와 `prompts/08_critic.md`(검토)다.

## 전제 확인
`comparison_table.json`이 있어야 한다(v0라도 됨 — 그 경우 보고서 성숙도는 L0로 표기). `03_argument_chains.json`, `02_classification.json`, `L0/environment_delta.md`도 필요하다.

## 순서
1. 총괄이 실행: `python scripts/render_table.py <id>` → `07_report/comparison_table.html`; `python scripts/render_report.py <id>`(있으면) → `07_report/report.md`, `report.html`. `--hwpx` 또는 run_config `output`에 hwpx가 있으면 07의 HWPX 안내를 따른다.
2. **조립·점검**(general-purpose): "`prompts/07_report.md`를 읽고 따르라. `<id>`의 report.md·report.html을 목차 8절 순서로 점검·보완하고 자가 점검표(C1~C7)를 통과시켜라. `render_report.py`가 없어 직접 썼다면 `07_report/README.md`에 한 줄 남겨라."
3. **검토**(refresh-critic, `--skip-critic`이 없으면): "`prompts/08_critic.md`를 읽고 따르라. 대상 `<id>`. 출력 `07_report/critic_notes.md` 하나."
4. FAIL이면 지적의 담당 역할별로 재작업을 시키고(원본 프롬프트를 다시 읽게 함) 영향받는 뒷단계를 다시 돌린 뒤 critic 재호출. 최대 2회. 총괄은 지적을 직접 고치지 않는다.
5. PASS면 `scripts.registry.set_maturity(path, "<id>", "<레벨>")`(레벨은 refresh-run 5절 규칙).

## 끝나면
`07_report/` 파일 목록, critic 결과(높음·중간·낮음 개수), 남은 지적을 보고한다. 보고서 첫 장(1절 결론 재도출 요약)을 그대로 붙여 보여준다.
