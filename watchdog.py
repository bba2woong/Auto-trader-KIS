"""
watchdog.py — KIS Auto Trader WatchDog (창 없이 백그라운드 실행용)
Task Scheduler에서 pythonw.exe로 실행 시 CMD 창 미표시.
"""
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

BASE    = Path(r"C:\KIS_Trader\1. Practice\kis_trader")
PYTHON  = BASE / "venv" / "Scripts" / "pythonw.exe"
ELECTRON = BASE / "electron" / "node_modules" / "electron" / "dist" / "electron.exe"
LOGFILE = BASE / ".cache" / "watchdog.log"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[WatchDog] {ts} {msg}\n"
    try:
        LOGFILE.parent.mkdir(exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def is_market_hours():
    h = datetime.now().hour
    return 8 <= h < 15


def main():
    log("Started")
    while True:
        if not is_market_hours():
            log("Outside market hours — standby 60s")
            time.sleep(60)
            continue

        log("Starting KIS Auto Trader...")
        try:
            proc = subprocess.run(
                [str(ELECTRON), str(BASE / "electron")],
                cwd=str(BASE),
            )
            log(f"App exited (code {proc.returncode})")
        except Exception as e:
            log(f"Launch error: {e}")

        time.sleep(10)


if __name__ == "__main__":
    main()
