import requests
import urllib3
import time
import threading
import config
from auth import get_access_token

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 잔고 공유 캐시 (30초) ────────────────────────────────────────────
# 여러 포지션 스레드가 동시에 get_balance()를 호출하면 500 오류 폭증.
# 30초 이내 재호출은 캐시를 반환해 API 호출 횟수를 최소화한다.
_balance_cache      = None
_balance_cache_ts   = 0.0
_balance_cache_ttl  = 30.0   # 초
_balance_cache_lock = threading.Lock()


def get_balance_cached():
    """잔고 캐시 조회 (30초 TTL). HTS 수동매도 감지 등 빈번한 호출에 사용."""
    global _balance_cache, _balance_cache_ts
    with _balance_cache_lock:
        if _balance_cache is not None and time.time() - _balance_cache_ts < _balance_cache_ttl:
            return _balance_cache
    result = get_balance()
    with _balance_cache_lock:
        _balance_cache    = result
        _balance_cache_ts = time.time()
    return result


def invalidate_balance_cache():
    """매수/매도 직후 캐시 강제 만료"""
    global _balance_cache
    with _balance_cache_lock:
        _balance_cache = None

def get_headers(tr_id):
    token = get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": tr_id,
    }

def get_stock_price(stock_code):
    """주식 현재가 조회"""
    url = f"{config.QUERY_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = get_headers("FHKST01010100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }

    res = requests.get(url, headers=headers, params=params, verify=False)  # ← 추가
    res.raise_for_status()
    data = res.json()

    if data["rt_cd"] != "0":
        raise Exception(f"API 오류: {data['msg1']}")

    output = data["output"]
    return {
        "종목코드": stock_code,
        "현재가": int(output["stck_prpr"]),
        "시가": int(output["stck_oprc"]),
        "고가": int(output["stck_hgpr"]),
        "저가": int(output["stck_lwpr"]),
        "거래량": int(output["acml_vol"]),
        "등락률": float(output["prdy_ctrt"]),
    }

def get_balance(max_retries=15):
    """주식 잔고 조회 (Rate Limit 초과 시 최대 max_retries회 재시도)"""
    url = f"{config.TRD_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    tr_id = "VTTC8434R" if config.MODE == "mock" else "TTTC8434R"

    account_no   = config.ACCOUNT.replace("-", "")[:8]
    product_code = config.ACCOUNT.replace("-", "")[8:] or "01"

    params = {
        "CANO": account_no,
        "ACNT_PRDT_CD": product_code,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    for attempt in range(max_retries):
        headers = get_headers(tr_id)
        headers["custtype"] = "P"
        res = requests.get(url, headers=headers, params=params, verify=False)

        try:
            data   = res.json()
            msg_cd = data.get("msg_cd", "")
        except Exception:
            data   = {}
            msg_cd = ""

        if msg_cd == "EGW00123":   # 토큰 만료 (HTTP 500으로 옴)
            from auth import invalidate_token
            invalidate_token()
            headers = get_headers(tr_id)
            headers["custtype"] = "P"
            print(f"  [잔고조회] 토큰 만료 — 재발급 후 재시도 ({attempt+1}/{max_retries})")
            continue
        if msg_cd == "EGW00201":   # Rate Limit
            wait = 2.0 + attempt * 1.5   # 2, 3.5, 5, 6.5, 8 ... 초
            print(f"  [잔고조회] Rate Limit — {wait:.1f}초 후 재시도 ({attempt+1}/{max_retries})")
            time.sleep(wait)
            continue
        if res.status_code == 200:
            if data.get("rt_cd") == "0":
                return {
                    "보유종목": data["output1"],
                    "계좌요약": data["output2"]
                }
            raise Exception(f"잔고조회 오류: {data.get('msg1','')}")

        # 그 외 HTTP 오류
        wait = 1.0 * (attempt + 1)
        print(f"  [잔고조회] {res.status_code} 오류 — {wait:.0f}초 후 재시도 ({attempt+1}/{max_retries})")
        time.sleep(wait)

    raise Exception(f"잔고조회 실패: {max_retries}회 재시도 초과")


def get_max_order_qty(stock_code: str, price: int) -> int:
    """
    특정 종목 현재가 기준 최대 주문 가능 수량 조회.
    KIS TR: VTTC8908R (모의) / TTTC8908R (실전)
    반환: 최대 매수 가능 수량 (int), 조회 실패 시 0
    """
    url   = f"{config.TRD_URL}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    tr_id = "VTTC8908R" if config.MODE == "mock" else "TTTC8908R"

    account_no   = config.ACCOUNT.replace("-", "")[:8]
    product_code = config.ACCOUNT.replace("-", "")[8:] or "01"

    params = {
        "CANO":         account_no,
        "ACNT_PRDT_CD": product_code,
        "PDNO":         stock_code,
        "ORD_UNPR":     str(price),
        "ORD_DVSN":     "01",   # 시장가
        "CMA_EVLU_AMT_ICLD_YN": "N",
        "OVRS_ICLD_YN": "N",
    }

    try:
        headers = get_headers(tr_id)
        headers["custtype"] = "P"
        res  = requests.get(url, headers=headers, params=params, verify=False)
        data = res.json()
        if data.get("rt_cd") == "0":
            qty = int(data["output"].get("max_buy_qty", 0))
            return qty
        print(f"  [최대주문수량] API 오류: {data.get('msg1','')}")
        return 0
    except Exception as e:
        print(f"  [최대주문수량] 조회 실패: {e}")
        return 0