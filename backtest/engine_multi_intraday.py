"""
단타 멀티-포지션 백테스트 엔진 (분봉 기반, 다중 날짜)

시뮬레이션 흐름:
  10:00 일괄 스크리닝 → compute_tech_score(params) 상위 N개 선택
  → 10:00 기준가 동시 매수 (포지션별 독립 관리)
  → 손절 / 트레일링스탑 / 강제청산(15:20 종가)

params dict로 모든 배점·트레이딩 파라미터 주입 — 전역 sc 수정 없음.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc

SCREEN_TIME = "100000"   # 10:00 스크리닝 + 매수
FORCE_SELL  = "152000"   # 15:20 강제 청산 (scheduler 동일)


# ── 퍼블릭 API ──────────────────────────────────────────────────

def run_multi_intraday_backtest(
    minute_data_by_date,   # {date: {code: [bars]}}
    daily_data,            # {code: {date: ohlcv_row}}
    stock_list,            # [{"code","name"}, ...]
    initial_capital=10_000_000,
    params=None,
):
    """
    날짜 범위에 걸친 단타 백테스트.

    날마다:
      1) 10:00 일괄 스크리닝  (compute_tech_score + MIN_SCORE 필터)
      2) 점수 상위 MAX_POSITIONS개 동시 매수
      3) 각 포지션 독립 청산 (손절/트레일링/15:20 강제)

    반환: {"trades", "daily_logs", "equity_curve", "final_capital", "initial_capital"}
    """
    from backtest.screener_sim import get_default_bt_params
    if params is None:
        params = get_default_bt_params()

    capital      = float(initial_capital)
    equity_curve = [capital]
    all_trades   = []
    daily_logs   = []

    for date in sorted(minute_data_by_date.keys()):
        day_minute = minute_data_by_date[date]
        candidates = _screen_at_10(day_minute, daily_data, stock_list, date, params)
        if not candidates:
            continue

        max_pos = int(params.get("MAX_POSITIONS", sc.MAX_POSITIONS))
        selected = candidates[:max_pos]
        bpp = params.get("budget_per_position") or (capital / max(max_pos, 1))

        day_trades = []
        for cand in selected:
            bars      = day_minute.get(cand["code"], [])
            daily_day = (daily_data.get(cand["code"]) or {}).get(date)
            trade = _simulate_position(cand, bars, bpp, params, date, daily_day)
            if trade:
                day_trades.append(trade)

        for t in day_trades:
            capital += t["pnl"]
            equity_curve.append(capital)
            all_trades.append(t)

        if day_trades:
            daily_logs.append({
                "date":        date,
                "trades":      day_trades,
                "capital_end": capital,
            })

    return {
        "trades":          all_trades,
        "daily_logs":      daily_logs,
        "equity_curve":    equity_curve,
        "final_capital":   capital,
        "initial_capital": float(initial_capital),
    }


# ── 내부 함수 ──────────────────────────────────────────────────

def _screen_at_10(minute_data, daily_data, stock_list, date, params):
    """
    10:00 기준 스크리닝.
    - 변동성 돌파 목표가 체크 (전일 범위 × K + 당일 시가)
    - AD Line 상승 여부
    - compute_tech_score()로 배점 (params 주입)
    - MIN_SCORE 필터 → 점수 내림차순 반환
    """
    from backtest.screener_sim import compute_tech_score

    try:
        from watchlist import WATCHLIST_CODES
        wl_codes = set(WATCHLIST_CODES)
    except Exception:
        wl_codes = set()

    k         = params.get("K", sc.K)
    min_score = params.get("MIN_SCORE", 0)
    candidates = []

    for stock in stock_list:
        code = stock["code"]
        bars = minute_data.get(code, [])
        if not bars:
            continue

        # 10:00 이후 첫 봉
        bar_10 = next((b for b in bars if b["time"] >= SCREEN_TIME), None)
        if bar_10 is None:
            continue

        # 일봉 데이터
        dmap   = daily_data.get(code, {})
        sdates = sorted(dmap.keys())
        if date not in sdates:
            continue
        idx = sdates.index(date)
        if idx < 1:
            continue

        today_d    = dmap[date]
        prev_d     = dmap[sdates[idx - 1]]
        prev_range = prev_d["high"] - prev_d["low"]
        if prev_range == 0:
            continue

        today_open = today_d.get("open") or bars[0]["open"]
        target     = today_open + prev_range * k

        # 10:00 봉이 목표가에 도달했는지 확인
        if bar_10["high"] < target:
            continue

        # 매수가: 목표가 이상 (갭업 시 10:00 봉 시가 사용)
        buy_price = int(max(bar_10["open"], target))
        gap = (buy_price - target) / target * 100

        # AD Line (일봉 5일)
        window = [dmap[d] for d in sdates[max(0, idx - 4): idx + 1]]
        if not _ad_rising(window):
            continue

        # 9시봉 강봉 감지
        hour_candle = _agg_hour_candle(bars, 9)
        strong_bull = _is_strong_bull(hour_candle)

        # 일봉 해머 감지
        hammer = _is_hammer(today_d)

        sr = {
            "변동성돌파": True,
            "돌파여유율": gap,
            "AD상승":     True,
            "패턴":       "hammer" if hammer else None,
            "시간봉패턴": "strong_bull" if strong_bull else None,
            "watchlist":  code in wl_codes,
        }
        score = compute_tech_score(sr, params)

        if score < min_score:
            continue

        candidates.append({
            **stock,
            "target":     int(target),
            "buy_price":  buy_price,
            "entry_bar":  bar_10,
            "gap":        gap,
            "score":      score,
        })

    # 점수 내림차순, 동점이면 gap 오름차순
    candidates.sort(key=lambda x: (-x["score"], x["gap"]))
    return candidates


def _simulate_position(cand, bars, budget_per_pos, params, date, daily_ohlcv=None):
    """단일 포지션 분봉 시뮬레이션 (10:00 매수 → 청산)
    분봉 없으면 일봉 고/저/종가로 근사 처리.
    """
    buy_price  = cand["buy_price"]
    quantity   = int(budget_per_pos / buy_price)
    if quantity < 1:
        return None

    loss_rate = params.get("LOSS_RATE",                   sc.LOSS_RATE)
    trail_rt  = params.get("TRAILING_STOP_RATE",          sc.TRAILING_STOP_RATE)
    act_rt    = params.get("TRAILING_STOP_ACTIVATE_RATE", sc.TRAILING_STOP_ACTIVATE_RATE)
    use_trail = params.get("USE_TRAILING_STOP",           sc.USE_TRAILING_STOP)
    profit_rt = params.get("PROFIT_RATE",                 sc.PROFIT_RATE)

    # ── 분봉 없을 때 일봉으로 근사 ──────────────────────────────
    if not bars and daily_ohlcv:
        return _simulate_position_daily(cand, daily_ohlcv, budget_per_pos,
                                        loss_rate, trail_rt, act_rt, use_trail,
                                        profit_rt, date)

    entry_time   = cand["entry_bar"]["time"]
    peak         = float(buy_price)
    trail_active = False
    exit_price   = None
    exit_time    = None
    reason       = None

    for bar in bars:
        if bar["time"] < entry_time:
            continue

        # 강제 청산 (15:20 종가)
        if bar["time"] >= FORCE_SELL:
            exit_price = bar["close"]
            exit_time  = bar["time"]
            reason     = "강제청산"
            break

        if bar["high"] > peak:
            peak = float(bar["high"])

        if not trail_active and (peak - buy_price) / buy_price >= act_rt:
            trail_active = True

        # 손절
        stop_loss = buy_price * (1 - loss_rate)
        if bar["low"] <= stop_loss:
            exit_price = int(stop_loss)
            exit_time  = bar["time"]
            reason     = "손절"
            break

        # 트레일링 스탑 or 고정 익절
        if use_trail:
            if trail_active:
                trailing_stop = peak * (1 - trail_rt)
                if bar["low"] <= trailing_stop:
                    exit_price = int(trailing_stop)
                    exit_time  = bar["time"]
                    reason     = "트레일링스탑"
                    break
        else:
            if bar["high"] >= buy_price * (1 + profit_rt):
                exit_price = int(buy_price * (1 + profit_rt))
                exit_time  = bar["time"]
                reason     = "익절"
                break

    # 장 종료까지 청산 안 됨
    if exit_price is None:
        post = [b for b in bars if b["time"] >= entry_time]
        last = post[-1] if post else None
        exit_price = last["close"] if last else buy_price
        exit_time  = last["time"]  if last else entry_time
        reason     = "장종료청산"

    pnl      = (exit_price - buy_price) * quantity
    pnl_rate = (exit_price - buy_price) / buy_price

    return {
        "code":       cand["code"],
        "name":       cand["name"],
        "date":       date,
        "entry_time": entry_time,
        "exit_time":  exit_time,
        "buy_price":  buy_price,
        "sell_price": exit_price,
        "quantity":   quantity,
        "pnl":        pnl,
        "pnl_rate":   pnl_rate,
        "reason":     reason,
        "score":      cand["score"],
        "target":     cand["target"],
        "gap":        cand["gap"],
    }


def _simulate_position_daily(cand, ohlcv, budget_per_pos,
                              loss_rate, trail_rt, act_rt, use_trail,
                              profit_rt, date):
    """분봉 없을 때 일봉 고/저/종가로 포지션 근사 시뮬레이션."""
    buy_price = cand["buy_price"]
    quantity  = int(budget_per_pos / buy_price)
    if quantity < 1:
        return None

    day_high  = ohlcv.get("high",  buy_price)
    day_low   = ohlcv.get("low",   buy_price)
    day_close = ohlcv.get("close", buy_price)

    stop_loss = buy_price * (1 - loss_rate)
    if day_low <= stop_loss:
        exit_price, reason = int(stop_loss), "손절"
    elif use_trail:
        peak   = max(buy_price, day_high)
        t_stop = peak * (1 - trail_rt)
        if day_low <= t_stop:
            exit_price, reason = int(t_stop), "트레일링스탑"
        else:
            exit_price, reason = day_close, "장종료청산"
    else:
        profit_target = buy_price * (1 + profit_rt)
        if day_high >= profit_target:
            exit_price, reason = int(profit_target), "익절"
        else:
            exit_price, reason = day_close, "장종료청산"

    pnl      = (exit_price - buy_price) * quantity
    pnl_rate = (exit_price - buy_price) / buy_price
    return {
        "code":       cand["code"],
        "name":       cand["name"],
        "date":       date,
        "entry_time": "100000",
        "exit_time":  "152000",
        "buy_price":  buy_price,
        "sell_price": exit_price,
        "quantity":   quantity,
        "pnl":        pnl,
        "pnl_rate":   pnl_rate,
        "reason":     reason + "(일봉근사)",
        "score":      cand["score"],
        "target":     cand["target"],
        "gap":        cand["gap"],
    }


# ── 헬퍼 ────────────────────────────────────────────────────────

def _ad_rising(window):
    if len(window) < 2:
        return False
    cumsum, line = 0, []
    for r in window:
        h, l, c, v = r["high"], r["low"], r["close"], r["volume"]
        ad = ((c - l) - (h - c)) / (h - l) * v if h != l else 0
        cumsum += ad
        line.append(cumsum)
    return line[-1] > line[-2]


def _agg_hour_candle(bars, hour: int):
    ph = [b for b in bars if b["time"].startswith(f"{hour:02d}")]
    if not ph:
        return None
    return {
        "open":  ph[0]["open"],
        "high":  max(b["high"]   for b in ph),
        "low":   min(b["low"]    for b in ph),
        "close": ph[-1]["close"],
    }


def _is_strong_bull(candle) -> bool:
    if candle is None:
        return False
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    rng = h - l
    if rng == 0 or c <= o:
        return False
    body       = c - o
    upper_wick = h - c
    return (body / rng >= 0.7) and (upper_wick <= body * 0.3)


def _is_hammer(candle) -> bool:
    if not candle:
        return False
    o, h, l, c = candle.get("open", 0), candle.get("high", 0), \
                 candle.get("low", 0),  candle.get("close", 0)
    body  = abs(c - o)
    rng   = h - l
    if rng == 0 or body == 0:
        return False
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower >= 2 * body and upper <= body * 0.3
