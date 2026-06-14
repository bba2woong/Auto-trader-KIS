from langgraph.graph import StateGraph, END
from state import TradeState
from nodes import (
    volatility_node, ad_line_node, candle_node, strong_bull_node,
    news_node, dart_node, watchlist_node, scoring_node,
)
from score_config import (
    VOLATILITY_GATE,
    AD_LINE_GATE,
    TECH_GATE,
)


# ── 조건부 라우팅 함수 ───────────────────────────────────────────

def _after_volatility(state: TradeState) -> str:
    """Gate 1: 변동성 돌파 점수 < VOLATILITY_GATE → 즉시 scoring(SKIP)"""
    if (state.get("volatility_score") or 0) < VOLATILITY_GATE:
        return "scoring"
    return "ad_line"


def _after_ad_line(state: TradeState) -> str:
    """Gate 2: volatility + ad_line 합산 < AD_LINE_GATE → scoring(SKIP)"""
    subtotal = (state.get("volatility_score") or 0) + (state.get("ad_line_score") or 0)
    if subtotal < AD_LINE_GATE:
        return "scoring"
    return "candle"


def _after_strong_bull(state: TradeState) -> str:
    """Gate 3: 기술적 점수 4개 합산 < TECH_GATE → scoring(SKIP), 이후만 외부 API"""
    subtotal = sum([
        state.get("volatility_score")  or 0,
        state.get("ad_line_score")     or 0,
        state.get("candle_score")      or 0,
        state.get("strong_bull_score") or 0,
    ])
    if subtotal < TECH_GATE:
        return "scoring"
    return "news"


# ── 그래프 빌드 ──────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(TradeState)

    # 노드 등록
    graph.add_node("volatility",  volatility_node)
    graph.add_node("ad_line",     ad_line_node)
    graph.add_node("candle",      candle_node)
    graph.add_node("strong_bull", strong_bull_node)
    graph.add_node("news",        news_node)
    graph.add_node("dart",        dart_node)
    graph.add_node("watchlist",   watchlist_node)
    graph.add_node("scoring",     scoring_node)

    graph.set_entry_point("volatility")

    # Gate 1 — 변동성 돌파 후 분기
    graph.add_conditional_edges(
        "volatility",
        _after_volatility,
        {"scoring": "scoring", "ad_line": "ad_line"},
    )

    # Gate 2 — AD Line 후 분기
    graph.add_conditional_edges(
        "ad_line",
        _after_ad_line,
        {"scoring": "scoring", "candle": "candle"},
    )

    # candle → strong_bull 은 항상 순차
    graph.add_edge("candle", "strong_bull")

    # Gate 3 — 기술적 점수 합산 후 외부 API 진입 여부 결정
    graph.add_conditional_edges(
        "strong_bull",
        _after_strong_bull,
        {"scoring": "scoring", "news": "news"},
    )

    # 이후는 항상 순차 (외부 API 구간)
    graph.add_edge("news",     "dart")
    graph.add_edge("dart",     "watchlist")
    graph.add_edge("watchlist","scoring")
    graph.add_edge("scoring",  END)

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()
    result = app.invoke({"ticker": "005930"})
    print(result)
