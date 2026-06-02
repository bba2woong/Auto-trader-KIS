import requests
import urllib3
from datetime import datetime, timedelta
import config
from auth import get_access_token
import strategy_config as sc

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_headers():
    token = get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": "FHKST01010100",
    }

def get_current_price(stock_code):
    """현재가 조회"""
    url = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = get_headers()
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }
    res = requests.get(url, headers=headers, params=params, verify=False)
    res.raise_for_status()
    data = res.json()

    if data["rt_cd"] != "0":
        raise Exception(f"현재가 조회 실패: {data['msg1']}")

    output = data["output"]
    return {
        "현재가": int(output["stck_prpr"]),
        "시가":   int(output["stck_oprc"]),
        "전일고가": int(output["stck_hgpr"]),  # 당일 고가 (장중) — 전일은 별도 조회
        "전일저가": int(output["stck_lwpr"]),
    }

def get_prev_day_data(stock_code):
    """전일 고가/저가 조회 (변동성 계산용)"""
    url = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    token = get_access_token()
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": "FHKST01010400",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_PERIOD_DIV_CODE": "D",   # 일봉
        "FID_ORG_ADJ_PRC": "0",
    }
    res = requests.get(url, headers=headers, params=params, verify=False)
    res.raise_for_status()
    data = res.json()

    if data["rt_cd"] != "0":
        raise Exception(f"전일 데이터 조회 실패: {data['msg1']}")

    # output[0] = 당일, output[1] = 전일
    prev = data["output"][1]
    return {
        "전일고가": int(prev["stck_hgpr"]),
        "전일저가": int(prev["stck_lwpr"]),
        "전일종가": int(prev["stck_clpr"]),
    }

def calc_target_price(stock_code):
    """변동성 돌파 목표가 계산"""
    prev   = get_prev_day_data(stock_code)
    price  = get_current_price(stock_code)

    range_ = prev["전일고가"] - prev["전일저가"]   # 전일 변동폭
    target = price["시가"] + (range_ * sc.K)       # 목표 돌파가

    print(f"  전일 고가  : {prev['전일고가']:,}원")
    print(f"  전일 저가  : {prev['전일저가']:,}원")
    print(f"  전일 변동폭: {range_:,}원")
    print(f"  오늘 시가  : {price['시가']:,}원")
    print(f"  목표 돌파가: {target:,.0f}원  (시가 + 변동폭 × {sc.K})")

    return int(target)

def calc_quantity(current_price):
    """매수 수량 계산 (예수금 × 투자비율 / 현재가)"""
    from api import get_balance
    balance  = get_balance()
    deposit  = int(balance["계좌요약"][0]["dnca_tot_amt"])  # 예수금
    invest   = int(deposit * sc.INVEST_RATIO)
    quantity = invest // current_price

    print(f"  예수금     : {deposit:,}원")
    print(f"  투자금액   : {invest:,}원 ({int(sc.INVEST_RATIO*100)}%)")
    print(f"  매수 수량  : {quantity}주 (@ {current_price:,}원)")

    return quantity

def is_market_open():
    """현재 장 중인지 확인"""
    now  = datetime.now().strftime("%H:%M")
    return sc.MARKET_OPEN <= now <= sc.MARKET_CLOSE

def is_force_sell_time():
    """강제 청산 시간인지 확인"""
    now = datetime.now().strftime("%H:%M")
    return now >= sc.FORCE_SELL_TIME

def check_profit_loss(buy_price, current_price):
    """익절/손절 조건 체크"""
    rate = (current_price - buy_price) / buy_price

    if rate >= sc.PROFIT_RATE:
        return "익절", rate
    elif rate <= -sc.LOSS_RATE:
        return "손절", rate
    else:
        return None, rate