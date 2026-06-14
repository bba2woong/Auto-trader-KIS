@echo off
chcp 65001 > nul
title KIS Auto Trader - Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo   KIS Auto Trader - Setup
echo ============================================================
echo.

echo [1/9] Checking Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     Python %%PYVER%% found

echo.
echo [2/9] Creating virtual environment...
if exist "venv\Scripts\python.exe" (
    echo     venv already exists - skipping
) else (
    python -m venv venv
    if errorlevel 1 ( echo [ERROR] venv creation failed & pause & exit /b 1 )
    echo     venv created
)

echo.
echo [3/9] Installing Python packages...
venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )
echo     Packages installed

echo.
echo [4/9] Checking Node.js...
node --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    pause
    exit /b 1
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo     Node.js %%NODEVER%% found

echo.
echo [5/9] Installing Electron dependencies...
if exist "electron\node_modules\electron\dist\electron.exe" (
    echo     Electron already installed - skipping
) else (
    cmd /c "cd electron && npm install > nul 2>&1"
    echo     Electron installed
)

echo.
echo [6/9] Creating .cache folder...
if not exist ".cache" mkdir ".cache"
echo     Done

echo.
echo [7/9] Environment variable setup guide
echo   Please register the following in Windows System Environment Variables
echo   KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET / KIS_REAL_ACCOUNT
echo   KIS_MOCK_APP_KEY / KIS_MOCK_APP_SECRET / KIS_MOCK_ACCOUNT
echo   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
echo   TELEGRAM_ALARM_BOT_TOKEN / TELEGRAM_ALARM_CHAT_ID
echo   PERPLEXITY_API_KEY / DART_API_KEY

echo.
echo [8/9] Generating watchdog.bat...
venv\Scripts\python.exe write_watchdog.py
if errorlevel 1 (
    echo [WARNING] watchdog.bat generation failed - run write_watchdog.py manually
) else (
    echo     watchdog.bat generated
)

echo.
echo [9/9] Registering Windows Task Scheduler...
schtasks /query /tn "KIS WatchDog" > nul 2>&1
if not errorlevel 1 schtasks /delete /tn "KIS WatchDog" /f > nul 2>&1
schtasks /create /tn "KIS WatchDog" /tr "\"%~dp0venv\Scripts\pythonw.exe\" \"%~dp0kis_watchdog.py\"" /sc ONLOGON /rl HIGHEST /f > nul 2>&1
if errorlevel 1 (
    echo [WARNING] Scheduler registration failed - run as administrator
) else (
    echo     Task Scheduler registered
)

echo.
echo ============================================================
echo   Setup Complete!
echo   1. Register environment variables in system settings
echo   2. Run watchdog.bat or restart PC to auto-start
echo ============================================================
echo.
pause