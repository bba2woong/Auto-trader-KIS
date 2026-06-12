import math


def calc_sharpe(result) -> float:
    """
    샤프 비율 계산 (거래당 수익률 기준).
    거래 횟수 < 2이면 0 반환.
    """
    trades = result.get("trades", [])
    if len(trades) < 2:
        return 0.0
    rates = [t["pnl_rate"] for t in trades]
    mean  = sum(rates) / len(rates)
    std   = math.sqrt(sum((r - mean) ** 2 for r in rates) / len(rates))
    if std == 0:
        return 0.0
    return mean / std


def print_report(result, start_date, end_date, stock_pool_size):
    trades          = result["trades"]
    initial_capital = result["initial_capital"]
    final_capital   = result["final_capital"]
    equity_curve    = result["equity_curve"]
    daily_logs      = result["daily_logs"]

    total_return  = (final_capital - initial_capital) / initial_capital * 100
    total_trades  = len(trades)
    wins          = [t for t in trades if t["pnl_rate"] > 0]
    win_rate      = len(wins) / total_trades * 100 if total_trades else 0
    avg_return    = sum(t["pnl_rate"] for t in trades) / total_trades * 100 if total_trades else 0
    mdd           = _calc_mdd(equity_curve)
    sharpe        = calc_sharpe(result)
    active_days   = len(daily_logs)

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    print()
    print("=" * 50)
    print("  백테스팅 결과")
    print("=" * 50)
    print(f"  기간          : {start_date} ~ {end_date}")
    print(f"  스크리닝 풀   : {stock_pool_size}개 종목")
    print(f"  ────────────────────────────────────────────────")
    print(f"  초기 자금     : {initial_capital:>15,}원")
    print(f"  최종 자산     : {int(final_capital):>15,}원")
    print(f"  수익률        : {total_return:>+14.2f}%")
    print(f"  샤프 비율     : {sharpe:>+14.4f}")
    print(f"  ────────────────────────────────────────────────")
    print(f"  매매 발생일   : {active_days}일")
    print(f"  총 거래 횟수  : {total_trades}회")
    print(f"  승률          : {win_rate:>14.1f}%")
    print(f"  평균 수익률   : {avg_return:>+14.2f}%")
    print(f"  최대 낙폭     : {mdd:>+14.2f}%")
    print(f"  ────────────────────────────────────────────────")
    print(f"  청산 사유별:")
    for reason, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = cnt / total_trades * 100
        print(f"    {reason:<12}: {cnt:>3}회  ({pct:.1f}%)")
    print("=" * 50)

    if daily_logs:
        print("\n  최근 5 거래일 요약:")
        print(f"  {'날짜':<10}  {'종목':<10}  {'매수가':>8}  {'매도가':>8}  {'수익률':>8}  사유")
        print(f"  {'-'*60}")
        for log in daily_logs[-5:]:
            for t in log["trades"]:
                name = t["name"][:6]
                print(
                    f"  {t['date']:<10}  {name:<10}  {t['buy_price']:>8,}"
                    f"  {t['sell_price']:>8,}  {t['pnl_rate']*100:>+7.2f}%  {t['reason']}"
                )
    print()


def _calc_mdd(equity_curve):
    if len(equity_curve) < 2:
        return 0.0
    peak, mdd = equity_curve[0], 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (val - peak) / peak * 100
        if dd < mdd:
            mdd = dd
    return mdd
