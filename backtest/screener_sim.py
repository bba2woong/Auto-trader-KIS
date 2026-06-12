"""
일별 스크리닝 시뮬레이션 (params 격리 + 전체 풀 지원)

변경 이력:
- params dict 주입으로 전역 strategy_config/scorer 수정 없이 배점 격리
- get_full_stock_pool(): KOSPI200 + watchlist 전체 풀 반환
- compute_tech_score(): scorer.py 대신 params 기반 점수 계산
- screen_day()에 MIN_SCORE 임계값 필터 추가
- 일봉 기반 해머 캔들 감지 추가
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc

AD_PERIODS = 5


# ── 기본 백테스트 params (sc 전역값 스냅샷) ─────────────────────
def get_default_bt_params() -> dict:
    """
    백테스트 실행 시 기본 params dict 반환.
    strategy_config 전역값을 1회 스냅샷 — 이후 전역 변경에 영향 없음.
    """
    return {
        # ── 트레이딩 ──
        "K":                           sc.K,
        "LOSS_RATE":                   sc.LOSS_RATE,
        "TRAILING_STOP_RATE":          sc.TRAILING_STOP_RATE,
        "TRAILING_STOP_ACTIVATE_RATE": sc.TRAILING_STOP_ACTIVATE_RATE,
        "USE_TRAILING_STOP":           sc.USE_TRAILING_STOP,
        "PROFIT_RATE":                 sc.PROFIT_RATE,
        "INVEST_RATIO":                sc.INVEST_RATIO,
        "MAX_TRADES_PER_DAY":          sc.MAX_TRADES_PER_DAY,
        "budget_per_position":         None,
        # ── Scorer 배점 ──
        "SCORE_BREAKOUT_MAX": 40,   # 변동성 돌파 최대 점수
        "SCORE_AD_LINE":      15,   # AD Line 점수
        "SCORE_CANDLE":       10,   # 해머 캔들 점수
        "SCORE_STRONG_BULL":  15,   # 60분봉 강봉 점수
        "SCORE_WATCHLIST":    10,   # 관심종목 가점
        "LLM_FIXED":           5,   # 백테스트 고정 LLM 점수 (중립=5)
        "DART_FIXED":          0,   # 백테스트 고정 DART 점수 (중립=0)
        "MIN_SCORE":          sc.CONFIRM_SCORE_MIN,
    }


# ── 전체 스크리닝 풀 ─────────────────────────────────────────────
def get_full_stock_pool() -> list:
    """
    백테스트용 전체 종목 풀 반환.
    KOSPI200 전체 + watchlist (중복 제거)
    """
    try:
        from screener import KOSPI_200
    except Exception:
        KOSPI_200 = []
    try:
        from watchlist import WATCHLIST_CODES
        wl = [{"code": c, "name": c} for c in WATCHLIST_CODES]
    except Exception:
        wl = []

    seen, pool = set(), []
    for s in KOSPI_200 + wl:
        if s["code"] not in seen:
            seen.add(s["code"])
            pool.append(s)
    return pool


# ── 점수 계산 ────────────────────────────────────────────────────
def compute_tech_score(screening_result: dict, params: dict) -> int:
    """
    params 기반 기술적 점수 계산.
    scorer.py의 전역값 대신 params를 사용해 완전 격리.
    LLM/DART는 백테스트 고정값(LLM_FIXED, DART_FIXED) 사용.
    """
    score = 0

    # 변동성 돌파 (최대 SCORE_BREAKOUT_MAX)
    if screening_result.get("변동성돌파"):
        gap     = screening_result.get("돌파여유율", 0)
        gap_max = max(sc.MAX_BREAKOUT_GAP, 0.01)
        ratio   = max(0.0, 1.0 - gap / gap_max)
        score  += int(params.get("SCORE_BREAKOUT_MAX", 40) * ratio)

    # AD Line
    if screening_result.get("AD상승"):
        score += int(params.get("SCORE_AD_LINE", 15))

    # 캔들 패턴 (해머)
    if screening_result.get("패턴") == "hammer":
        score += int(params.get("SCORE_CANDLE", 10))

    # 60분봉 강봉 (분봉 백테스트에서만 채워짐)
    if screening_result.get("시간봉패턴") == "strong_bull":
        score += int(params.get("SCORE_STRONG_BULL", 15))

    # 관심종목 가점
    if screening_result.get("watchlist"):
        score += int(params.get("SCORE_WATCHLIST", 10))

    # LLM / DART 고정값 (백테스트: API 미호출)
    score += int(params.get("LLM_FIXED", 5))
    score += int(params.get("DART_FIXED", 0))

    return score


# ── 스크리닝 ─────────────────────────────────────────────────────
def screen_day(all_data, date, stock_list, params=None):
    """
    특정 날짜의 스크리닝 시뮬레이션.

    all_data   : {code: {date: ohlcv_row}}
    date       : "YYYYMMDD"
    stock_list : [{"code", "name"}, ...]
    params     : get_default_bt_params() 형식 dict.
                 None이면 sc 전역값 사용 (하위 호환).
    반환       : 조건 충족 + 점수 통과 종목 (gap 오름차순)
    """
    if params is None:
        params = get_default_bt_params()

    k         = params.get("K", sc.K)
    min_score = params.get("MIN_SCORE", 0)   # 0이면 점수 필터 없음

    try:
        from watchlist import WATCHLIST_CODES
        wl_codes = set(WATCHLIST_CODES)
    except Exception:
        wl_codes = set()

    passed = []
    for stock in stock_list:
        code   = stock["code"]
        result = _check_stock(all_data.get(code, {}), code, date, k)
        if result is None:
            continue
        result["watchlist"] = code in wl_codes
        score = compute_tech_score(result, params)
        if score >= min_score:
            passed.append({**stock, **result, "score": score})

    passed.sort(key=lambda x: x["gap"])
    return passed


# ── 내부 함수 ────────────────────────────────────────────────────
def _check_stock(date_map, code, date, k):
    """단일 종목 스크리닝 체크. k param 사용."""
    if date not in date_map:
        return None

    sorted_dates = sorted(date_map.keys())
    try:
        idx = sorted_dates.index(date)
    except ValueError:
        return None

    if idx < 1:
        return None

    today = date_map[date]
    prev  = date_map[sorted_dates[idx - 1]]

    prev_range = prev["high"] - prev["low"]
    if prev_range == 0:
        return None
    target = today["open"] + prev_range * k

    if today["high"] < target:
        return None

    # AD Line
    window_dates = sorted_dates[max(0, idx - AD_PERIODS + 1): idx + 1]
    window       = [date_map[d] for d in window_dates]
    if not _ad_rising(window):
        return None

    gap    = (today["close"] - target) / target * 100
    hammer = _is_hammer(today)

    return {
        "target":      int(target),
        "buy_price":   int(target),
        "gap":         gap,
        "today":       today,
        "prev":        prev,
        "변동성돌파":   True,
        "돌파여유율":   gap,
        "AD상승":       True,
        "패턴":         "hammer" if hammer else None,
        "시간봉패턴":   None,   # 일봉 기반: 분봉 없어 미사용
    }


def _is_hammer(candle) -> bool:
    """해머 캔들 패턴 감지 (일봉 OHLC 기준)"""
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    body         = abs(c - o)
    total_range  = h - l
    if total_range == 0 or body == 0:
        return False
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    return lower_shadow >= 2 * body and upper_shadow <= body * 0.3


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
