"""
백테스팅 진입점 (run_backtest_menu)

시뮬레이션 사이클 (실제 스케줄러와 동일한 흐름):
  09:30 스크리닝 → [1]번 종목 선택 → 목표가 체결 → 트레일링스탑/손절/강제청산
  → 재스크리닝(당일 잔여 후보) → 반복 → 15:20 강제 청산
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest.data_loader     import fetch_multi_ohlcv
from backtest.data_loader_yf  import fetch_multi_minute_bars_yf
from backtest.engine          import run_backtest as _run_engine
from backtest.engine_intraday import run_intraday_backtest
from backtest.report          import print_report, _calc_mdd
import strategy_config as sc


def run_backtest_menu():
    print()
    print("=" * 50)
    print("       백테스팅 설정")
    print("=" * 50)

    # ── 1. 유형 먼저 선택 ──
    print("  백테스팅 유형:")
    print("  [1] 단타 하루치  — 분봉 기반 (최근 30일 이내)")
    print("  [2] 다일 백테스트 — 일봉 기반, 장기 전략 검증")
    bt_type = input("\n  선택 >> ").strip()
    if bt_type not in ("1", "2"):
        print("  잘못된 입력입니다.")
        return

    # ── 2. 날짜 입력 (유형에 따라 다름) ──
    print()
    if bt_type == "1":
        date = input("  날짜 (YYYYMMDD, 최근 30일 이내): ").strip()
        if not date:
            print("  날짜를 입력하세요.")
            return
        start_date = end_date = date
    else:
        print("  ※ 권장 기간: 최소 1개월 / 권장 6개월 / 이상적 1~3년")
        start_date = input("  시작일 (YYYYMMDD): ").strip()
        end_date   = input("  종료일 (YYYYMMDD): ").strip()
        if not (start_date and end_date) or start_date >= end_date:
            print("  날짜 입력이 올바르지 않습니다.")
            return

    # ── 3. 초기 자금 ──
    try:
        capital_str     = input("  초기 자금 (기본 1,000,000): ").strip()
        initial_capital = int(capital_str) if capital_str else 1_000_000
    except ValueError:
        print("  기본값(1,000,000원)으로 진행합니다.")
        initial_capital = 1_000_000

    # ── 4. 종목 풀 ──
    print()
    print("  스크리닝 종목 풀:")
    print(f"  [1] 코스피200 상위 {sc.KOSPI_POOL_SIZE}개  (strategy_config.py → KOSPI_POOL_SIZE)")
    print("  [2] 관심종목 (watchlist.py)")
    print("  [3] 직접 입력 (콤마로 구분, 예: 005930,000660)")
    pool_choice = input("\n  선택 >> ").strip()

    stock_list = _build_stock_list(pool_choice)
    if not stock_list:
        print("  종목 목록을 구성하지 못했습니다.")
        return

    print()
    print("  현재 전략 파라미터:")
    sc.print_config()
    print()

    # ── 5. 실행 ──
    if bt_type == "1":
        _run_intraday(stock_list, date, initial_capital)
    else:
        print("  실행 모드:")
        print("  [1] 현재 파라미터로 실행")
        print("  [2] K값 최적화 (0.3 ~ 0.7 스캔)")
        mode = input("\n  선택 >> ").strip()

        print()
        all_data = fetch_multi_ohlcv(stock_list, start_date, end_date)
        if not all_data:
            print("  수집된 데이터가 없습니다. 날짜나 종목 풀을 확인하세요.")
            return

        if mode == "2":
            _run_optimization(all_data, stock_list, start_date, end_date, initial_capital)
        else:
            _run_single(all_data, stock_list, start_date, end_date, initial_capital)


# ──────────────────────────────────────────
# 실행 모드
# ──────────────────────────────────────────

def _run_intraday(stock_list, date, initial_capital):
    """분봉 기반 하루치 단타 백테스트"""
    from backtest.data_loader import fetch_multi_ohlcv

    # 분봉 수집 (yfinance: 7일 이내 1분봉 / 60일 이내 5분봉)
    actual_date, minute_data = fetch_multi_minute_bars_yf(stock_list, date)
    if not minute_data:
        print("  분봉 데이터를 수집하지 못했습니다.")
        print("  ※ 1분봉: 최근 7일 이내 / 5분봉: 최근 60일 이내만 가능합니다.")
        return

    # 전일 데이터 필요 (목표가 계산용)
    from datetime import datetime, timedelta
    fetch_from = (datetime.strptime(actual_date, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
    daily_data = fetch_multi_ohlcv(stock_list, fetch_from, actual_date)

    print("\n  백테스팅 실행 중...")
    result = run_intraday_backtest(minute_data, daily_data, stock_list, actual_date, initial_capital)

    _print_intraday_report(result, len(stock_list))


def _print_intraday_report(result, pool_size):
    trades          = result["trades"]
    initial_capital = result["initial_capital"]
    final_capital   = result["final_capital"]
    date            = result["date"]

    total_return = (final_capital - initial_capital) / initial_capital * 100

    print()
    print("=" * 50)
    print("  단타 백테스팅 결과  [분봉 기반]")
    print("=" * 50)
    print(f"  날짜          : {date}")
    print(f"  스크리닝 풀   : {pool_size}개 종목")
    print(f"  ────────────────────────────────────────────────")
    print(f"  초기 자금     : {initial_capital:>15,}원")
    print(f"  최종 자산     : {int(final_capital):>15,}원")
    print(f"  수익률        : {total_return:>+14.2f}%")
    print(f"  총 거래 횟수  : {len(trades)}회")

    if trades:
        print(f"  ────────────────────────────────────────────────")
        print(f"  거래 내역:")
        print(f"  {'진입':>6}  {'청산':>6}  {'종목':<10}  {'매수가':>8}  {'매도가':>8}  {'수익률':>8}  사유")
        print(f"  {'-'*64}")
        for t in trades:
            entry = t["entry_time"][:2] + ":" + t["entry_time"][2:4]
            exit_ = t["exit_time"][:2]  + ":" + t["exit_time"][2:4]
            print(
                f"  {entry:>6}  {exit_:>6}  {t['name']:<10}  "
                f"{t['buy_price']:>8,}  {t['sell_price']:>8,}  "
                f"{t['pnl_rate']*100:>+7.2f}%  {t['reason']}"
            )
    else:
        print(f"\n  이 날 조건 충족 매매 없음")
        print(f"  → 변동성 돌파 종목이 없거나 AD Line 조건 불충족")

    print("=" * 50)

    # 상세 타임라인 출력 여부 질문
    show = input("\n  분봉 타임라인 출력? (y/N): ").strip().lower()
    if show == "y":
        print()
        for line in result["timeline"]:
            print(f"    {line}")
    print()


def _run_single(all_data, stock_list, start_date, end_date, initial_capital):
    print("\n  백테스팅 실행 중...")
    result = _run_engine(all_data, stock_list, start_date, end_date, initial_capital)

    if not result["trades"]:
        print("  [결과] 조건 충족 거래 없음 — 기간이나 파라미터를 조정해보세요.")
        return

    print_report(result, start_date, end_date, len(stock_list))


def _run_optimization(all_data, stock_list, start_date, end_date, initial_capital):
    print("\n  K값 최적화 스캔 중...\n")

    original_k = sc.K
    best       = {"k": original_k, "return": float("-inf"), "result": None}
    k_range    = [round(k * 0.1, 1) for k in range(3, 8)]  # 0.3 ~ 0.7

    print(f"  {'K값':>6}  {'수익률':>10}  {'거래수':>6}  {'승률':>8}  {'MDD':>8}")
    print(f"  {'-'*48}")

    for k in k_range:
        sc.K   = k
        result = _run_engine(all_data, stock_list, start_date, end_date, initial_capital)
        trades     = result["trades"]
        total_ret  = (result["final_capital"] - initial_capital) / initial_capital * 100
        win_rate   = len([t for t in trades if t["pnl_rate"] > 0]) / len(trades) * 100 if trades else 0
        mdd        = _calc_mdd(result["equity_curve"])

        flag = " ◀" if total_ret > best["return"] else ""
        print(f"  {k:>6.1f}  {total_ret:>+9.2f}%  {len(trades):>6}  {win_rate:>7.1f}%  {mdd:>+7.2f}%{flag}")

        if total_ret > best["return"]:
            best = {"k": k, "return": total_ret, "result": result}

    sc.K = original_k  # 원복

    print(f"\n  최적 K값: {best['k']}  (수익률: {best['return']:+.2f}%)")
    if best["result"] and best["result"]["trades"]:
        print_report(best["result"], start_date, end_date, len(stock_list))


# ──────────────────────────────────────────
# 종목 풀 구성
# ──────────────────────────────────────────

def _build_stock_list(choice):
    if choice == "1":
        from screener import build_screening_pool
        return build_screening_pool()

    if choice == "2":
        from watchlist import WATCHLIST_CODES
        from screener import KOSPI_200
        kospi_map = {s["code"]: s["name"] for s in KOSPI_200}
        return [{"code": c, "name": kospi_map.get(c, c)} for c in WATCHLIST_CODES]

    if choice == "3":
        raw = input("  종목 코드 입력 : ").strip()
        codes = [c.strip() for c in raw.split(",") if c.strip()]
        if not codes:
            return []
        return [{"code": c, "name": c} for c in codes]

    return []
