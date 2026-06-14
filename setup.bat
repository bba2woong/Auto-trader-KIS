@echo off
chcp 65001 > nul
title KIS Auto Trader - Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo   KIS Auto Trader - Setup
echo ============================================================
echo.

REM ── [1] Python Check ───────────────────────────────────────
echo [1/10] Checking Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    echo         Required version: Python 3.11.x
    echo         Download: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     Python %PYVER% found

REM ── [2] Virtual Environment ────────────────────────────────
echo.
echo [2/10] Creating virtual environment...
if exist "venv\Scripts\python.exe" (
    echo     venv already exists - skipping
) else (
    python -m venv venv
    if errorlevel 1 ( echo [ERROR] venv creation failed & pause & exit /b 1 )
    echo     venv created
)

REM ── [3] Python Packages ────────────────────────────────────
echo.
echo [3/10] Installing Python packages...
venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )
echo     Packages installed

REM ── [4] Node.js Check ──────────────────────────────────────
echo.
echo [4/10] Checking Node.js...
node --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    echo         Download LTS version.
    pause
    exit /b 1
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo     Node.js %NODEVER% found

REM ── [5] Electron Dependencies ──────────────────────────────
echo.
echo [5/10] Installing Electron dependencies...
if exist "electron\node_modules\electron\dist\electron.exe" (
    echo     Electron already installed - skipping
) else (
    cmd /c "cd electron && npm install > nul 2>&1"
    echo     Electron installed
)

REM ── [6] .cache Folder ──────────────────────────────────────
echo.
echo [6/10] Creating .cache folder...
if not exist ".cache" mkdir ".cache"
echo     Done

REM ── [7] Environment Variable Guide ────────────────────────
echo.
echo [7/10] Environment variable setup guide
echo   Please register the following in Windows System Environment Variables
echo   (Run sysdm.cpl - Advanced - Environment Variables - System Variables - New)
echo.
echo   KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET / KIS_REAL_ACCOUNT
echo   KIS_MOCK_APP_KEY / KIS_MOCK_APP_SECRET / KIS_MOCK_ACCOUNT
echo   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
echo   TELEGRAM_ALARM_BOT_TOKEN / TELEGRAM_ALARM_CHAT_ID
echo   PERPLEXITY_API_KEY / DART_API_KEY

REM ── [8] Watchdog.bat ───────────────────────────────────────
echo.
echo [8/10] Generating watchdog.bat...
venv\Scripts\python.exe write_watchdog.py
if errorlevel 1 (
    echo [WARNING] watchdog.bat generation failed - run write_watchdog.py manually
) else (
    echo     watchdog.bat generated
)

REM ── [9] Task Scheduler ─────────────────────────────────────
echo.
echo [9/10] Registering Windows Task Scheduler...
schtasks /query /tn "KIS WatchDog" > nul 2>&1
if not errorlevel 1 schtasks /delete /tn "KIS WatchDog" /f > nul 2>&1
schtasks /create /tn "KIS WatchDog" /tr "\"%~dp0venv\Scripts\pythonw.exe\" \"%~dp0kis_watchdog.py\"" /sc ONLOGON /rl HIGHEST /f > nul 2>&1
if errorlevel 1 (
    echo [WARNING] Scheduler registration failed - run as administrator
    echo          Right-click setup.bat - Run as administrator
) else (
    echo     Task Scheduler registered
)

REM ── [10] Electron App Build ────────────────────────────────
echo.
echo [10/10] Building Electron app... (first build may take 10-30 mins)
echo         Step 1: Checking build configuration...
if not exist "electron\package.json" (
    echo [WARNING] electron\package.json not found - skipping build
    goto BUILD_DONE
)
echo         Step 2: Running electron-builder...
cd electron
npm run build
if errorlevel 1 (
    echo [WARNING] Electron build failed - check electron\package.json build script
    cd ..
    goto BUILD_DONE
)
cd ..
echo         Step 3: Verifying output...
if exist "electron\dist\*.exe" (
    echo         Step 4: Build complete!
    for %%f in (electron\dist\*.exe) do echo         Output: electron\%%f
) else (
    echo [WARNING] .exe not found in electron\dist\ - build may have failed
)
:BUILD_DONE

REM ── Done ───────────────────────────────────────────────────
echo.
echo ============================================================
echo   Setup Complete!
echo   1. Register environment variables in system settings
echo   2. Run watchdog.bat or restart PC to auto-start
echo ============================================================
echo.
pause