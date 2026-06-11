"""
현재 스크립트 위치를 기준으로 watchdog.bat을 동적 생성합니다.
setup.bat 또는 수동으로 실행하세요.
"""
import os
from pathlib import Path

BASE = Path(__file__).parent.resolve()

# BAT 내에서 사용할 경로
base_str     = str(BASE)
python_exe   = str(BASE / "venv" / "Scripts" / "python.exe")
electron_exe = str(BASE / "electron" / "node_modules" / "electron" / "dist" / "electron.exe")
electron_dir = str(BASE / "electron")
logfile      = str(BASE / ".cache" / "watchdog.log")
bat_path     = BASE / "watchdog.bat"

content = (
    "@echo off\r\n"
    "chcp 65001 > nul\r\n"
    "title WatchDog - KIS Auto Trader\r\n"
    f'cd /d "{base_str}"\r\n'
    "\r\n"
    'if not exist ".cache" mkdir ".cache"\r\n'
    f'set LOGFILE={logfile}\r\n'
    'echo [WatchDog] Started at %date% %time% >> "%LOGFILE%"\r\n'
    "\r\n"
    ":check_hours\r\n"
    f'"{python_exe}"'
    ' -c "import sys; from datetime import datetime; h=datetime.now().hour; sys.exit(0 if 8<=h<15 else 1)"\r\n'
    "if %errorlevel% == 0 goto loop\r\n"
    "\r\n"
    'echo [WatchDog] Outside market hours - standby 60s >> "%LOGFILE%"\r\n'
    "ping -n 61 127.0.0.1 > nul\r\n"
    "goto check_hours\r\n"
    "\r\n"
    ":loop\r\n"
    'echo [WatchDog] %date% %time% - Starting KIS Auto Trader... >> "%LOGFILE%"\r\n'
    "\r\n"
    f'"{electron_exe}" "{electron_dir}"\r\n'
    "\r\n"
    'echo [WatchDog] App exited at %time% >> "%LOGFILE%"\r\n'
    "\r\n"
    "ping -n 11 127.0.0.1 > nul\r\n"
    "goto check_hours\r\n"
)

with open(bat_path, "w", encoding="utf-8-sig") as f:
    f.write(content)
print(f"watchdog.bat 생성 완료: {bat_path}")
