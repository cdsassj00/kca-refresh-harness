# 받는 사람이 설정할 것 (체크리스트)

이 저장소를 받은 뒤 아래 순서대로 하면 됩니다. 1~3은 필수, 4는 선택, 5~6은 확인입니다. 소요 15분.

## 1. Python 설치 (필수)
- [ ] Python **3.11 이상** 설치. https://www.python.org/downloads/ 에서 받고 설치 시 "Add python.exe to PATH" 체크.
- [ ] 확인: 명령창에서 `python --version` 이 3.11 이상.

## 2. 패키지와 기본 파일 (필수)
- [ ] 이 폴더에서 `setup.bat` 더블클릭(또는 명령창에서 실행). 가상환경 `.venv`를 만들고 패키지를 설치하고 `.env` 파일을 만들어 줍니다.
- [ ] 끝에 "소스 상태" 표가 나오면 정상입니다.

## 3. Claude Code 설치와 로그인 (필수)
하네스의 AI 부분은 Claude Code가 실행합니다. 이것만은 자동으로 묶어 드릴 수 없습니다.
- [ ] Node.js 18 이상 설치 (https://nodejs.org) → 명령창에서 `npm install -g @anthropic-ai/claude-code`
- [ ] `claude` 실행 후 안내에 따라 로그인 (Claude 구독 계정 또는 기관에서 발급한 API 키)
- [ ] 확인: `claude --version` 이 2.1 이상.
- Claude Code 데스크톱 앱이나 VS Code 확장을 써도 됩니다. 같은 엔진이라 이 폴더의 설정을 그대로 읽습니다.

## 4. API 키 입력 (선택, 있으면 검증이 정확해짐)
- [ ] `.env` 파일을 메모장으로 열어 값 입력. 권장 순서: `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`(뉴스), `KOSIS_API_KEY`(통계), `DATA_GO_KR_API_KEY`(공공데이터·KCI 논문), `LAW_GO_KR_OC`(법령).
- [ ] 발급 방법은 [docs/api_keys_guide.md](docs/api_keys_guide.md). 대부분 무료이고 당일 발급.
- [ ] 확인: `python scripts\evidence.py doctor` 에서 해당 소스가 `OK`.
- 키가 하나도 없어도 됩니다. 키 없는 소스(OpenAlex·Crossref·arXiv·Semantic Scholar·웹 검색)로 1단계 전체와 2단계 일부가 돌아갑니다.
- 키는 `.env`에만 두세요. 이 파일은 git에 올라가지 않습니다. 화면·문서·로그에 키 값을 붙여 넣지 마세요.

## 5. 샘플로 한 번 돌려보기 (확인)
- [ ] Claude Code로 이 폴더를 열고 `/refresh-run R01` 입력. 샘플 R01(5G 시장전망 보고서)은 이미 결과가 들어 있어 단계별로 "건너뜀"이 표시되며 빠르게 끝납니다.
- [ ] 처음부터 돌려 보려면 `reports/R02/`가 비어 있으니 `python scripts\intake.py R02 "samples\pdf\02_[2022.03]_주파수_경매_제도의_사회경제적_후생효과_분석.pdf"` 후 `/refresh-run R02`. 보고서 한 편에 30분~1시간, AI 호출 6~10회가 듭니다.
- [ ] 결과 보기: `reports/R02/07_report/comparison_table.html`(대조표), `report.md`(현행화 보고서), `registry.csv`(현황판).

## 6. 내 부서 보고서 넣기
- [ ] 보고서를 **PDF**로 준비합니다. HWP·HWPX·DOCX는 한글이나 워드에서 "PDF로 저장"으로 변환합니다(직접 입력은 다음 버전).
- [ ] `python scripts\intake.py R08 "C:\경로\보고서.pdf"` → ID는 `R` + 두 자리 숫자로 겹치지 않게.
- [ ] Claude Code에서 `/refresh-run R08`.
- [ ] 원문과 산출물은 `reports/R08/`에 내 PC에만 남습니다. 공유하려면 `07_report/`의 HTML·Markdown만 보내면 됩니다.

## 7. 내부 문서 취급 (확인)
- [ ] 보고서 원문이 AI 서비스(Anthropic)로 전송되는 것에 대해 기관 방침을 확인했습니다. 비공개·대외비 문서는 방침 확인 전에 넣지 마세요.
- [ ] 공용 지식베이스 `kb/events/`에는 공개 사건과 출처만 기록합니다. 내부 정보는 넣지 않습니다.

## Claude Code가 아닌 도구를 쓰는 경우
- Codex·Antigravity·Cursor·Gemini CLI: 이 폴더를 열면 `AGENTS.md`가 절차를 안내합니다. `prompts/00~08`을 순서대로 따르고 산출물을 `reports/<ID>/`의 정해진 자리에 저장하면 같은 계산기·렌더가 동작합니다. 블라인드 단계는 원문을 열지 않은 새 세션에서 하세요.
- ChatGPT 웹만 있는 경우: `AGENTS.md`의 수동 모드. 프롬프트를 단계별로 붙여 넣고 결과를 파일로 저장합니다.

## 문제가 생기면
- `python -m pytest` 로 자체 점검. 모두 통과해야 정상입니다.
- `python scripts\evidence.py doctor` 로 소스 상태 확인.
- 설명서 [docs/설명서_구성과_기술스펙.md](docs/설명서_구성과_기술스펙.md) 의 "자주 묻는 질문".
