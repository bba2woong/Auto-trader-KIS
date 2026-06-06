import requests
import urllib3
import time
import config
from auth import get_access_token

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    url = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
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

def get_balance(max_retries=5):
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

        if res.status_code == 200:
            data = res.json()
            if data["rt_cd"] == "0":
                return {
                    "보유종목": data["output1"],
                    "계좌요약": data["output2"]
                }
            # Rate Limit 오류(EGW00201)는 재시도
            if "EGW00201" in data.get("msg_cd", ""):
                wait = 1.0 * (attempt + 1)
                print(f"  [잔고조회] Rate Limit — {wait:.0f}초 후 재시도 ({attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise Exception(f"잔고조회 오류: {data['msg1']}")

        # 500 서버 에러도 재시도
        wait = 1.0 * (attempt + 1)
        print(f"  [잔고조회] {res.status_code} 오류 — {wait:.0f}초 후 재시도 ({attempt+1}/{max_retries})")
        time.sleep(wait)

    raise Exception(f"잔고조회 실패: {max_retries}회 재시도 초과")