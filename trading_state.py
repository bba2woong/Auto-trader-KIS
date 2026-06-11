"""
trading_state.py — 트레이딩 실행 상태 영속화

watchdog.bat 재시작 후 app.py가 비정상 종료 여부를 감지하는 데 사용.
scheduler.run_scheduler() 시작/종료 시 save_state/clear_state 호출.
"""
import json
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / ".cache" / "trader_state.json"


def save_state(mode: str, running: bool):
    """트레이딩 상태 저장 (스케줄러 시작 시 호출)"""
    import os
    STATE_FILE.parent.mkdir(exist_ok=True)
    state = {
        "mode":       mode,
        "running":    running,
        "pid":        os.getpid(),   # F5 새로고침 vs 실제 재시작 구분용
        "updated_at": datetime.now().isoformat(),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def load_state() -> dict:
    """저장된 상태 로드. 없거나 파싱 실패 시 기본값 반환"""
    if not STATE_FILE.exists():
        return {"mode": "mock", "running": False}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"mode": "mock", "running": False}


def clear_state():
    """정상 종료 시 running=False로 업데이트"""
    state = load_state()
    state["running"]    = False
    state["updated_at"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def is_market_hours() -> bool:
    """현재 장 중(09:00~15:00)인지 확인"""
    now = datetime.now().strftime("%H:%M")
    return "09:00" <= now <= "15:00"
