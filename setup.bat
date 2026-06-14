@echo off
title KIS Auto Trader - Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo   KIS Auto Trader - Setup
echo ============================================================
echo.

echo [1/10] Checking Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo         Install Python 3.11.9 from:
    echo         https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    echo         Check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     Python %PYVER% found

echo.
echo [2/10] Creating virtual environment...
if exist "venv\Scripts\python.exe" (
    echo     venv already exists - skipping
) else (
    python -m venv venv
    if errorlevel 1 ( echo [ERROR] venv creation failed & pause & exit /b 1 )
    echo     venv created
)

echo.
echo [3/10] Installing Python packages...
venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )
echo     Packages installed

echo.
echo [4/10] Checking Node.js...
node --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found.
    echo         Install LTS version from https://nodejs.org
    pause
    exit /b 1
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo     Node.js %NODEVER% found

echo.
echo [5/10] Installing Electron dependencies...
if exist "electron\node_modules\electron\dist\electron.exe" (
    echo     Electron already installed - skipping
) else (
    cmd /c "cd /d "%~dp0electron" && npm install"
    echo     Checking electron binary...
    if exist "electron\node_modules\electron\dist\electron.exe" (
        echo     Electron binary found
    ) else (
        echo     Extracting from cache...
        powershell -Command "$d='electron\node_modules\electron\dist'; $zip=Get-ChildItem \"$env:LOCALAPPDATA\electron\Cache\*.zip\" | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($zip){Expand-Archive -Path $zip.FullName -DestinationPath $d -Force; Write-Host 'Done'} else {Write-Host 'No zip found'}"
        if exist "electron\node_modules\electron\dist\electron.exe" (
            echo     Electron binary extracted
        ) else (
            echo [ERROR] Electron binary not found
            pause
            exit /b 1
        )
    )
)

echo.
echo [6/10] Creating .cache folder...
if not exist ".cache" mkdir ".cache"
echo     Done

echo.
echo [7/10] Environment variable setup guide
echo   Register the following in Windows System Environment Variables
echo   (sysdm.cpl - Advanced - Environment Variables - New)
echo.
echo   KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET / KIS_REAL_ACCOUNT
echo   KIS_MOCK_APP_KEY / KIS_MOCK_APP_SECRET / KIS_MOCK_ACCOUNT
echo   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
echo   TELEGRAM_ALARM_BOT_TOKEN / TELEGRAM_ALARM_CHAT_ID
echo   PERPLEXITY_API_KEY / DART_API_KEY

echo.
echo [8/10] Generating watchdog.bat...
venv\Scripts\python.exe write_watchdog.py
if errorlevel 1 (
    echo [WARNING] watchdog.bat generation failed - run write_watchdog.py manually
) else (
    echo     watchdog.bat generated
)

echo.
echo [9/10] Registering Windows Task Scheduler...
schtasks /query /tn "KIS WatchDog" > nul 2>&1
if not errorlevel 1 schtasks /delete /tn "KIS WatchDog" /f > nul 2>&1
schtasks /create /tn "KIS WatchDog" /tr "\"%~dp0venv\Scripts\pythonw.exe\" \"%~dp0kis_watchdog.py\"" /sc ONLOGON /rl HIGHEST /f > nul 2>&1
if errorlevel 1 (
    echo [WARNING] Scheduler registration failed - run as administrator
) else (
    echo     Task Scheduler registered
)

echo.
echo [10/10] Creating desktop shortcut...
set APPDIR=%~dp0
set LAUNCH_VBS=%~dp0launch.vbs
set SHORTCUT_VBS=%~dp0create_shortcut.vbs
set ELECTRON_EXE=%~dp0electron\node_modules\electron\dist\electron.exe
set ELECTRON_DIR=%~dp0electron
set ICON_PATH=%~dp0assets\20260610_172343.ico

(
echo Set ws = CreateObject^("WScript.Shell"^)
echo ws.Run Chr^(34^) ^& "%ELECTRON_EXE%" ^& Chr^(34^) ^& " " ^& Chr^(34^) ^& "%ELECTRON_DIR%" ^& Chr^(34^), 1, False
) > "%LAUNCH_VBS%"

(
echo Set ws = CreateObject^("WScript.Shell"^)
echo Set s = ws.CreateShortcut^(ws.SpecialFolders^("Desktop"^) ^& "\KIS Auto Trader.lnk"^)
echo s.TargetPath = "wscript.exe"
echo s.Arguments = Chr^(34^) ^& "%LAUNCH_VBS%" ^& Chr^(34^)
echo s.WorkingDirectory = "%APPDIR%"
echo s.IconLocation = "%ICON_PATH%"
echo s.Save^(^)
) > "%SHORTCUT_VBS%"

cscript //nologo "%SHORTCUT_VBS%"
if errorlevel 1 (
    echo [WARNING] Shortcut creation failed
) else (
    echo     Desktop shortcut created
)

echo.
echo ============================================================
echo   Setup Complete!
echo   1. Register environment variables in system settings
echo   2. Use desktop shortcut to start KIS Auto Trader
echo ============================================================
echo.
pause