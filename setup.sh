#!/usr/bin/env bash
# macOS / Linux 용 설정 스크립트. Windows는 setup.bat
set -e
cd "$(dirname "$0")"
echo "=== KCA 연구보고서 현행화 하네스 설정 ==="
command -v python3 >/dev/null || { echo "[오류] python3(3.11 이상)을 설치하세요"; exit 1; }
python3 --version
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo ".env 파일을 만들었습니다. API 키는 .env를 열어 입력하세요 (선택)."; }
if command -v claude >/dev/null; then echo "Claude Code $(claude --version)"; else echo "[안내] Claude Code CLI가 없습니다: npm install -g @anthropic-ai/claude-code 후 claude 실행해 로그인"; fi
echo; echo "=== 소스 상태 ==="; python scripts/evidence.py doctor --no-ping
echo; echo "완료. 다음: Claude Code로 이 폴더를 열고 /refresh-run R01"
