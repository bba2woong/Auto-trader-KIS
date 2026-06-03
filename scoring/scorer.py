"""
종목 총점 계산 + 일별 캐시 관리

점수 구성 (총 100점):
  변동성 돌파  30점  — 돌파 여부 + 여유율 (낮을수록 고점)
  AD Line     30점  — 상승 여부
  캔들 패턴   ±10점  — 해머 +10 / 행잉맨 -10 / 없음 0
  LLM 분석    20점  — bullish=20 / neutral=10 / bearish=0
  DART 공시   10점  — 긍정=10 / 중립=0 / 부정=-10

캐시 갱신 시점 (scheduler.py에서 호출):
  - 장 전 (MARKET_OPEN 30분 전)
  - 오후 1시
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

REFRESH_TIMES = ["0830", "1300"]   # 캐시 갱신 시각 (HH:MM 없는 HHMM)


# ──────────────────────────────────────────
# 기술적 점수 (실시간 계산)
# ──────────────────────────────────────────

def technical_score(screening_result: dict) -> int:
    """
    screener.py check_volatility_breakout() 반환값 기반 기술적 점수
    변동성 돌파 30 + AD Line 30 + 캔들 ±10 = 최대 70점
    """
    score = 0

    # 변동성 돌파 (최대 30점)
    if screening_result.get("변동성돌파"):
        gap   = screening_result.get("돌파여유율", 0)
        # gap 0%→30점, 1%→20점, MAX_BREAKOUT_GAP%→0점 선형 감소
        ratio = max(0.0, 1.0 - gap / max(sc.MAX_BREAKOUT_GAP, 0.01))
        score += int(30 * ratio)

    # AD Line (30점)
    if screening_result.get("AD상승"):
        score += 30

    # 캔들 패턴 (±10점)
    pattern = screening_result.get("패턴")
    if pattern == "hammer":
        score += 10
    elif pattern == "hanging_man":
        score -= 10

    return score


# ──────────────────────────────────────────
# 총점 계산 (기술적 + 캐시)
# ──────────────────────────────────────────

def total_score(screening_result: dict) -> dict:
    """
    종목 총점 반환
    반환: {
        "code": str, "total": int,
        "tech": int, "llm": int, "dart": int,
        "llm_opinion": str, "llm_reason": str, "dart_reason": str,
        "grade": "A"|"B"|"C"|None  (스크리너 그레이드와 별개)
    }
    """
    code  = screening_result["code"]
    tech  = technical_score(screening_result)
    cache = _load_cache()

    stock_cache = cache.get("stocks", {}).get(code, {})
    llm_score   = stock_cache.get("llm_score",  10)   # 캐시 없으면 중립
    dart_score  = stock_cache.get("dart_score",  0)

    total = tech + llm_score + dart_score

    return {
        "code":        code,
        "total":       total,
        "tech":        tech,
        "llm":         llm_score,
        "dart":        dart_score,
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
    dart_results = score_stocks(stock_list)

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
