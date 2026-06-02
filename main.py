from scheduler import run_scheduler
from screener import run_screening
from strategy_config import print_config

def main():
    print("=" * 40)
    print("   KIS 자동매매 봇 시작")
    print("=" * 40)

    print_config()

    print("\n실행 모드를 선택하세요:")
    print("  1. 정식 실행 (장 시작 대기 후 자동매매)")
    print("  2. 스크리닝만 테스트 (매매 없이 종목만 확인)")
    print("  3. 종료")

    choice = input("\n선택 (1/2/3): ").strip()

    if choice == "1":
        run_scheduler()
    elif choice == "2":
        results = run_screening()
        if results:
            print(f"\n총 {len(results)}개 종목이 조건을 충족했습니다.")
    elif choice == "3":
        print("종료합니다.")
    else:
        print("잘못된 입력입니다.")

if __name__ == "__main__":
    main()