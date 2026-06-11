@echo off
chcp 65001 > nul
title KIS Auto Trader - Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo   KIS Auto Trader - Setup
echo ============================================================
echo.

REM ── [1] Python 3.11+ 확인 ──────────────────────────────────
echo [1/9] Python 확인 중...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [오류] Python이 설치되어 있지 않습니다.
    echo        https://python.org 에서 Python 3.11 이상을 설치하세요.
    echo        설치 시 "Add Python to PATH" 옵션을 반드시 체크하세요.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     Python %PYVER% 확인됨

REM ── [2] venv 생성 ──────────────────────────────────────────
echo.
echo [2/9] 가상환경 생성 중...
if exist "venv\Scripts\python.exe" (
    echo     venv 이미 존재 - 건너뜀
) else (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [오류] 가상환경 생성 실패
        pause
        exit /b 1
    )
    echo     venv 생성 완료
)

REM ── [3] 패키지 설치 ────────────────────────────────────────
echo.
echo [3/9] Python 패키지 설치 중... (시간이 걸릴 수 있습니다)
venv\Scripts\pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [오류] 패키지 설치 실패. requirements.txt를 확인하세요.
    pause
    exit /b 1
)
echo     패키지 설치 완료

REM ── [4] Node.js 확인 ───────────────────────────────────────
echo.
echo [4/9] Node.js 확인 중...
node --version > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [오류] Node.js가 설치되어 있지 않습니다.
    echo        https://nodejs.org 에서 LTS 버전을 설치하세요.
    pause
    exit /b 1
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo     Node.js %NODEVER% 확인됨

REM ── [5] Electron 의존성 설치 ───────────────────────────────
echo.
echo [5/9] Electron 의존성 설치 중... (최초 실행 시 수 분 소요)
if exist "electron\node_modules\electron\dist\electron.exe" (
    echo     Electron 이미 설치됨 - 건너뜀
) else (
    cd electron
    npm install
    if %errorlevel% neq 0 (
        echo [오류] npm install 실패
        cd ..
        pause
        exit /b 1
    )
    cd ..
    echo     Electron 설치 완료
)

REM ── [6] .cache 폴더 생성 ───────────────────────────────────
echo.
echo [6/9] .cache 폴더 생성 중...
if not exist ".cache" mkdir ".cache"
echo     완료

REM ── [7] 환경변수 안내 ──────────────────────────────────────
echo.
echo [7/9] 환경변수 설정 안내
echo.
echo ┌─────────────────────────────────────────────────────────┐
echo │  아래 환경변수를 Windows 시스템 환경변수에 등록하세요.  │
echo │  sysdm.cpl ^> 고급 ^> 환경변수 ^> 시스템 변수 ^> 새로 만들기  │
echo ├─────────────────────────────────────────────────────────┤
echo │  [KIS API - 실전투자]                                   │
echo │    KIS_REAL_APP_KEY                                     │
echo │    KIS_REAL_APP_SECRET                                  │
echo │    KIS_REAL_ACCOUNT      (예: 12345678-01)              │
echo │                                                         │
echo │  [KIS API - 모의투자]                                   │
echo │    KIS_MOCK_APP_KEY                                     │
echo │    KIS_MOCK_APP_SECRET                                  │
echo │    KIS_MOCK_ACCOUNT                                     │
echo │                                                         │
echo │  [텔레그램 선택봇]                                      │
echo │    TELEGRAM_BOT_TOKEN                                   │
echo │    TELEGRAM_CHAT_ID                                     │
echo │                                                         │
echo │  [텔레그램 알람봇]                                      │
echo │    TELEGRAM_ALARM_BOT_TOKEN                             │
echo │    TELEGRAM_ALARM_CHAT_ID                               │
echo │                                                         │
echo │  [AI 점수 - 선택]                                       │
echo │    PERPLEXITY_API_KEY                                   │
echo │    DART_API_KEY                                         │
echo └─────────────────────────────────────────────────────────┘
echo.

REM ── [8] watchdog.bat 생성 ──────────────────────────────────
echo [8/9] watchdog.bat 생성 중...
venv\Scripts\python.exe write_watchdog.py
if %errorlevel% neq 0 (
    echo [경고] watchdog.bat 생성 실패 - 수동으로 write_watchdog.py를 실행하세요.
) else (
    echo     watchdog.bat 생성 완료
)

REM ── [9] 작업 스케줄러 등록 ─────────────────────────────────
echo.
echo [9/9] Windows 작업 스케줄러 등록 중...
schtasks /query /tn "KIS WatchDog" > nul 2>&1
if %errorlevel% == 0 (
    schtasks /delete /tn "KIS WatchDog" /f > nul 2>&1
)
schtasks /create /tn "KIS WatchDog" /tr "\"%~dp0venv\Scripts\pythonw.exe\" \"%~dp0kis_watchdog.py\"" /sc ONLOGON /rl HIGHEST /f > nul 2>&1
if %errorlevel% neq 0 (
    echo [경고] 작업 스케줄러 등록 실패.
    echo        관리자 권한으로 setup.bat을 다시 실행하거나,
    echo        taskschd.msc에서 수동으로 등록하세요.
) else (
    echo     작업 스케줄러 등록 완료
)

REM ── 완료 ───────────────────────────────────────────────────
echo.
echo ============================================================
echo   설치 완료!
echo.
echo   1. 위 환경변수를 시스템 환경변수에 등록하세요.
echo   2. watchdog.bat을 실행하거나,
echo      PC 재시작 후 자동으로 앱이 시작됩니다.
echo ============================================================
echo.
pause
