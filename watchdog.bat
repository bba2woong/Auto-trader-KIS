@echo off
chcp 65001 > nul

@REM ================================================================
@REM Task Scheduler setup (run on startup):
@REM   Program  : cmd.exe
@REM   Arguments: /c "C:\KIS_Trader\1. Practice\kis_trader\watchdog.bat"
@REM   Check "Run with highest privileges"
@REM ================================================================

cd /d "C:\KIS_Trader\1. Practice\kis_trader"
if not exist "C:\KIS_Trader\1. Practice\kis_trader\.cache" mkdir "C:\KIS_Trader\1. Practice\kis_trader\.cache"

:loop
echo [WatchDog] %date% %time% - Starting Streamlit...
"C:\KIS_Trader\1. Practice\kis_trader\venv\Scripts\streamlit.exe" run "C:\KIS_Trader\1. Practice\kis_trader\app.py"

echo [WatchDog] Streamlit exited - checking market hours...

"C:\KIS_Trader\1. Practice\kis_trader\venv\Scripts\python.exe" -c "from datetime import datetime; h=datetime.now().strftime('%%H:%%M'); print('MARKET' if '09:00'<=h<='15:30' else 'CLOSED')" > "C:\KIS_Trader\1. Practice\kis_trader\.cache\market_check.txt" 2>nul

findstr "MARKET" "C:\KIS_Trader\1. Practice\kis_trader\.cache\market_check.txt" > nul
if %errorlevel% == 0 (
    echo [WatchDog] Market hours - restarting in 10 seconds...
    timeout /t 10 /nobreak
) else (
    echo [WatchDog] Outside market hours - standby 60 seconds...
    timeout /t 60 /nobreak
)

goto loop
