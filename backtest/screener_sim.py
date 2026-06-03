"""
일별 스크리닝 시뮬레이션
실제 screener.py의 변동성 돌파 + AD Line 조건을 과거 데이터로 재현한다.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc

AD_PERIODS = 5  # AD Line 윈도우 (screener.py 와 동일)


def screen_day(all_data, date, stock_list):
    """
    특정 날짜의 스크리닝 시뮬레이션
    all_data   : {code: {date: ohlcv_row}}
    date       : "YYYYMMDD"
    stock_list : [{"code", "name"}, ...]
    반환       : 조건 충족 종목 리스트 (돌파여유율 오름차순)
                 [{"code","name","target","buy_price","gap","today"}, ...]
    """
    passed = []

    for stock in stock_list:
        code   = stock["code"]
        result = _check_stock(all_data.get(code, {}), code, date)
        if result:
            passed.append({**stock, **result})

    # 돌파여유율 낮은 순 정렬 (방금 막 돌파한 종목 우선)
    passed.sort(key=lambda x: x["gap"])
    return passed


def _check_stock(date_map, code, date):
    """
    단일 종목 스크리닝 체크
    반환: 조건 충족 시 dict, 아니면 None
    """
    if date not in date_map:
        return None

    # 날짜 정렬된 키 목록에서 date 이전 날짜들 추출
    sorted_dates = sorted(date_map.keys())
    try:
        idx = sorted_dates.index(date)
    except ValueError:
        return None

    if idx < 1:
        return None  # 전일 데이터 없음

    today = date_map[date]
    prev  = date_map[sorted_dates[idx - 1]]

    # 변동성 돌파 목표가
    prev_range   = prev["high"] - prev["low"]
    if prev_range == 0:
        return None
    target = today["open"] + prev_range * sc.K

    # 당일 고가가 목표가에 도달해야 돌파
    if today["high"] < target:
        return None

    # AD Line (최근 AD_PERIODS일)
    window_dates = sorted_dates[max(0, idx - AD_PERIODS + 1): idx + 1]
    window       = [date_map[d] for d in window_dates]
    if not _ad_rising(window):
        return None

    # 돌파여유율: 종가를 "체결 시점 근사값"으로 사용
    gap = (today["close"] - target) / target * 100

    return {
        "target":    int(target),
        "buy_price": int(target),   # 백테스트에서는 목표가에 체결 가정
        "gap":       gap,
        "today":     today,
        "prev":      prev,
    }


def _ad_rising(window):
    if len(window) < 2:
        return False
    cumsum, ad_line = 0, []
    for r in window:
        h, l, c, v = r["high"], r["low"], r["close"], r["volume"]
        ad = ((c - l) - (h - c)) / (h - l) * v if h != l else 0
        cumsum += ad
        ad_line.append(cumsum)
    return ad_line[-1] > ad_line[-2]
