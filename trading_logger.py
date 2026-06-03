"""
매매 로그 기록 모듈
장 중 모든 이벤트를 trading_logs/YYYYMMDD.jsonl 에 append 저장.

이벤트 종류:
  screening_result  — 스크리닝 결과 + AI 점수
  auto_buy          — 자동 매수 결정
  confirm_sent      — 텔레그램 확인 요청
  confirm_selected  — 텔레그램 종목 선택
  buy_executed      — 실제 매수 체결
  sell_executed     — 실제 매도 체결
  daily_summary     — 당일 최종 요약
"""
import json
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "trading_logs"
LOG_DIR.mkdir(exist_ok=True)


def _log_path(date_str: str = None) -> Path:
    d = date_str or datetime.now().strftime("%Y%m%d")
    return LOG_DIR / f"{d}.jsonl"


def _write(event: dict):
    event.setdefault("ts", datetime.now().strftime("%H:%M:%S"))
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────
# 이벤트별 로그 함수
# ──────────────────────────────────────────

def log_screening(round_no: int, candidates: list, skipped: list = None):
    """스크리닝 결과 + AI 점수"""
    _write({
        "event":      "screening_result",
        "round":      round_no,
        "candidates": [
            {
                "code":    c["code"],
                "name":    c["name"],
                "score":   c.get("score", 0),
                "tech":    c.get("score_detail", {}).get("tech", 0),
                "llm":     c.get("score_detail", {}).get("llm", 0),
                "dart":    c.get("score_detail", {}).get("dart", 0),
                "route":   c.get("route", ""),
                "gap":     round(c.get("돌파여유율", 0), 2),
                "pattern": c.get("패턴"),
                "grade":   c.get("grade"),
            }
            for c in candidates
        ],
        "skipped_cnt": len(skipped or []),
    })


def log_auto_buy(stock: dict):
    """자동 매수 결정"""
    d = stock.get("score_detail", {})
    _write({
        "event":   "auto_buy",
        "code":    stock["code"],
        "name":    stock["name"],
        "score":   stock.get("score", 0),
        "tech":    d.get("tech", 0),
        "llm":     d.get("llm", 0),
        "dart":    d.get("dart", 0),
        "llm_opinion": d.get("llm_opinion", ""),
        "llm_reason":  d.get("llm_reason", ""),
    })


def log_confirm_sent(candidates: list):
    """텔레그램 확인 요청"""
    _write({
        "event":      "confirm_sent",
        "candidates": [{"code": c["code"], "name": c["name"],
                        "score": c.get("score", 0)} for c in candidates],
    })


def log_confirm_selected(stock: dict):
    """텔레그램 종목 선택"""
    _write({
        "event": "confirm_selected",
        "code":  stock["code"],
        "name":  stock["name"],
        "score": stock.get("score", 0),
    })


def log_buy(code: str, name: str, buy_price: int, quantity: int, budget: int, slot_no: int):
    """매수 체결"""
    _write({
        "event":     "buy_executed",
        "slot":      slot_no,
        "code":      code,
        "name":      name,
        "buy_price": buy_price,
        "quantity":  quantity,
        "budget":    budget,
        "amount":    buy_price * quantity,
    })


def log_sell(code: str, name: str, buy_price: int, sell_price: int,
             quantity: int, reason: str, slot_no: int):
    """매도 체결"""
    pnl      = (sell_price - buy_price) * quantity
    pnl_rate = (sell_price - buy_price) / buy_price * 100
    _write({
        "event":      "sell_executed",
        "slot":       slot_no,
        "code":       code,
        "name":       name,
        "buy_price":  buy_price,
        "sell_price": sell_price,
        "quantity":   quantity,
        "pnl":        pnl,
        "pnl_rate":   round(pnl_rate, 2),
        "reason":     reason,
    })


def log_daily_summary(trade_count: int, daily_log: list):
    """당일 마감 요약"""
    sells = [e for e in daily_log if e.get("결과")]
    _write({
        "event":        "daily_summary",
        "trade_count":  trade_count,
        "results":      daily_log,
        "total_pnl":    0,   # PositionManager에서 집계 필요
    })


# ──────────────────────────────────────────
# 로그 읽기 (Streamlit 뷰어용)
# ──────────────────────────────────────────

def load_log(date_str: str) -> list:
    """날짜별 로그 파일 읽기. 반환: 이벤트 리스트"""
    path = _log_path(date_str)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events


def list_log_dates() -> list:
    """로그가 있는 날짜 목록 반환 (최신순)"""
    files = sorted(LOG_DIR.glob("*.jsonl"), reverse=True)
    return [f.stem for f in files]
