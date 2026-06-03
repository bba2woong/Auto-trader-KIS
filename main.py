import os


def _print_header():
    print("=" * 46)
    print("      Auto Stock Trading System")
    print("=" * 46)
    print("  실행 모드를 선택하세요:\n")
    print("  [1] 모의투자  (Mock Trading)")
    print("  [2] 실전투자  (Live Trading)")
    print("  [3] 백테스팅  (Backtesting)")
    print("  [0] 종료")


def _start_trading(mode):
    os.environ["TRADING_MODE"] = mode
    # config 이전에 TRADING_MODE를 설정해야 올바른 키를 로드하므로 지연 import
    from scheduler import run_scheduler
    from strategy_config import print_config
    print_config()
    run_scheduler()


def _run_screening():
    os.environ.setdefault("TRADING_MODE", "mock")
    from screener import run_screening
    results = run_screening()
    if results:
        print(f"\n총 {len(results)}개 종목이 조건을 충족했습니다.")


def main():
    _print_header()

    choice = input("\n  선택 >> ").strip()

    if choice == "1":
        _start_trading("mock")
    elif choice == "2":
        confirm = input("\n  ⚠️  실전투자를 시작합니다. 계속하시겠습니까? (y/N): ").strip().lower()
        if confirm == "y":
            _start_trading("real")
        else:
            print("  취소되었습니다.")
    elif choice == "3":
        os.environ.setdefault("TRADING_MODE", "mock")
        from backtest.backtest import run_backtest_menu
        run_backtest_menu()
    elif choice == "0":
        print("  종료합니다.")
    else:
        print("  잘못된 입력입니다.")


if __name__ == "__main__":
    main()
