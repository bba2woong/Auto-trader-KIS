"""
단타 하루치 백테스트 엔진 (분봉 기반)

시뮬레이션 흐름 (실제 스케줄러 동일):
  09:30 이후 매 분봉마다 스크리닝
    → 목표가 돌파 + AD상승 종목 발견 시 [1]번 매수
    → 분봉 단위로 트레일링스탑 / 하드손절 감시
    → 청산 후 재스크리닝 (잔여 후보 중 다음 종목)
  15:20 강제 청산
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc

SCAN_START  = "093000"   # 스크리닝 시작 (장 개시 후 30분)
FORCE_SELL  = "152000"   # 강제 청산


def run_intraday_backtest(minute_data, daily_data, stock_list, date,
                          initial_capital=1_000_000, params=None):
    """
    minute_data : {code: [{"time","open","high","low","close","volume"}, ...]}  시간 오름차순
    daily_data  : {code: {date: ohlcv_row}}  일봉 (전일 데이터 포함)
    stock_list  : [{"code","name"}, ...]
    date        : "YYYYMMDD"
    params      : {"K", "LOSS_RATE", "TRAILING_STOP_RATE", "INVEST_RATIO", ...}
                  None이면 strategy_config 전역값 사용.
                  그리드 서치 시 전역값 오염 방지를 위해 params를 전달.

    반환: {"trades", "equity_curve", "final_capital", "initial_capital", "timeline"}
    """
    # params가 없으면 현재 sc 값으로 스냅샷 (전역 변경에 영향 안 받도록)
    if params is None:
        params = {
            "K":                    sc.K,
            "LOSS_RATE":            sc.LOSS_RATE,
            "TRAILING_STOP_RATE":   sc.TRAILING_STOP_RATE,
            "TRAILING_STOP_ACTIVATE_RATE": sc.TRAILING_STOP_ACTIVATE_RATE,
            "USE_TRAILING_STOP":    sc.USE_TRAILING_STOP,
            "PROFIT_RATE":          sc.PROFIT_RATE,
            "INVEST_RATIO":         sc.INVEST_RATIO,
            "MAX_TRADES_PER_DAY":   sc.MAX_TRADES_PER_DAY,
        }
    # ── 목표가 / AD 상승 여부 사전 계산 ──
    candidates = _build_candidates(minute_data, daily_data, stock_list, date, params)
    if not candidates:
        return _empty_result(initial_capital)

    # ── 분봉 공통 타임라인 생성 (전 종목 합집합) ──
    all_times = sorted({b["time"] for bars in minute_data.values() for b in bars
                        if b["time"] >= SCAN_START})

    capital      = float(initial_capital)
    equity_curve = [capital]
    trades       = []
    timeline     = []   # 디버그/로그용

    holding      = None   # 현재 보유 종목 정보
    peak_price   = 0
    trail_active = False
    available    = list(candidates)   # 아직 매매 안 한 후보 (순서 유지)
    traded_codes = set()
    trade_count  = 0

    for t in all_times:
        # ── 강제 청산 시간 ──
        if t >= FORCE_SELL:
            if holding:
                sell_p = _bar_at(minute_data[holding["code"]], t)["close"]
                trade  = _close_trade(holding, sell_p, t, "강제청산", capital)
                capital += trade["pnl"]
                equity_curve.append(capital)
                trades.append(trade)
                timeline.append(f"{t} 강제청산 {holding['name']} @ {sell_p:,}")
                holding = None
            break

        # ── 보유 중: 청산 조건 체크 ──
        if holding:
            bar = _bar_at(minute_data[holding["code"]], t)
            if bar is None:
                continue

            # 고점 갱신
            if bar["high"] > peak_price:
                peak_price = bar["high"]

            p = holding["params"]
            reason, sell_p = _check_exit(bar, holding["buy_price"], peak_price, trail_active, p)

            # 트레일링 활성화 체크
            if not trail_active:
                peak_rate = (peak_price - holding["buy_price"]) / holding["buy_price"]
                if peak_rate >= p["TRAILING_STOP_ACTIVATE_RATE"]:
                    trail_active = True

            if reason:
                trade = _close_trade(holding, sell_p, t, reason, capital)
                capital += trade["pnl"]
                equity_curve.append(capital)
                trades.append(trade)
                timeline.append(f"{t} {reason} {holding['name']} @ {sell_p:,}  ({trade['pnl_rate']*100:+.2f}%)")
                holding      = None
                peak_price   = 0
                trail_active = False
            else:
                stop_p = peak_price * (1 - sc.TRAILING_STOP_RATE) if trail_active else \
                         holding["buy_price"] * (1 - sc.LOSS_RATE)
                timeline.append(
                    f"{t} 보유 {holding['name']} | 현재: {bar['close']:,} "
                    f"| 고점: {peak_price:,} | 스탑: {stop_p:,.0f}"
                )
            continue

        # ── 미보유: 매수 신호 탐색 ──
        if trade_count >= sc.MAX_TRADES_PER_DAY:
            break

        for cand in available:
            code = cand["code"]
            if code in traded_codes:
                continue
            bar = _bar_at(minute_data.get(code, []), t)
            if bar is None:
                continue

            # 현재 분봉 종가가 목표가 이상 → 매수 신호
            if bar["close"] >= cand["target"]:
                buy_p    = cand["target"]    # 목표가에 체결 가정
                quantity = int(capital * sc.INVEST_RATIO / buy_p)
                if quantity < 1:
                    continue

                holding      = {**cand, "buy_price": buy_p, "quantity": quantity,
                               "entry_time": t, "params": params}
                peak_price   = buy_p
                trail_active = False
                traded_codes.add(code)
                trade_count  += 1
                timeline.append(f"{t} 매수 {cand['name']} @ {buy_p:,}  (목표가: {cand['target']:,})")
                break   # 1번만 매수

    # ── 장 종료 후 잔여 포지션 청산 ──
    if holding:
        last_bars = minute_data.get(holding["code"], [])
        sell_p    = last_bars[-1]["close"] if last_bars else holding["buy_price"]
        trade     = _close_trade(holding, sell_p, "153000", "장종료청산", capital)
        capital  += trade["pnl"]
        equity_curve.append(capital)
        trades.append(trade)

    return {
        "trades":          trades,
        "equity_curve":    equity_curve,
        "final_capital":   capital,
        "initial_capital": initial_capital,
        "timeline":        timeline,
        "date":            date,
    }


# ──────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────

def _build_candidates(minute_data, daily_data, stock_list, date, params):
    """
    목표가 + AD상승 기준으로 후보 종목 목록 생성.
    오늘 시가는 분봉 첫 번째 봉의 open 사용.
    정렬: 목표가 낮은 것 우선 (스크리닝과 동일 정책).
    """
    result = []
    for stock in stock_list:
        code = stock["code"]
        bars = minute_data.get(code)
        if not bars:
            continue

        # 오늘 시가
        today_open = bars[0]["open"]

        # 전일 데이터
        dmap = daily_data.get(code, {})
        dates = sorted(dmap.keys())
        if date not in dates:
            continue
        idx = dates.index(date)
        if idx < 1:
            continue
        prev = dmap[dates[idx - 1]]

        prev_range = prev["high"] - prev["low"]
        if prev_range == 0:
            continue
        target = today_open + prev_range * params["K"]

        # AD Line 상승 여부 (일봉 기준)
        window = [dmap[d] for d in dates[max(0, idx - 4): idx + 1]]
        if not _ad_rising(window):
            continue

        result.append({
            **stock,
            "target":    int(target),
            "today_open": today_open,
        })

    # 목표가 낮은 순 (더 일찍 돌파 가능한 것 우선)
    result.sort(key=lambda x: x["target"])
    return result


def _check_exit(bar, buy_price, peak_price, trail_active, params):
    """
    현재 분봉 기준 청산 조건 체크 (params로 전역 오염 방지)
    반환: (reason, sell_price) or (None, None)
    """
    stop_loss = buy_price * (1 - params["LOSS_RATE"])
    if bar["low"] <= stop_loss:
        return "손절", int(stop_loss)

    if params["USE_TRAILING_STOP"]:
        if trail_active:
            trailing_stop = peak_price * (1 - params["TRAILING_STOP_RATE"])
            if bar["low"] <= trailing_stop:
                return "트레일링스탑", int(trailing_stop)
    else:
        profit_target = buy_price * (1 + params["PROFIT_RATE"])
        if bar["high"] >= profit_target:
            return "익절", int(profit_target)

    return None, None


def _close_trade(holding, sell_price, sell_time, reason, capital):
    buy_p    = holding["buy_price"]
    qty      = holding["quantity"]
    pnl      = (sell_price - buy_p) * qty
    pnl_rate = (sell_price - buy_p) / buy_p
    return {
        "code":        holding["code"],
        "name":        holding["name"],
        "entry_time":  holding["entry_time"],
        "exit_time":   sell_time,
        "buy_price":   buy_p,
        "sell_price":  sell_price,
        "quantity":    qty,
        "pnl":         pnl,
        "pnl_rate":    pnl_rate,
        "reason":      reason,
        "target":      holding["target"],
    }


def _bar_at(bars, time_str):
    """특정 시간의 분봉 반환 (없으면 None)"""
    for b in bars:
        if b["time"] == time_str:
            return b
    return None


def _ad_rising(window):
    if len(window) < 2:
        return False
    cumsum, ad_line = 0, []
    for r in window:
        h, l, c, v = r["high"], r["low"], r["close"], r["volume"]
        ad = ((c - l) - (h - c)) / (h - l) * v if h != l else 0
        cumsum += ad
        ad_line.append(cumsum)
    return ad_line[-1] > ad_line[-2]


def _empty_result(initial_capital):
    return {
        "trades":          [],
        "equity_curve":    [float(initial_capital)],
        "final_capital":   float(initial_capital),
        "initial_capital": initial_capital,
        "timeline":        [],
        "date":            "",
    }
