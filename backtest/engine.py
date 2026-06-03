"""
백테스트 엔진
실제 스케줄러(scheduler.py)와 동일한 하루 매매 사이클을 일봉 데이터로 시뮬레이션한다.

사이클:
  09:30 스크리닝 → [1]번 종목 선택 → 매수(목표가 체결 가정)
  → 트레일링스탑 / 하드손절 / 종가청산
  → 재스크리닝(당일 나머지 후보 순서대로) → ...
  → 15:20 강제 청산 (일봉 근사: 종가)
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc
from backtest.screener_sim import screen_day


def run_backtest(all_data, stock_list, start_date, end_date, initial_capital=1_000_000):
    """
    all_data      : {code: {date: ohlcv_row}}
    stock_list    : [{"code","name"}, ...]
    반환          : {"trades", "daily_logs", "equity_curve",
                     "final_capital", "initial_capital"}
    """
    # 공통 거래일 목록 (start_date ~ end_date, 오름차순)
    trading_days = _get_trading_days(all_data, start_date, end_date)

    capital      = float(initial_capital)
    equity_curve = [capital]
    all_trades   = []
    daily_logs   = []
    cooldown_map = {}   # {code: date(str)} 마지막 청산일

    for date in trading_days:
        day_result = _simulate_day(
            date, all_data, stock_list, capital, cooldown_map
        )

        for trade in day_result["trades"]:
            capital += trade["pnl"]
            equity_curve.append(capital)
            all_trades.append(trade)

        if day_result["trades"]:
            daily_logs.append({
                "date":   date,
                "trades": day_result["trades"],
                "capital_end": capital,
            })

    return {
        "trades":          all_trades,
        "daily_logs":      daily_logs,
        "equity_curve":    equity_curve,
        "final_capital":   capital,
        "initial_capital": initial_capital,
    }


# ──────────────────────────────────────────
# 내부 함수
# ──────────────────────────────────────────

def _simulate_day(date, all_data, stock_list, capital, cooldown_map):
    """
    하루 매매 사이클 시뮬레이션.
    당일 스크리닝 → [1]번 매매 → 재스크리닝(잔여 후보 순서) → 반복
    """
    # 당일 스크리닝
    candidates = screen_day(all_data, date, stock_list)

    # 쿨다운 중인 종목 제거
    candidates = [
        c for c in candidates
        if cooldown_map.get(c["code"]) != date  # 당일 이미 매매한 종목 제외
    ]

    trades      = []
    trade_count = 0

    while candidates and trade_count < sc.MAX_TRADES_PER_DAY:
        # 1순위 후보 선택
        target = candidates.pop(0)
        code   = target["code"]

        trade = _execute_trade(target, capital)
        if trade is None:
            continue   # 자금 부족 → 다음 후보

        capital += trade["pnl"]
        trade_count += 1
        cooldown_map[code] = date  # 당일 재진입 금지
        trades.append(trade)

        # 강제 청산 시간 이후면 추가 매매 없음 (일봉 근사: 종가청산이면 15:20 이후로 간주)
        if trade["reason"] in ("강제청산", "종가청산"):
            break

    return {"trades": trades}


def _execute_trade(candidate, capital):
    """
    단일 종목 매매 시뮬레이션 (일봉 OHLC 근사)
    반환: trade dict 또는 None(자금 부족)
    """
    today     = candidate["today"]
    buy_price = candidate["buy_price"]   # 목표가에 체결 가정

    quantity = int(capital * sc.INVEST_RATIO / buy_price)
    if quantity < 1:
        return None

    sell_price, reason = _resolve_exit(today, buy_price)

    cost     = quantity * buy_price
    proceeds = quantity * sell_price
    pnl      = proceeds - cost
    pnl_rate = (sell_price - buy_price) / buy_price

    return {
        "date":       today["date"],
        "code":       candidate["code"],
        "name":       candidate["name"],
        "buy_price":  buy_price,
        "sell_price": sell_price,
        "quantity":   quantity,
        "pnl":        pnl,
        "pnl_rate":   pnl_rate,
        "reason":     reason,
        "target":     candidate["target"],
        "gap":        candidate["gap"],
    }


def _resolve_exit(today, buy_price):
    """
    일봉 OHLC 기준 청산 가격 / 사유 결정
    우선순위: 하드손절 > 트레일링스탑/고정익절 > 종가청산(강제청산 포함)
    """
    stop_loss_price = buy_price * (1 - sc.LOSS_RATE)

    # 1) 하드 손절: 저가가 손절선 이하
    if today["low"] <= stop_loss_price:
        return int(stop_loss_price), "손절"

    # 2) 트레일링 스탑 or 고정 익절
    if sc.USE_TRAILING_STOP:
        peak      = today["high"]   # 당일 고가를 피크 근사값으로 사용
        peak_rate = (peak - buy_price) / buy_price
        if peak_rate >= sc.TRAILING_STOP_ACTIVATE_RATE:
            trailing_stop = peak * (1 - sc.TRAILING_STOP_RATE)
            if today["close"] <= trailing_stop:
                return int(trailing_stop), "트레일링스탑"
    else:
        profit_target = buy_price * (1 + sc.PROFIT_RATE)
        if today["high"] >= profit_target:
            return int(profit_target), "익절"

    # 3) 종가 청산 (15:20 강제 청산 ≈ 종가)
    return today["close"], "강제청산"


def _get_trading_days(all_data, start_date, end_date):
    """전체 종목에서 거래일 합집합 추출 (start_date ~ end_date)"""
    days = set()
    for date_map in all_data.values():
        for d in date_map:
            if start_date <= d <= end_date:
                days.add(d)
    return sorted(days)
