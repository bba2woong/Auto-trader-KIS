import requests
import urllib3
import time
from datetime import datetime
import config
from auth import get_access_token
import strategy_config as sc
from watchlist import WATCHLIST

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------------------------------------------------------
# 코스피 200 고정 리스트 (시가총액 상위)
# ----------------------------------------------------------------
KOSPI_200 = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "207940", "name": "삼성바이오로직스"},
    {"code": "005935", "name": "삼성전자우"},
    {"code": "373220", "name": "LG에너지솔루션"},
    {"code": "000270", "name": "기아"},
    {"code": "005380", "name": "현대차"},
    {"code": "068270", "name": "셀트리온"},
    {"code": "105560", "name": "KB금융"},
    {"code": "055550", "name": "신한지주"},
    {"code": "035420", "name": "NAVER"},
    {"code": "003550", "name": "LG"},
    {"code": "012330", "name": "현대모비스"},
    {"code": "035720", "name": "카카오"},
    {"code": "051910", "name": "LG화학"},
    {"code": "028260", "name": "삼성물산"},
    {"code": "066570", "name": "LG전자"},
    {"code": "032830", "name": "삼성생명"},
    {"code": "086790", "name": "하나금융지주"},
    {"code": "003490", "name": "대한항공"},
    {"code": "034730", "name": "SK"},
    {"code": "017670", "name": "SK텔레콤"},
    {"code": "011200", "name": "HMM"},
    {"code": "018260", "name": "삼성에스디에스"},
    {"code": "009150", "name": "삼성전기"},
    {"code": "010950", "name": "S-Oil"},
    {"code": "096770", "name": "SK이노베이션"},
    {"code": "033780", "name": "KT&G"},
    {"code": "015760", "name": "한국전력"},
    {"code": "030200", "name": "KT"},
    {"code": "011070", "name": "LG이노텍"},
    {"code": "009830", "name": "한화솔루션"},
    {"code": "000810", "name": "삼성화재"},
    {"code": "010130", "name": "고려아연"},
    {"code": "047050", "name": "포스코인터내셔널"},
    {"code": "316140", "name": "우리금융지주"},
    {"code": "032640", "name": "LG유플러스"},
    {"code": "024110", "name": "기업은행"},
    {"code": "138040", "name": "메리츠금융지주"},
    {"code": "003670", "name": "포스코퓨처엠"},
    {"code": "004020", "name": "현대제철"},
    {"code": "000100", "name": "유한양행"},
    {"code": "042660", "name": "한화오션"},
    {"code": "009540", "name": "HD한국조선해양"},
    {"code": "267250", "name": "HD현대"},
    {"code": "329180", "name": "HD현대중공업"},
    {"code": "011790", "name": "SKC"},
    {"code": "006400", "name": "삼성SDI"},
    {"code": "001570", "name": "금양"},
    {"code": "000720", "name": "현대건설"},
]

def get_headers(tr_id):
    token = get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": tr_id,
    }

def request_with_retry(url, headers, params, max_retries=3, delay=0.5):
    """500 에러 시 재시도하는 요청 헬퍼"""
    for attempt in range(max_retries):
        try:
            res = requests.get(url, headers=headers, params=params, verify=False)
            if res.status_code == 200:
                return res
            # 500 등 서버 에러면 잠시 후 재시도
            time.sleep(delay * (attempt + 1))  # 점점 더 길게 대기
        except Exception:
            time.sleep(delay * (attempt + 1))
    return None  # 모든 재시도 실패

def get_daily_data(stock_code):
    """일봉 데이터 조회 (전일 고가/저가/종가 + AD Line 계산용)"""
    url = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    headers = get_headers("FHKST01010400")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    res = request_with_retry(url, headers, params)  # ← 재시도 적용
    if res is None:
        return None

    data = res.json()
    if data["rt_cd"] != "0":
        return None

    return data["output"]

def get_current_price_simple(stock_code):
    """현재가 + 시가 간단 조회"""
    url = f"{config.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = get_headers("FHKST01010100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }
    res = request_with_retry(url, headers, params)  # ← 재시도 적용
    if res is None:
        return None

    data = res.json()
    if data["rt_cd"] != "0":
        return None

    output = data["output"]
    return {
        "현재가": int(output["stck_prpr"]),
        "시가":   int(output["stck_oprc"]),
        "고가":   int(output["stck_hgpr"]),
        "저가":   int(output["stck_lwpr"]),
        "거래량": int(output["acml_vol"]),
    }
    
def calc_ad_line(daily_data, periods=5):
    """
    AD Line 계산 (최근 N일 누적)
    AD = ((종가-저가) - (고가-종가)) / (고가-저가) × 거래량
    """
    ad_values = []
    for day in daily_data[:periods]:
        high  = int(day["stck_hgpr"])
        low   = int(day["stck_lwpr"])
        close = int(day["stck_clpr"])
        vol   = int(day["acml_vol"])

        if high == low:
            ad_values.append(0)
            continue

        ad = ((close - low) - (high - close)) / (high - low) * vol
        ad_values.append(ad)

    # AD Line = 누적합
    ad_line = []
    cumsum = 0
    for v in reversed(ad_values):  # 오래된 것부터 누적
        cumsum += v
        ad_line.append(cumsum)

    # 최근값이 이전값보다 높으면 상승 중
    if len(ad_line) >= 2:
        return ad_line[-1] > ad_line[-2]  # True = 상승
    return False

def check_volatility_breakout(stock_code):
    """
    변동성 돌파 조건 체크
    목표가 = 시가 + (전일 고가 - 전일 저가) × K
    """
    try:
        daily = get_daily_data(stock_code)
        if not daily or len(daily) < 2:
            return None

        current = get_current_price_simple(stock_code)
        if not current:
            return None

        prev_high = int(daily[1]["stck_hgpr"])
        prev_low  = int(daily[1]["stck_lwpr"])
        range_    = prev_high - prev_low
        target    = current["시가"] + (range_ * sc.K)

        volatility_ok = current["현재가"] >= target
        ad_rising     = calc_ad_line(daily)

        return {
            "code":           stock_code,
            "현재가":         current["현재가"],
            "시가":           current["시가"],
            "목표가":         int(target),
            "전일변동폭":     range_,
            "변동성돌파":     volatility_ok,
            "AD상승":         ad_rising,
            "돌파여유율":     (current["현재가"] - target) / target * 100 if target > 0 else 0,
        }

    except Exception as e:
        print(f"\n  [오류] {stock_code}: {e}")  # 디버그용
        return None

def build_screening_pool():
    """코스피200 + 관심종목 합치기 (중복 제거)"""
    pool = {s["code"]: s for s in KOSPI_200}
    for s in WATCHLIST:
        pool[s["code"]] = s  # 중복이면 덮어씀 (관심종목 우선)
    result = list(pool.values())
    print(f"  스크리닝 풀: 코스피200({len(KOSPI_200)}개) + 관심종목({len(WATCHLIST)}개) = 총 {len(result)}개 (중복 제거)")
    return result

def run_screening():
    """
    전체 스크리닝 실행
    → 변동성 돌파 + AD Line 상승 종목 반환
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 스크리닝 시작...")
    pool     = build_screening_pool()
    passed   = []
    failed   = []

    for i, stock in enumerate(pool):
        print(f"  [{i+1}/{len(pool)}] {stock['name']} 체크 중...", end="\r")
        result = check_volatility_breakout(stock["code"])

        if result is None:
            failed.append(stock["code"])
            time.sleep(0.5)  # API 호출 간격
            continue

        if result["변동성돌파"] and result["AD상승"] and result["돌파여유율"] <= sc.MAX_BREAKOUT_GAP:
            passed.append({
                "code":       stock["code"],
                "name":       stock["name"],
                "현재가":     result["현재가"],
                "목표가":     result["목표가"],
                "돌파여유율": result["돌파여유율"],
            })

        time.sleep(0.5)  # API 호출 제한 방지

    # 돌파 여유율 낮은 순 정렬 (방금 막 돌파한 종목 우선)
    passed.sort(key=lambda x: x["돌파여유율"])

    print(f"\n[스크리닝 완료]")
    print(f"  전체: {len(pool)}개 | 통과: {len(passed)}개 | 오류: {len(failed)}개")

    if passed:
        print(f"\n  ✅ 조건 충족 종목:")
        for s in passed:
            print(f"    - {s['name']} ({s['code']}) | 현재가: {s['현재가']:,}원 | 목표가: {s['목표가']:,}원")
    else:
        print(f"  ❌ 조건 충족 종목 없음")

        # strategy_config 자동 업데이트
    sc.update_candidates(passed)

    return passed

if __name__ == "__main__":
    # 스크리닝 단독 테스트
    results = run_screening()