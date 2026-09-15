# AGENTS.md — 도구 중립 안내 (Codex · Cursor · Antigravity · Gemini CLI · ChatGPT 웹)

이 폴더는 **KCA 연구보고서 결론 재도출·현행화 하네스**다. 옛 보고서의 결론 하나하나에 대해 「지금 같은 연구를 다시 하면 같은 결론이 나오는가」를 판정한다. 규칙의 원본은 `CLAUDE.md`(사규)와 `prompts/00~08`(단계별 역할 지시서)이며, 어떤 도구를 쓰든 **그 두 가지만 따르면 같은 결과가 나오도록** 만들어져 있다. `.claude/skills`·`.claude/agents`는 Claude Code용 포장일 뿐이므로 다른 도구에서는 읽지 않아도 된다.

## 1. 먼저 읽을 것
1. `CLAUDE.md` — 항상 지켜야 하는 규칙. 요지: 근거 없는 수치 금지(모든 수치에 출처 URL·조회일·등급 A/B/C), 작성자와 검토자 분리, 블라인드 재수행자에게 원문을 주지 않기, 설문·실험을 하지 않기(판정 불가 + 설계서), 원 결론 문장(old) 불변, 키는 `.env`에만.
2. `docs/하네스_구조_쉬운설명.md` — 전체 그림 5분 설명.
3. `prompts/` — 단계마다 하나씩. 각 파일이 입력·출력 경로·JSON 형식·규칙을 다 담고 있다.

## 2. 폴더 구조
```
prompts/            00_intake 01_chains 02_delta 03_impact 04_forecast_verify 05_blind 06_compare 07_report 08_critic
reports/<id>/       보고서 서랍(R01~R07). 산출물은 반드시 여기의 정해진 경로에
  00_source/<id>.md 01_meta.json 02_classification.json 03_argument_chains.json
  L0/  events.json environment_delta.md literature.json provisional_verdicts.json comparison_table_v0.json
  L1/  verdicts.json policy_tracking.md model_rerun.json calc/
  L2/  blind_input/brief.md  blind_output/blind_conclusions.json  traced/traced_conclusions.json  compare/{verdict_notes.md,question_map.json}
  L3/  survey_redesign_<K-ID>.md experiment_plan_<K-ID>.md      (판정불가 결론의 설계서)
  comparison_table.json  07_report/{comparison_table.html,report.md,report.html,critic_notes.md}  logs/  run_config.json
samples/pdf/        공개 샘플 보고서 7편          registry.csv   현황판(보고서별 성숙도 L0~L3)
kb/                 events/<domain>/ 사건, evidence/ 근거, domains/ 도메인 프로파일   templates/  분류체계·판정 규칙·스키마·양식
scripts/            intake.py evidence.py validate.py render_table.py render_report.py registry.py (일부는 작성 중)
docs/               설계서(superpowers/specs), API 키 발급 안내, 설명서
```
완성된 실제 예는 `reports/R01/` 전체다. 형식이 헷갈리면 그 파일들을 연다.

## 3. 절차 요약 — prompts/00~08을 순서대로
| 순서 | 프롬프트 | 하는 일 | 산출(reports/<id>/ 아래) |
|---|---|---|---|
| 0 | `00_intake.md` | `python scripts/intake.py <id> <pdf>` 로 접수, 도메인·유형·연구설계 분류 | `00_source/<id>.md`, `01_meta.json`, `02_classification.json` |
| 1 | `01_chains.md` | 결론 8~12개와 전제·근거·방법 사슬 복원 | `03_argument_chains.json` |
| 2 | `02_delta.md` | 발간 이후 사건 8~15개, 출처·등급 | `L0/events.json`, `L0/environment_delta.md` (+ `kb/events/<domain>/`에도 기록) |
| 3 | `03_impact.md` | 사건→전제→결론 전파, 잠정 판정, 대조표 v0 | `L0/provisional_verdicts.json`, `comparison_table.json` → 복사본 `L0/comparison_table_v0.json` |
| 4 | `04_forecast_verify.md` | 전망 대 실적, 추적 재도출(원 방법 + 오늘 값) | `L1/verdicts.json`, `L2/traced/traced_conclusions.json` |
| 5 | `05_blind.md` | **새 세션**에서 브리프만 보고 독립 결론 | `L2/blind_output/blind_conclusions.json` |
| 6 | `06_compare.md` | 원·추적·블라인드 비교, 최종 판정 7종 | `comparison_table.json`(덮어쓰기), `L2/compare/verdict_notes.md` |
| 7 | `07_report.md` | 렌더 + 9절 목차로 보고서 조립 | `07_report/comparison_table.html`, `report.md`, `report.html` |
| 8 | `08_critic.md` | 읽기 전용 검토, 지적 표 | `07_report/critic_notes.md` (PASS여야 완료) |

- 각 단계는 "그 프롬프트 파일을 읽고 지시대로 수행하라 + 보고서 ID + 입력 파일 경로 + 출력 파일 경로"만 주면 된다. 프롬프트 본문을 복사해 고치지 말고 파일을 그대로 쓴다(단일 원본).
- 산출 파일이 이미 있으면 그 단계는 건너뛰어도 된다(재개). 다시 할 때는 기존 파일을 `.bak.<시각>`으로 옮긴다. `comparison_table.json`의 `old` 열과 `L0/comparison_table_v0.json`은 어떤 경우에도 바꾸지 않는다.
- 병렬 가능: (1과 2)는 동시에, (4와 5)는 동시에. 3은 1·2 뒤, 6은 4·5 뒤.
- 후속 문헌 스캔(L0), 정책 제언 추적·모형 재계산(L1), 재설문·재실험 설계서(L3)는 아직 prompts 원본이 없다. 규칙은 `.claude/agents/{literature-scanner,policy-tracker,model-reconstructor,survey-redesigner,experiment-planner}.md`의 본문에 있으니 그 본문을 지시문으로 쓰면 된다(frontmatter는 무시).
- 옵션은 `reports/<id>/run_config.json`(예시는 설계서 7.3절). 없으면 기본값: L0·L1·L2 모두, 블라인드 1회, 재설문·재실험 설계서는 R3 결론에만, 합성 시뮬레이션 꺼짐.
- 끝나면 `registry.csv`의 해당 행 `maturity`를 L0/L1/L2/L3로 갱신한다(`scripts/registry.py`의 `set_maturity` 또는 손으로).

## 4. 블라인드 단계(05)의 격리 — 어떤 도구든 동일
- 브리프 `L2/blind_input/brief.md`는 총괄(원문을 본 사람)이 쓴다. 담는 것: 연구질문, 방법의 뼈대, 답해야 할 항목, 오늘 날짜. **담지 않는 것**: 원 결론·수치·시나리오 값·판정 어휘·보고서 제목·기관·저자·원문 page. 실제 예 `reports/R01/L2/blind_input/brief.md`.
- 블라인드 수행은 **원문을 연 적이 없는 새 세션(새 채팅·새 에이전트 인스턴스)** 에서 한다. 그 세션에 주는 것은 `prompts/05_blind.md`와 `brief.md` 두 파일과 출력 경로뿐이다. 프로젝트 폴더 전체를 열어 주지 않는다(가능한 도구라면 그 두 파일만 있는 임시 폴더에서 실행).
- 산출물 마지막 원소 `files_opened`에 두 파일 외의 경로가 있으면 그 결과는 버리고 새 세션에서 다시 한다.
- 결론 ID와 질문(Q1…)의 대응표는 브리프에 넣지 말고 `L2/compare/question_map.json`에 둔다.

## 5. 도구별 메모
- **Codex CLI / Antigravity / Cursor / Gemini CLI**: 이 파일을 프로젝트 지시문으로 읽는다. 작업 지시는 "`prompts/NN.md`를 읽고 `<id>`에 대해 수행. 출력은 그 파일에 적힌 경로"로 준다. 서브에이전트·병렬 실행을 지원하면 3절의 병렬 조합대로, 아니면 순서대로 한 번에 한 단계. 스크립트 실행에는 Python 3.11+와 `pip install -r requirements.txt`가 필요하다. API 키는 `.env`에만 넣고 프롬프트에 붙이지 않는다.
- **검토(08)** 는 작성 세션과 다른 세션에서 한다. 검토자는 파일을 고치지 않고 `critic_notes.md`만 쓴다. "높음" 지적이 있으면 해당 단계를 만든 세션(또는 새 세션)이 그 프롬프트를 다시 읽고 고친 뒤 재검토한다.

## 6. ChatGPT 웹 수동 모드
파일 시스템·스크립트 실행이 없는 웹 채팅에서도 같은 절차를 손으로 돌릴 수 있다. 저장은 사용자가 직접 한다.
1. **접수**는 로컬에서 `python scripts/intake.py <id> <pdf>`를 돌린다(웹에서는 불가). 결과 `00_source/<id>.md`를 첨부하거나 붙여넣는다. PDF 텍스트가 길면 장별로 나눠 붙인다.
2. 단계마다 새 메시지에 **① 해당 `prompts/NN.md` 전문 → ② 필요한 입력 파일 내용(표의 입력 열) → ③ "위 지시대로 `<id>`를 수행하고 출력 JSON을 코드블록으로 내라"** 순으로 붙여넣는다. 응답의 JSON·Markdown을 표의 산출 경로에 그대로 저장한다(UTF-8).
3. 저장 위치(반드시 이 경로): `02_classification.json` `03_argument_chains.json` → `reports/<id>/`; 사건·잠정판정 → `reports/<id>/L0/`; 검증 → `reports/<id>/L1/`; 브리프·블라인드·추적·비교 → `reports/<id>/L2/…`; 대조표 → `reports/<id>/comparison_table.json`(v0는 `L0/comparison_table_v0.json`에도 복사); 보고서·검토 → `reports/<id>/07_report/`.
4. **블라인드(05)** 는 반드시 **새 채팅**을 열어 `prompts/05_blind.md`와 `brief.md`만 붙여넣는다. 이전 대화·원문·제목을 언급하지 않는다. 응답 끝의 `files_opened`에는 그 두 파일만 적히도록 한다(웹에서는 실제 파일 접근이 없으므로 "붙여넣은 문서" 기준).
5. **웹 검색이 되는 모델**을 쓰고, 수치마다 URL·조회일·등급을 요구한다. URL이 없는 수치는 저장하지 않는다.
6. 렌더는 로컬에서 `python scripts/render_table.py <id>`, `python scripts/render_report.py <id>`. 스크립트를 못 돌리면 `prompts/07_report.md`의 목차대로 Markdown 보고서를 채팅에서 만들어 `07_report/report.md`로 저장한다.
7. **검토(08)** 도 새 채팅에서 `prompts/08_critic.md` + 검토 대상 파일들을 붙여넣고, 응답을 `07_report/critic_notes.md`로 저장한다. 높음 지적이 0건이 될 때까지 반복한다.
8. 끝나면 `registry.csv`의 `maturity`를 손으로 갱신한다.

## 7. 완료 기준
`comparison_table.json`의 모든 결론행에 판정·reason_locus·evidence·grade·status가 있고, 판정불가 결론에는 `L3/` 설계서가 붙어 있으며, `07_report/critic_notes.md`가 PASS이고, `registry.csv`의 maturity가 갱신된 상태.
