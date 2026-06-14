import time
import random
from state import TradeState


def volatility_node(state: TradeState) -> dict:
    """변동성 돌파 분석 노드 (Mock)"""
    start = time.time()
    time.sleep(random.uniform(0.3, 0.8))  # API 호출 시뮬레이션

    # Mock 점수: 0~40점
    score = round(random.uniform(0, 40), 1)

    return {
        "volatility_score": score,
        "volatility_elapsed": round(time.time() - start, 3),
    }


def ad_line_node(state: TradeState) -> dict:
    """AD Line 분석 노드 (Mock)"""
    start = time.time()
    time.sleep(random.uniform(0.2, 0.6))

    # Mock 점수: 0~15점
    score = round(random.uniform(0, 15), 1)

    return {
        "ad_line_score": score,
        "ad_line_elapsed": round(time.time() - start, 3),
    }


def news_node(state: TradeState) -> dict:
    """뉴스 감성 분석 노드 (Mock) - Perplexity API 시뮬레이션"""
    start = time.time()
    time.sleep(random.uniform(1.0, 2.5))  # LLM 호출 시뮬레이션 (느림)

    # Mock 점수: 0~10점
    score = round(random.uniform(0, 10), 1)

    return {
        "news_score": score,
        "news_elapsed": round(time.time() - start, 3),
    }


def dart_node(state: TradeState) -> dict:
    """DART 공시 분석 노드 (Mock)"""
    start = time.time()
    time.sleep(random.uniform(0.5, 1.2))

    # Mock 점수: 0~10점
    score = round(random.uniform(0, 10), 1)

    return {
        "dart_score": score,
        "dart_elapsed": round(time.time() - start, 3),
    }


def scoring_node(state: TradeState) -> dict:
    """스코어 집계 및 종목 판단 노드"""
    start = time.time()

    total = sum([
        state.get("volatility_score") or 0,
        state.get("ad_line_score") or 0,
        state.get("news_score") or 0,
        state.get("dart_score") or 0,
    ])
    total = round(total, 1)

    if total >= 50:
        decision = "BUY"
        reason = f"종합 점수 {total}점 — 임계값(50점) 초과"
    else:
        decision = "SKIP"
        reason = f"종합 점수 {total}점 — 임계값(50점) 미달"

    return {
        "total_score": total,
        "decision": decision,
        "reason": reason,
        "scoring_elapsed": round(time.time() - start, 3),
    }
