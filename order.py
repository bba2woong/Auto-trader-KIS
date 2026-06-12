import requests
import urllib3
import config
from auth import get_access_token

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_trade_headers(tr_id):
    token = get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }

def buy_stock(stock_code, quantity):
    """시장가 매수 주문"""
    url = f"{config.TRD_URL}/uapi/domestic-stock/v1/trading/order-cash"

    # 모의/실전 tr_id 분기
    tr_id = "VTTC0802U" if config.MODE == "mock" else "TTTC0802U"
    headers = get_trade_headers(tr_id)

    account_no   = config.ACCOUNT.replace("-", "")[:8]
    product_code = config.ACCOUNT.replace("-", "")[8:] or "01"

    body = {
        "CANO": account_no,
        "ACNT_PRDT_CD": product_code,
        "PDNO": stock_code,          # 종목코드
        "ORD_DVSN": "01",            # 01: 시장가
        "ORD_QTY": str(quantity),    # 주문 수량
        "ORD_UNPR": "0",             # 시장가는 0
    }

    res = requests.post(url, headers=headers, json=body, verify=False)

    if res.status_code != 200:
        print(f"  [매수 에러] {res.text}")
        res.raise_for_status()

    data = res.json()

    if data["rt_cd"] != "0":
        raise Exception(f"매수 주문 실패: {data['msg1']}")

    order_no = data["output"]["ODNO"]
    print(f"  [매수 완료] 종목: {stock_code} | 수량: {quantity}주 | 주문번호: {order_no}")
    from api import invalidate_balance_cache
    invalidate_balance_cache()
    return order_no


def sell_stock(stock_code, quantity):
    """시장가 매도 주문"""
    url = f"{config.TRD_URL}/uapi/domestic-stock/v1/trading/order-cash"

    # 모의/실전 tr_id 분기
    tr_id = "VTTC0801U" if config.MODE == "mock" else "TTTC0801U"
    headers = get_trade_headers(tr_id)

    account_no   = config.ACCOUNT.replace("-", "")[:8]
    product_code = config.ACCOUNT.replace("-", "")[8:] or "01"

    body = {
        "CANO": account_no,
        "ACNT_PRDT_CD": product_code,
        "PDNO": stock_code,
        "ORD_DVSN": "01",            # 01: 시장가
        "ORD_QTY": str(quantity),
        "ORD_UNPR": "0",
    }

    res = requests.post(url, headers=headers, json=body, verify=False)

    if res.status_code != 200:
        print(f"  [매도 에러] {res.text}")
        res.raise_for_status()

    data = res.json()

    if data["rt_cd"] != "0":
        raise Exception(f"매도 주문 실패: {data['msg1']}")

    order_no = data["output"]["ODNO"]
    print(f"  [매도 완료] 종목: {stock_code} | 수량: {quantity}주 | 주문번호: {order_no}")
    from api import invalidate_balance_cache
    invalidate_balance_cache()
    return order_no


def get_holding_quantity(stock_code):
    """특정 종목 보유 수량 조회 (캐시 사용 — API 호출 최소화)"""
    from api import get_balance_cached
    balance = get_balance_cached()
    for item in balance["보유종목"]:
        if item["pdno"] == stock_code:
            return int(item["hldg_qty"])
    return 0


def test_order():
    """주문 테스트 (소량으로 매수 → 즉시 매도)"""
    TEST_STOCK = "005930"  # 삼성전자
    TEST_QTY   = 1         # 1주

    print("=== 주문 테스트 시작 ===\n")

    print("[1] 매수 주문")
    buy_stock(TEST_STOCK, TEST_QTY)

    import time
    print("\n  3초 대기 후 매도...")
    time.sleep(3)

    print("\n[2] 매도 주문")
    sell_stock(TEST_STOCK, TEST_QTY)

    print("\n=== 주문 테스트 완료 ===")


if __name__ == "__main__":
    test_order()