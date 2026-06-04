"""
매수/매도 API 단순 테스트
종목 1주 매수 → 10초 보유 → 매도

실행: python test_trade.py
"""
import sys, os, time
os.environ.setdefault("TRADING_MODE", "mock")
sys.path.insert(0, ".")

TEST_STOCK = "005930"   # 삼성전자 (변경 가능)
TEST_QTY   = 1

def main():
    import config
    from strategy import get_current_price
    from order import buy_stock, sell_stock

    print("=" * 44)
    print(f"  매매 API 테스트")
    print(f"  모드  : {config.MODE.upper()}")
    print(f"  종목  : {TEST_STOCK}")
    print(f"  수량  : {TEST_QTY}주")
    print("=" * 44)

    # 현재가 조회
    print("\n[1] 현재가 조회...")
    try:
        info = get_current_price(TEST_STOCK)
        print(f"  현재가: {info['현재가']:,}원")
    except Exception as e:
        print(f"  ❌ 현재가 조회 실패: {e}")
        return

    # 매수
    print(f"\n[2] 매수 주문 ({TEST_QTY}주)...")
    try:
        order_no = buy_stock(TEST_STOCK, TEST_QTY)
        print(f"  ✅ 매수 성공 | 주문번호: {order_no}")
    except Exception as e:
        print(f"  ❌ 매수 실패: {e}")
        return

    # 10초 보유
    print(f"\n[3] 10초 보유 중...")
    for i in range(10, 0, -1):
        print(f"  {i}초 후 매도...", end="\r")
        time.sleep(1)

    # 현재가 재조회
    try:
        info = get_current_price(TEST_STOCK)
        print(f"\n  현재가: {info['현재가']:,}원")
    except Exception as e:
        print(f"\n  ⚠️ 현재가 재조회 실패 (매도는 계속): {e}")

    # 매도
    print(f"\n[4] 매도 주문 ({TEST_QTY}주)...")
    try:
        order_no = sell_stock(TEST_STOCK, TEST_QTY)
        print(f"  ✅ 매도 성공 | 주문번호: {order_no}")
    except Exception as e:
        print(f"  ❌ 매도 실패: {e}")
        return

    print("\n✅ 테스트 완료")

if __name__ == "__main__":
    main()
