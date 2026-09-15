@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title KCA 연구보고서 현행화 - 독립 프로그램
echo === KCA 연구보고서 현행화 독립 프로그램 ===
echo Claude Code 는 필요 없습니다. OpenRouter 키 하나면 됩니다.
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [오류] Python이 없습니다. https://www.python.org/downloads/ 에서 3.11 이상을 설치하고
  echo        설치 화면의 "Add python.exe to PATH" 를 체크한 뒤 다시 실행하세요.
  pause
  exit /b 1
)
for /f "tokens=2" %%v in ('python --version') do echo Python %%v

if not exist .venv (
  echo 가상환경 생성 중... ^(처음 한 번, 1~2분^)
  python -m venv .venv
  if errorlevel 1 (
    echo [오류] 가상환경 생성 실패. Python 설치를 확인하세요.
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
echo 패키지 설치·확인 중...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [오류] 패키지 설치 실패. 인터넷 연결^(사내 프록시^)을 확인하세요.
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo .env 파일을 만들었습니다. OpenRouter 키는 브라우저의 [설정] 화면에서 입력하면 됩니다.
)

echo.
echo 서버를 시작합니다: http://127.0.0.1:8765
echo 브라우저가 3초 뒤 자동으로 열립니다. 끝내려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo.
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8765"
python -m uvicorn server.main:app --host 127.0.0.1 --port 8765
if errorlevel 1 (
  echo.
  echo [오류] 서버가 종료되었습니다. 위 메시지를 확인하세요.
  echo        - "address already in use" 이면 포트 8765 를 쓰는 다른 프로그램^(이미 떠 있는 이 창^)을 닫고 다시 실행
  echo        - "No module named" 이면 이 창을 닫고 run_app.bat 를 다시 실행 ^(패키지 재설치^)
  echo        자세한 해결법: SETUP.md 의 "문제 해결"
  pause
  exit /b 1
)
