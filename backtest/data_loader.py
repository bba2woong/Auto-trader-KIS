"""
과거 OHLCV 데이터 수집
- fetch_ohlcv(code, start, end)         : 일봉, 단일 종목
- fetch_multi_ohlcv(stocks, start, end) : 일봉, 다종목 → {code: {date: row}}
- fetch_minute_bars(code, date)         : 분봉, 단일 종목 하루치 → [{"time","open","high","low","close","volume"}, ...]
- fetch_multi_minute_bars(stocks, date) : 분봉, 다종목 → {code: [bars]}
"""
import requests
import urllib3
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from auth import get_access_token

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _headers():
    token = get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": "FHKST03010100",
    }


def fetch_ohlcv(stock_code, start_date, end_date):
    """
    일봉 OHLCV 수집 (KIS 주식 일봉차트조회)
    반환: [{"date","open","high","low","close","volume"}, ...] 날짜 오름차순
    """
    url      = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    all_rows = []
    page_end = end_date

    while True:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":         stock_code,
            "FID_INPUT_DATE_1":       start_date,
            "FID_INPUT_DATE_2":       page_end,
            "FID_PERIOD_DIV_CODE":    "D",
            "FID_ORG_ADJ_PRC":        "0",
        }
        res  = requests.get(url, headers=_headers(), params=params, verify=False)
        res.raise_for_status()
        data = res.json()

        if data["rt_cd"] != "0":
            raise Exception(f"조회 실패: {data['msg1']}")

        rows = data.get("output2") or []
        if not rows:
            break

        for row in rows:
            d = row["stck_bsop_date"]
            if d < start_date:
                continue
            all_rows.append({
                "date":   d,
                "open":   int(row["stck_oprc"]),
                "high":   int(row["stck_hgpr"]),
                "low":    int(row["stck_lwpr"]),
                "close":  int(row["stck_clpr"]),
                "volume": int(row["acml_vol"]),
            })

        oldest = rows[-1]["stck_bsop_date"]
        if len(rows) < 100 or oldest <= start_date:
            break

        page_end = oldest
        time.sleep(0.3)

    # 중복 제거 + 오름차순
    seen, unique = set(), []
    for r in all_rows:
        if r["date"] not in seen:
            seen.add(r["date"])
            unique.append(r)
    unique.sort(key=lambda x: x["date"])
    return unique


def fetch_multi_ohlcv(stock_list, start_date, end_date, progress_cb=None):
    """
    다종목 OHLCV 수집
    stock_list  : [{"code": ..., "name": ...}, ...]
    progress_cb : (current, total, name) → None  (UI 진행률 콜백, 선택)
    반환        : {code: {date: ohlcv_row}}
    """
    from datetime import datetime, timedelta
    fetch_from = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")

    result  = {}
    total   = len(stock_list)
    success = 0

    print(f"\n  종목 데이터 수집: 총 {total}개")
    for i, stock in enumerate(stock_list):
        code = stock["code"]
        name = stock["name"]
        print(f"  [{i+1:>3}/{total}] {name} ({code}) 수집 중...", end="\r")
        if progress_cb:
            progress_cb(i + 1, total, name)
        try:
            rows = fetch_ohlcv(code, fetch_from, end_date)
            if rows:
                result[code] = {r["date"]: r for r in rows}
                success += 1
        except Exception:
            pass
        time.sleep(0.3)

    print(f"\n  수집 완료: {success}/{total}개 성공")
    return result


# ──────────────────────────────────────────
# 분봉 데이터
# ──────────────────────────────────────────

def _minute_headers():
    token = get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": "FHKST03010200",
    }


def fetch_minute_bars(stock_code, date):
    """
    특정 날짜의 1분봉 데이터 수집 (KIS 주식 분봉차트조회)
    date   : "YYYYMMDD" (비거래일 입력 시 직전 거래일 데이터로 자동 보정)
    반환   : (actual_date, bars)
             actual_date : 실제 수집된 거래일 ("YYYYMMDD")
             bars        : [{"time","open","high","low","close","volume"}, ...] 시간 오름차순
    """
    url       = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    all_bars  = []
    page_time = "153000"
    actual_date = None  # API가 실제로 반환한 날짜 (첫 row에서 확정)

    while True:
        params = {
            "FID_ETC_CLS_CODE":       "0",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":         stock_code,
            "FID_INPUT_HOUR_1":       page_time,
            "FID_PW_DATA_INCU_YN":    "Y",
        }
        res  = requests.get(url, headers=_minute_headers(), params=params, verify=False)
        res.raise_for_status()
        data = res.json()

        if data["rt_cd"] != "0":
            break

        rows = data.get("output2") or []
        if not rows:
            break

        # 첫 row에서 실제 거래일 확정 (API가 비거래일 → 직전 거래일로 자동 보정)
        if actual_date is None:
            actual_date = rows[0].get("stck_bsop_date", date)

        for row in rows:
            bar_date = row.get("stck_bsop_date", "")
            # 확정된 거래일과 다른 날 데이터는 건너뜀 (전날 데이터 혼입 방지)
            if bar_date and bar_date != actual_date:
                continue
            all_bars.append({
                "time":   row["stck_cntg_hour"],
                "open":   int(row["stck_oprc"]),
                "high":   int(row["stck_hgpr"]),
                "low":    int(row["stck_lwpr"]),
                "close":  int(row["stck_prpr"]),
                "volume": int(row["cntg_vol"]),
            })

        oldest_time = rows[-1]["stck_cntg_hour"]
        oldest_date = rows[-1].get("stck_bsop_date", actual_date)

        # 다른 날짜로 넘어갔거나 장 시작 이전이면 종료
        if oldest_date != actual_date or oldest_time <= "090000":
            break

        page_time = oldest_time
        time.sleep(0.2)

    # 중복 제거 + 시간 오름차순
    seen, unique = set(), []
    for b in all_bars:
        if b["time"] not in seen:
            seen.add(b["time"])
            unique.append(b)
    unique.sort(key=lambda x: x["time"])
    return actual_date or date, unique


def fetch_multi_minute_bars(stock_list, date):
    """
    다종목 분봉 수집
    반환: (actual_date, {code: [bars]})
    actual_date : API가 실제 반환한 거래일 (비거래일 입력 시 자동 보정된 날짜)
    """
    result      = {}
    total       = len(stock_list)
    success     = 0
    actual_date = date  # 첫 성공 종목에서 확정

    print(f"\n  분봉 데이터 수집: {total}개 종목  요청 날짜: {date}")
    for i, stock in enumerate(stock_list):
        code = stock["code"]
        name = stock["name"]
        print(f"  [{i+1:>3}/{total}] {name} ({code}) ...", end="\r")
        try:
            returned_date, bars = fetch_minute_bars(code, date)
            if bars:
                result[code] = bars
                success += 1
                if success == 1:
                    actual_date = returned_date  # 실제 거래일 확정
        except Exception as e:
            if i == 0:
                print(f"\n  [오류] {name}: {e}")
        time.sleep(0.3)

    if actual_date != date:
        print(f"\n  ※ {date}은 비거래일 → 직전 거래일 {actual_date} 데이터로 자동 보정")
    print(f"  수집 완료: {success}/{total}개 성공")
    return actual_date, result
