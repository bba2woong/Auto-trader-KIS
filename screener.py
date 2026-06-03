import requests
import urllib3
import time
from datetime import datetime
import config
from auth import get_access_token
import strategy_config as sc
from watchlist import WATCHLIST_CODES

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------------------------------------------------------
# 코스피 200 전체 리스트 (시가총액 상위, 반기 리밸런싱 기준)
# ----------------------------------------------------------------
KOSPI_200 = [
    # ── 1~50 (초대형주) ──
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
    # ── 51~100 (대형주) ──
    {"code": "005490", "name": "POSCO홀딩스"},
    {"code": "051900", "name": "LG생활건강"},
    {"code": "090430", "name": "아모레퍼시픽"},
    {"code": "002790", "name": "아모레G"},
    {"code": "021240", "name": "코웨이"},
    {"code": "036570", "name": "엔씨소프트"},
    {"code": "251270", "name": "넷마블"},
    {"code": "259960", "name": "크래프톤"},
    {"code": "352820", "name": "하이브"},
    {"code": "323410", "name": "카카오뱅크"},
    {"code": "377300", "name": "카카오페이"},
    {"code": "293490", "name": "카카오게임즈"},
    {"code": "035760", "name": "CJ ENM"},
    {"code": "030000", "name": "제일기획"},
    {"code": "004370", "name": "농심"},
    {"code": "097950", "name": "CJ제일제당"},
    {"code": "271560", "name": "오리온"},
    {"code": "280360", "name": "롯데웰푸드"},
    {"code": "139480", "name": "이마트"},
    {"code": "023530", "name": "롯데쇼핑"},
    {"code": "004990", "name": "롯데지주"},
    {"code": "069960", "name": "현대백화점"},
    {"code": "004170", "name": "신세계"},
    {"code": "007070", "name": "GS리테일"},
    {"code": "282330", "name": "BGF리테일"},
    {"code": "001040", "name": "CJ"},
    {"code": "078930", "name": "GS"},
    {"code": "006360", "name": "GS건설"},
    {"code": "047040", "name": "대우건설"},
    {"code": "375500", "name": "DL이앤씨"},
    {"code": "034020", "name": "두산에너빌리티"},
    {"code": "000150", "name": "두산"},
    {"code": "180640", "name": "한진칼"},
    {"code": "002320", "name": "한진"},
    {"code": "000120", "name": "CJ대한통운"},
    {"code": "128940", "name": "한미약품"},
    {"code": "185750", "name": "종근당"},
    {"code": "069620", "name": "대웅제약"},
    {"code": "006280", "name": "GC녹십자"},
    {"code": "091990", "name": "셀트리온헬스케어"},
    {"code": "016360", "name": "삼성증권"},
    {"code": "006800", "name": "미래에셋증권"},
    {"code": "071050", "name": "한국금융지주"},
    {"code": "005940", "name": "NH투자증권"},
    {"code": "039490", "name": "키움증권"},
    {"code": "008560", "name": "메리츠증권"},
    {"code": "001450", "name": "현대해상"},
    {"code": "005830", "name": "DB손해보험"},
    {"code": "088350", "name": "한화생명"},
    {"code": "082640", "name": "동양생명"},
    # ── 101~150 (중대형주) ──
    {"code": "018880", "name": "한온시스템"},
    {"code": "204320", "name": "HL만도"},
    {"code": "011210", "name": "현대위아"},
    {"code": "012450", "name": "한화에어로스페이스"},
    {"code": "047810", "name": "한국항공우주"},
    {"code": "079550", "name": "LIG넥스원"},
    {"code": "011170", "name": "롯데케미칼"},
    {"code": "285130", "name": "SK케미칼"},
    {"code": "010060", "name": "OCI홀딩스"},
    {"code": "011780", "name": "금호석유"},
    {"code": "000880", "name": "한화"},
    {"code": "004800", "name": "효성"},
    {"code": "120110", "name": "코오롱인더"},
    {"code": "003240", "name": "태광산업"},
    {"code": "002380", "name": "KCC"},
    {"code": "014680", "name": "한솔케미칼"},
    {"code": "000990", "name": "DB하이텍"},
    {"code": "058470", "name": "리노공업"},
    {"code": "042700", "name": "한미반도체"},
    {"code": "039030", "name": "이오테크닉스"},
    {"code": "036930", "name": "주성엔지니어링"},
    {"code": "240810", "name": "원익IPS"},
    {"code": "357780", "name": "솔브레인"},
    {"code": "036460", "name": "한국가스공사"},
    {"code": "001740", "name": "SK네트웍스"},
    {"code": "161390", "name": "한국타이어앤테크놀로지"},
    {"code": "000080", "name": "하이트진로"},
    {"code": "005180", "name": "빙그레"},
    {"code": "007310", "name": "오뚜기"},
    {"code": "003230", "name": "삼양식품"},
    {"code": "086280", "name": "현대글로비스"},
    {"code": "294870", "name": "HDC현대산업개발"},
    {"code": "170900", "name": "동아ST"},
    {"code": "003850", "name": "보령"},
    {"code": "009290", "name": "광동제약"},
    {"code": "192820", "name": "코스맥스"},
    {"code": "161890", "name": "한국콜마"},
    {"code": "001680", "name": "대상"},
    {"code": "000070", "name": "삼양홀딩스"},
    {"code": "012750", "name": "에스원"},
    {"code": "006120", "name": "SK디스커버리"},
    {"code": "003540", "name": "대신증권"},
    {"code": "006490", "name": "인탑스"},
    {"code": "010140", "name": "삼성중공업"},
    {"code": "009450", "name": "경동나비엔"},
    {"code": "000060", "name": "메리츠화재"},
    {"code": "019170", "name": "신풍제약"},
    {"code": "316140", "name": "우리금융지주"},
    {"code": "030570", "name": "BNK금융지주"},
    {"code": "175330", "name": "JB금융지주"},
    {"code": "050등", "name": "DGB금융지주"},
    # ── 151~200 (중형주) ──
    {"code": "078340", "name": "컴투스"},
    {"code": "263750", "name": "펄어비스"},
    {"code": "035900", "name": "JYP Ent"},
    {"code": "041510", "name": "에스엠"},
    {"code": "122870", "name": "와이지엔터테인먼트"},
    {"code": "016360", "name": "삼성증권"},
    {"code": "026960", "name": "동서"},
    {"code": "007160", "name": "사조산업"},
    {"code": "008770", "name": "호텔신라"},
    {"code": "021080", "name": "IHQ"},
    {"code": "004000", "name": "롯데정밀화학"},
    {"code": "010580", "name": "에스에너지"},
    {"code": "003470", "name": "유안타증권"},
    {"code": "016610", "name": "DB금융투자"},
    {"code": "006650", "name": "대한유화"},
    {"code": "005070", "name": "코스모화학"},
    {"code": "003410", "name": "쌍용C&E"},
    {"code": "001230", "name": "동국제강"},
    {"code": "023150", "name": "MH에탄올"},
    {"code": "000215", "name": "DL"},
    {"code": "012630", "name": "HDC"},
    {"code": "000070", "name": "삼양홀딩스"},
    {"code": "111770", "name": "영원무역"},
    {"code": "084스크", "name": "이랜드리테일"},
    {"code": "005300", "name": "롯데칠성"},
    {"code": "033530", "name": "세아제강지주"},
    {"code": "001430", "name": "세아베스틸지주"},
    {"code": "002310", "name": "아세아제지"},
    {"code": "025820", "name": "이구산업"},
    {"code": "010780", "name": "아이에스동서"},
    {"code": "052690", "name": "한전기술"},
    {"code": "015890", "name": "태경산업"},
    {"code": "006740", "name": "영풍제지"},
    {"code": "014530", "name": "극동유화"},
    {"code": "001800", "name": "오리온홀딩스"},
    {"code": "006560", "name": "현대백화점우"},
    {"code": "009200", "name": "무림P&P"},
    {"code": "298040", "name": "효성중공업"},
    {"code": "093050", "name": "LF"},
    {"code": "000210", "name": "DL케미칼"},
    {"code": "014820", "name": "동원시스템즈"},
    {"code": "007570", "name": "일양약품"},
    {"code": "004560", "name": "현대비앤지스틸"},
    {"code": "000250", "name": "삼천리"},
    {"code": "002170", "name": "삼양통상"},
    {"code": "007700", "name": "F&F홀딩스"},
    {"code": "019210", "name": "화승인더"},
    {"code": "241560", "name": "두산밥캣"},
    {"code": "100840", "name": "SNT에너지"},
    {"code": "044820", "name": "코스맥스비티아이"},
    {"code": "214420", "name": "토니모리"},
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

def detect_candle_pattern(daily):
    """
    행잉맨 / 해머 패턴 감지 (직전 영업일 봉 기준)
    daily : KIS API 일봉 리스트 (index 0=오늘, 1=어제, 2=2일전 ... 최신→과거 순)
    반환  : 'hammer' | 'hanging_man' | None

    해머     : 하락 추세에서 발생 → 상승 반전 신호 (매수 우선순위↑)
    행잉맨   : 상승 추세에서 발생 → 하락 반전 신호 (보유 중이면 경계)
    """
    # 패턴 판별에 최소 7봉 필요 (1=어제, 2~6=추세 계산용 5일)
    if len(daily) < 7:
        return None

    # 직전 영업일 (index 1): 오늘 봉(index 0)은 장 중 미완성이므로 제외
    d = daily[1]
    o = int(d["stck_oprc"])
    h = int(d["stck_hgpr"])
    l = int(d["stck_lwpr"])
    c = int(d["stck_clpr"])

    body         = abs(c - o)
    upper_shadow = h - max(c, o)
    lower_shadow = min(c, o) - l
    total_range  = h - l

    if total_range == 0 or body == 0:
        return None

    small_body  = body         <= total_range * 0.3   # 몸통이 전체의 30% 이하
    long_lower  = lower_shadow >= body * 2.0           # 아래꼬리 ≥ 몸통의 2배
    short_upper = upper_shadow <= body * 0.3           # 위꼬리 거의 없음

    if not (small_body and long_lower and short_upper):
        return None

    # 추세 판별: index 2~6 (직전 5 영업일, 오래된→최근 순으로 비교)
    # daily[6] = 6일전(오래된), daily[2] = 2일전(최근)
    old_close    = int(daily[6]["stck_clpr"])
    recent_close = int(daily[2]["stck_clpr"])

    if recent_close > old_close:
        return "hanging_man"   # 상승 추세 + 긴 아래꼬리 = 하락 반전 경고
    elif recent_close < old_close:
        return "hammer"        # 하락 추세 + 긴 아래꼬리 = 상승 반전 기대
    return None


def check_volatility_breakout(stock_code):
    """
    변동성 돌파 조건 체크 + 캔들 패턴 감지
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
        pattern       = detect_candle_pattern(daily)

        return {
            "code":       stock_code,
            "현재가":     current["현재가"],
            "시가":       current["시가"],
            "목표가":     int(target),
            "전일변동폭": range_,
            "변동성돌파": volatility_ok,
            "AD상승":     ad_rising,
            "돌파여유율": (current["현재가"] - target) / target * 100 if target > 0 else 0,
            "패턴":       pattern,
        }

    except Exception as e:
        print(f"\n  [오류] {stock_code}: {e}")
        return None


def _grade(volatility_ok, ad_rising, gap, pattern):
    """
    매수 우선순위 그레이드
    A : 변동성 돌파 + AD상승 + 해머  → 최우선 매수
    B : 변동성 돌파 + AD상승         → 기존 전략
    C : 해머 패턴만                  → 내일 진입 검토
    """
    breakout = volatility_ok and ad_rising and gap <= sc.MAX_BREAKOUT_GAP
    if breakout and pattern == "hammer":
        return "A"
    if breakout:
        return "B"
    if pattern == "hammer":
        return "C"
    return None

def _resolve_name(code, kospi_map):
    """코드 → 종목명. KOSPI_200에 있으면 거기서, 없으면 코드 그대로."""
    return kospi_map.get(code, code)


def build_screening_pool():
    """
    코스피200(상위 N개) + 관심종목 합치기 (중복 제거)
    N = strategy_config.KOSPI_POOL_SIZE
    관심종목은 코드만 입력하면 이름 자동 조회.
    """
    n        = min(sc.KOSPI_POOL_SIZE, len(KOSPI_200))
    kospi_map = {s["code"]: s["name"] for s in KOSPI_200}  # code → name 조회용

    # 코스피200 상위 N개
    pool = {s["code"]: s for s in KOSPI_200[:n]}

    # 관심종목 추가 (코드만 있으면 이름 자동 채움)
    watchlist_new = 0
    for code in WATCHLIST_CODES:
        if code not in pool:
            watchlist_new += 1
            pool[code] = {"code": code, "name": _resolve_name(code, kospi_map)}
        # 코스피200에 이미 있으면 그대로 유지 (이름 정보 있음)

    result = list(pool.values())
    print(f"  스크리닝 풀: 코스피200 상위 {n}개 + 관심종목 {len(WATCHLIST_CODES)}개 "
          f"(신규 {watchlist_new}개) = 총 {len(result)}개")
    return result

_GRADE_ORDER = {"A": 0, "B": 1, "C": 2}
_GRADE_LABEL = {
    "A": "A [변동성돌파+해머]",
    "B": "B [변동성돌파]",
    "C": "C [해머패턴]",
}
_PATTERN_EMOJI = {
    "hammer":      "🔨",
    "hanging_man": "⚠️",
}


def run_screening(progress_cb=None):
    """
    전체 스크리닝 실행
    progress_cb : (current, total, name) → None  (UI 진행률 콜백, 선택)
    그레이드: A(변동성+해머) > B(변동성) > C(해머만)
    행잉맨(hanging_man)은 매수 후보 제외, 보유 종목 경고용으로만 반환
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 스크리닝 시작...")
    pool   = build_screening_pool()
    passed = []
    warned = []
    failed = []

    for i, stock in enumerate(pool):
        print(f"  [{i+1}/{len(pool)}] {stock['name']} 체크 중...", end="\r")
        if progress_cb:
            progress_cb(i + 1, len(pool), stock["name"])
        result = check_volatility_breakout(stock["code"])

        if result is None:
            failed.append(stock["code"])
            time.sleep(0.5)
            continue

        grade = _grade(
            result["변동성돌파"], result["AD상승"],
            result["돌파여유율"], result["패턴"]
        )

        if grade:
            passed.append({
                "code":       stock["code"],
                "name":       stock["name"],
                "현재가":     result["현재가"],
                "목표가":     result["목표가"],
                "돌파여유율": result["돌파여유율"],
                "패턴":       result["패턴"],
                "grade":      grade,
                # scorer.py technical_score() 에서 사용
                "변동성돌파": result["변동성돌파"],
                "AD상승":     result["AD상승"],
            })
        elif result["패턴"] == "hanging_man":
            warned.append(stock["name"])

        time.sleep(0.5)

    # 정렬: 그레이드 오름차순(A→B→C), 같은 그레이드 내에서는 돌파여유율 낮은 순
    passed.sort(key=lambda x: (_GRADE_ORDER[x["grade"]], x["돌파여유율"]))

    print(f"\n[스크리닝 완료]")
    print(f"  전체: {len(pool)}개 | 통과: {len(passed)}개 | 오류: {len(failed)}개")

    if passed:
        print(f"\n  ✅ 매수 후보:")
        for s in passed:
            pat_str = f"  {_PATTERN_EMOJI.get(s['패턴'], '')} " if s["패턴"] else "    "
            print(f"    {_GRADE_LABEL[s['grade']]:22s}{pat_str}"
                  f"{s['name']} ({s['code']}) | {s['현재가']:,}원 | 목표가 {s['목표가']:,}원")
    else:
        print(f"  ❌ 조건 충족 종목 없음")

    if warned:
        print(f"\n  ⚠️  행잉맨 감지 (하락 반전 경고): {', '.join(warned)}")

    sc.update_candidates(passed)
    return passed

if __name__ == "__main__":
    # 스크리닝 단독 테스트
    results = run_screening()