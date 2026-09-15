@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo === KCA 연구보고서 현행화 하네스 설정 ===

where python >nul 2>&1
if errorlevel 1 (
  echo [오류] Python이 없습니다. https://www.python.org/downloads/ 에서 3.11 이상을 설치하고 PATH 추가를 체크하세요.
  pause
  exit /b 1
)
for /f "tokens=2" %%v in ('python --version') do set PYVER=%%v
echo Python %PYVER%

if not exist .venv (
  echo 가상환경 생성 중...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
echo 패키지 설치 중...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [오류] 패키지 설치 실패. 인터넷 연결을 확인하세요.
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo .env 파일을 만들었습니다. API 키는 메모장으로 .env를 열어 입력하세요 ^(선택^).
)

where claude >nul 2>&1
if errorlevel 1 (
  echo [안내] Claude Code CLI가 없습니다. Node.js 설치 후: npm install -g @anthropic-ai/claude-code  그리고 claude 실행해 로그인.
) else (
  for /f "delims=" %%c in ('claude --version') do echo Claude Code %%c
)

echo.
echo === 소스 상태 ===
python scripts\evidence.py doctor --no-ping
echo.
echo 완료. 다음 단계: Claude Code로 이 폴더를 열고  /refresh-run R01  을 입력하세요. 자세한 것은 SETUP.md
pause
