# KCA 연구보고서 결론 재도출·현행화 하네스

## 목적
옛 연구보고서의 결론 하나하나에 대해 「지금 같은 연구를 다시 하면 같은 결론이 나오는가」를 판정한다.
자료 최신화는 입력이고, **결론별 판정과 다음 조치**가 산출물이다. 새 보고서를 대신 써 주는 도구가 아니다.
설계: `docs/superpowers/specs/2026-09-15-kca-refresh-harness-design.md` / 쉬운 설명: `docs/하네스_구조_쉬운설명.md`

## 3단계 (파이프라인)
1. **바뀐 것 찾기 (L0)** 발간 이후 사건을 찾아 전제를 갱신하고, 제언 채택 여부를 추적하고, 결론별 잠정 판정을 낸다. 어떤 보고서든 여기까지는 바로 된다.
2. **숫자 다시 맞춰보기 (L1)** 결론을 떠받치던 수치를 실적·최신 조사·재계산으로 갱신한다.
3. **결론 다시 내보기 (L2)** 원 방법에 오늘 값을 넣어 추적 재도출하고, 원문을 보지 않은 에이전트가 블라인드 재수행한다. 셋을 비교해 판정(동일·강화·부분수정·약화·뒤집힘·신규결론·판정불가)과 다음 조치(유지·부록 갱신·재연구 발주·폐기·추가 조사)를 붙인다.

## 규칙
- 산출물·로그·주석은 한국어. 코드 식별자는 영어.
- 근거 없는 수치 금지. 모든 수치·판정에 출처 URL, 조회일, 증거 등급(A 1차·공식 / B 2차 / C 추정·시뮬레이션·블라인드 결론)을 붙인다.
- 외부 근거 수집은 `python scripts/evidence.py`(캐시·등급·기록 일관성)와 WebSearch/WebFetch로 한다. 결과는 `kb/evidence/`에 남긴다.
- kb 선독후기: 조사 전에 `kb/events/<domain>/`을 읽고, 새 사건은 같은 형식으로 기록한다.
- 작성자와 검토자를 분리한다. 대조표·보고서는 `refresh-critic` 검토를 통과해야 완료다.
- 블라인드 재수행 에이전트에게 원문 경로를 주지 않는다. 입력은 `reports/<id>/L2/blind_input/brief.md`뿐이며, 산출물의 `files_opened`로 격리를 확인한다.
- 설문·실험은 수행하지 않는다. R3 결론은 "판정 불가"로 두고 설계서를 붙인다. 합성 시뮬레이션은 옵션이며 C등급과 "시뮬레이션" 표기가 필수다.
- 원 결론 문장(old)은 절대 고치지 않는다.
- 키는 `.env`에만. 키 값을 출력·기록하지 않는다.

## 경로
- `prompts/` 단계별 역할 지시서 원본(도구 중립 마크다운). `.claude/skills`·`.claude/agents`·`AGENTS.md`는 이것을 감싼다.
- `reports/<id>/` 보고서 서랍: `00_source/`, `01_meta.json`, `02_classification.json`, `03_argument_chains.json`, `L0/`, `L1/`, `L2/`, `comparison_table.json`, `07_report/`, `logs/`
- `samples/pdf/` 공개 샘플 보고서 7편 · `registry.csv` 현황판 · `kb/` 지식베이스(사건·근거·도메인 프로파일) · `templates/` 분류체계·판정 규칙·스키마·양식 · `scripts/` 계산기·검사기 · `docs/` 설명서

## 실행
- 접수: `python scripts/intake.py R01 samples/pdf/<파일>.pdf`
- 전체: `/refresh-run R01` (Claude Code) — 단계별 재개 가능
- 소스 상태: `python scripts/evidence.py doctor` · 논문 검색: `python scripts/evidence.py papers --q "..." --since 2023-01-01`
- 검증: `python scripts/validate.py <file> --schema <name>` · 렌더: `python scripts/render_table.py R01`, `python scripts/render_report.py R01`
- 테스트: `python -m pytest`
