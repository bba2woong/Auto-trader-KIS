"""
종목 총점 계산 + 일별 캐시 관리

점수 구성 (최대 110점):
  변동성 돌파  최대 40점 — 돌파 여부 + 여유율 (낮을수록 고점)
  AD Line      +15점     — 상승 여부
  캔들 패턴    +10점     — 해머 +10 / 행잉맨 0 (패널티 없음)
  60분봉 강봉  +15점     — strong_bull 감지 시
  LLM 분석     최대 10점 — bullish=10 / neutral=5 / bearish=0  (llm_score // 2)
  DART 공시    +10점     — 긍정=10 / 중립=0 / 부정=-10
  관심종목     +10점     — watchlist.py 등록 종목 가점
  합계         최대 110점

캐시 갱신 시점 (scheduler.py에서 호출):
  - 08:30 (장 전)
  - 10:00
  - 12:00
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc

CACHE_DIR  = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

REFRESH_TIMES = ["0830", "1000", "1200"]   # 캐시 갱신 시각 (HH:MM 없는 HHMM)


# ──────────────────────────────────────────
# 기술적 점수 (실시간 계산)
# ──────────────────────────────────────────

def technical_score(screening_result: dict) -> int:
    """
    screener.py check_volatility_breakout() 반환값 기반 기술적 점수
    변동성 돌파 최대40 + AD Line 15 + 해머 +10 + strong_bull +15 + 관심종목 +10 = 최대 90점
    (LLM/DART 합산 시 최대 110점)
    """
    score = 0

    # 변동성 돌파 (최대 40점)
    if screening_result.get("변동성돌파"):
        gap   = screening_result.get("돌파여유율", 0)
        ratio = max(0.0, 1.0 - gap / max(sc.MAX_BREAKOUT_GAP, 0.01))
        score += int(40 * ratio)

    # AD Line (15점)
    if screening_result.get("AD상승"):
        score += 15

    # 캔들 패턴: 해머 +10 / 행잉맨 패널티 없음
    if screening_result.get("패턴") == "hammer":
        score += 10

    # 60분봉 강한 양봉 (15점)
    if screening_result.get("시간봉패턴") == "strong_bull":
        score += 15

    # 관심종목 가점 (+10점)
    try:
        from watchlist import WATCHLIST_CODES
        if screening_result.get("code") in WATCHLIST_CODES:
            score += 10
    except Exception:
        pass

    return score


# ──────────────────────────────────────────
# 총점 계산 (기술적 + 캐시)
# ──────────────────────────────────────────

def total_score(screening_result: dict) -> dict:
    """
    종목 총점 반환
    반환: {
        "code": str, "total": int,
        "tech": int, "llm": int, "dart": int, "watchlist": int,
        "llm_opinion": str, "llm_reason": str, "dart_reason": str,
    }
    """
    code  = screening_result["code"]
    tech  = technical_score(screening_result)   # 관심종목 +10 포함
    cache = _load_cache()

    stock_cache = cache.get("stocks", {}).get(code, {})
    llm_raw     = stock_cache.get("llm_score",  10)   # 캐시 없으면 중립(10)
    llm_score   = llm_raw // 2                         # bullish=10, neutral=5, bearish=0
    dart_score  = stock_cache.get("dart_score",  0)

    # 관심종목 여부 (표시용 — 실제 점수는 technical_score 내부에서 이미 가산)
    try:
        from watchlist import WATCHLIST_CODES
        watchlist_bonus = 10 if code in WATCHLIST_CODES else 0
    except Exception:
        watchlist_bonus = 0

    total = tech + llm_score + dart_score

    return {
        "code":        code,
        "total":       total,
        "tech":        tech,
        "llm":         llm_score,
        "dart":        dart_score,
        "watchlist":   watchlist_bonus,
        "llm_opinion": stock_cache.get("llm_opinion", "unknown"),
        "llm_reason":  stock_cache.get("llm_reason",  "캐시 없음"),
        "dart_reason": stock_cache.get("dart_reason",  "캐시 없음"),
    }


def routing(score: int) -> str:
    """
    점수 기반 라우팅
    반환: "auto_buy" | "confirm" | "skip"
    """
    if score >= sc.AUTO_BUY_SCORE:
        return "auto_buy"
    if score >= sc.CONFIRM_SCORE_MIN:
        return "confirm"
    return "skip"


# ──────────────────────────────────────────
# 캐시 갱신 (LLM + DART 일괄 분석)
# ──────────────────────────────────────────

def refresh_cache(stock_list: list, label: str = ""):
    """
    LLM + DART 분석 실행 후 캐시 저장
    stock_list : [{"code", "name"}, ...]
    label      : "장전" | "오후1시" (로그용)
    """
    from scoring.llm_client  import analyze_stocks
    from scoring.dart_client import score_stocks

    print(f"\n{'='*44}")
    print(f"  AI 분석 캐시 갱신 [{label or datetime.now().strftime('%H:%M')}]")
    print(f"  대상: {len(stock_list)}개 종목")
    print(f"{'='*44}")

    print("\n[1/2] Perplexity LLM 분석...")
    llm_results  = analyze_stocks(stock_list)

    print("\n[2/2] DART 공시 분석...")
    if sc.USE_DART_SCORING:
        dart_results = score_stocks(stock_list)
    else:
        print("  [DART] USE_DART_SCORING=False — 건너뜀")
        dart_results = {s["code"]: {"score": 0, "reason": "비활성화"} for s in stock_list}

    # 캐시 병합
    cache  = _load_cache()
    stocks = cache.setdefault("stocks", {})
    now    = datetime.now().strftime("%H%M")

    for stock in stock_list:
        code = stock["code"]
        llm  = llm_results.get(code,  {})
        dart = dart_results.get(code, {})

        stocks[code] = {
            "llm_score":   llm.get("score",   10),
            "llm_opinion": llm.get("opinion", "neutral"),
            "llm_reason":  llm.get("reason",  ""),
            "dart_score":  dart.get("score",   0),
            "dart_reason": dart.get("reason",  ""),
            "updated_at":  now,
        }

    cache["date"]     = datetime.now().strftime("%Y%m%d")
    cache["last_run"] = now
    _save_cache(cache)

    print(f"\n  캐시 저장 완료 ({len(stocks)}개)")
    return stocks


def needs_refresh() -> bool:
    """현재 시각이 갱신 시각(REFRESH_TIMES)에 해당하는지 확인"""
    now      = datetime.now().strftime("%H%M")
    cache    = _load_cache()
    last_run = cache.get("last_run", "0000")

    for t in REFRESH_TIMES:
        # 정각 기준 ±2분 이내이고, 오늘 아직 이 시각에 실행 안 했으면
        if abs(int(now) - int(t)) <= 2 and last_run < t:
            return True
    return False


# ──────────────────────────────────────────
# 캐시 파일 입출력
# ──────────────────────────────────────────

def _cache_path() -> Path:
    today = datetime.now().strftime("%Y%m%d")
    return CACHE_DIR / f"daily_{today}.json"


def _load_cache() -> dict:
    path = _cache_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"date": datetime.now().strftime("%Y%m%d"), "stocks": {}}


def _save_cache(data: dict):
    _cache_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
