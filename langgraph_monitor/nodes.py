import time
import random
from state import TradeState
from score_config import (
    SCORE_VOLATILITY_MAX,
    SCORE_AD_LINE,
    SCORE_CANDLE_MAX,
    SCORE_STRONG_BULL,
    SCORE_LLM_MAX,
    SCORE_DART_MAX,
    SCORE_WATCHLIST,
    BUY_THRESHOLD,
    VOLATILITY_GATE,
    AD_LINE_GATE,
    TECH_GATE,
)


# ── 변동성 돌파 (max SCORE_VOLATILITY_MAX점) ─────────────────────
def volatility_node(state: TradeState) -> dict:
    """변동성 돌파 분석 (Mock) — 돌파여유율 반영, 0~SCORE_VOLATILITY_MAX 비례"""
    start = time.time()
    time.sleep(random.uniform(0.3, 0.8))
    score = round(random.uniform(0, SCORE_VOLATILITY_MAX), 1)
    return {
        "volatility_score":   score,
        "volatility_elapsed": round(time.time() - start, 3),
    }


# ── AD Line (SCORE_AD_LINE점 고정) ───────────────────────────────
def ad_line_node(state: TradeState) -> dict:
    """AD Line 상승 여부 (Mock) — 상승이면 SCORE_AD_LINE, 아니면 0"""
    start = time.time()
    time.sleep(random.uniform(0.2, 0.6))
    score = random.choice([0, SCORE_AD_LINE])
    return {
        "ad_line_score":   score,
        "ad_line_elapsed": round(time.time() - start, 3),
    }


# ── 캔들 패턴 (max SCORE_CANDLE_MAX점) ──────────────────────────
def candle_node(state: TradeState) -> dict:
    """캔들 패턴 분석 (Mock) — 해머 +SCORE_CANDLE_MAX / 그 외 0"""
    start = time.time()
    time.sleep(random.uniform(0.1, 0.4))
    score = random.choice([0, SCORE_CANDLE_MAX])
    return {
        "candle_score":   score,
        "candle_elapsed": round(time.time() - start, 3),
    }


# ── 60분봉 강봉 (SCORE_STRONG_BULL점 고정) ──────────────────────
def strong_bull_node(state: TradeState) -> dict:
    """60분봉 강한 양봉 감지 (Mock) — 감지 시 SCORE_STRONG_BULL, 아니면 0"""
    start = time.time()
    time.sleep(random.uniform(0.2, 0.5))
    score = random.choice([0, SCORE_STRONG_BULL])
    return {
        "strong_bull_score":   score,
        "strong_bull_elapsed": round(time.time() - start, 3),
    }


# ── LLM 뉴스 감성 (max SCORE_LLM_MAX점) ────────────────────────
def news_node(state: TradeState) -> dict:
    """뉴스 감성 분석 (Mock) — bullish=MAX / neutral=MAX//2 / bearish=0"""
    start = time.time()
    time.sleep(random.uniform(1.0, 2.5))
    score = random.choice([0, SCORE_LLM_MAX // 2, SCORE_LLM_MAX])
    return {
        "news_score":   score,
        "news_elapsed": round(time.time() - start, 3),
    }


# ── DART 공시 (±SCORE_DART_MAX점) ───────────────────────────────
def dart_node(state: TradeState) -> dict:
    """DART 공시 분석 (Mock) — 긍정=+MAX / 중립=0 / 부정=-MAX"""
    start = time.time()
    time.sleep(random.uniform(0.5, 1.2))
    score = random.choice([-SCORE_DART_MAX, 0, SCORE_DART_MAX])
    return {
        "dart_score":   score,
        "dart_elapsed": round(time.time() - start, 3),
    }


# ── 관심종목 보너스 (SCORE_WATCHLIST점 고정) ────────────────────
def watchlist_node(state: TradeState) -> dict:
    """관심종목 등록 여부 (Mock) — 등록 시 SCORE_WATCHLIST, 아니면 0"""
    start = time.time()
    time.sleep(random.uniform(0.1, 0.3))
    score = random.choice([0, SCORE_WATCHLIST])
    return {
        "watchlist_score":   score,
        "watchlist_elapsed": round(time.time() - start, 3),
    }


# ── 스코어 집계 ──────────────────────────────────────────────────
def scoring_node(state: TradeState) -> dict:
    """
    전체 점수 합산 및 BUY/SKIP 판정.

    조기종료(Early Exit) 감지:
    - news_score가 None이면 Gate 3 이전에 이미 SKIP 결정된 것
    - ad_line_score가 None이면 Gate 1에서 종료
    - candle_score가 None이면 Gate 2에서 종료
    조기종료 시 어느 게이트에서 탈락했는지 reason에 포함.
    """
    start = time.time()

    v  = state.get("volatility_score")  or 0
    a  = state.get("ad_line_score")     or 0
    c  = state.get("candle_score")      or 0
    sb = state.get("strong_bull_score") or 0
    n  = state.get("news_score")        or 0
    d  = state.get("dart_score")        or 0
    w  = state.get("watchlist_score")   or 0

    total = round(v + a + c + sb + n + d + w, 1)

    # 어느 게이트에서 조기종료됐는지 감지
    if state.get("ad_line_score") is None:
        # Gate 1 탈락 — volatility_score만 있음
        decision = "SKIP"
        reason   = f"[Gate 1] 변동성 점수 {v}점 — 하한({VOLATILITY_GATE}점) 미달로 조기종료"
    elif state.get("candle_score") is None:
        # Gate 2 탈락 — volatility + ad_line까지만 실행
        decision = "SKIP"
        reason   = f"[Gate 2] 기술점수 합산 {v+a}점 — 하한({AD_LINE_GATE}점) 미달로 조기종료"
    elif state.get("news_score") is None:
        # Gate 3 탈락 — candle + strong_bull까지만 실행
        decision = "SKIP"
        reason   = f"[Gate 3] 기술점수 합산 {v+a+c+sb}점 — 하한({TECH_GATE}점) 미달로 조기종료"
    elif total >= BUY_THRESHOLD:
        decision = "BUY"
        reason   = f"종합 점수 {total}점 — 임계값({BUY_THRESHOLD}점) 초과"
    else:
        decision = "SKIP"
        reason   = f"종합 점수 {total}점 — 임계값({BUY_THRESHOLD}점) 미달"

    return {
        "total_score":     total,
        "decision":        decision,
        "reason":          reason,
        "scoring_elapsed": round(time.time() - start, 3),
    }
