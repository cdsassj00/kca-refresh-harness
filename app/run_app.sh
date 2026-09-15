#!/usr/bin/env bash
# macOS / Linux 용 실행 스크립트. Windows 는 run_app.bat (Git Bash 에서는 이 파일도 동작한다)
# 하는 일: 가상환경 생성 → 패키지 설치 → .env 준비 → 서버 실행(127.0.0.1:8765) → 브라우저 열기
set -e
cd "$(dirname "$0")"
echo "=== KCA 연구보고서 현행화 독립 프로그램 ==="
echo "Claude Code 는 필요 없습니다. OpenRouter 키 하나면 됩니다."
echo

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || { echo "[오류] Python 3.11 이상을 설치하세요: https://www.python.org/downloads/"; exit 1; }
"$PY" --version

[ -d .venv ] || { echo "가상환경 생성 중... (처음 한 번)"; "$PY" -m venv .venv; }
# shellcheck disable=SC1091
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; else source .venv/Scripts/activate; fi
python -m pip install -q --upgrade pip
echo "패키지 설치·확인 중..."
python -m pip install -q -r requirements.txt

[ -f .env ] || { cp .env.example .env; echo ".env 파일을 만들었습니다. OpenRouter 키는 브라우저 [설정] 화면에서 입력하세요."; }

URL="http://127.0.0.1:8765"
echo
echo "서버를 시작합니다: $URL   (브라우저가 3초 뒤 열립니다. 끝내려면 Ctrl+C)"
echo
(
  sleep 3
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
  elif command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v start >/dev/null 2>&1; then start "$URL"
  fi
) &
python -m uvicorn server.main:app --host 127.0.0.1 --port 8765 || {
  echo
  echo "[오류] 서버가 종료되었습니다. 포트 8765 가 사용 중이면 기존 프로세스를 끄고 다시 실행하세요. 자세한 해결법: SETUP.md"
  exit 1
}
