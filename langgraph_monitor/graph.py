from langgraph.graph import StateGraph, END
from state import TradeState
from nodes import volatility_node, ad_line_node, news_node, dart_node, scoring_node


def build_graph():
    graph = StateGraph(TradeState)

    # 노드 등록
    graph.add_node("volatility", volatility_node)
    graph.add_node("ad_line", ad_line_node)
    graph.add_node("news", news_node)
    graph.add_node("dart", dart_node)
    graph.add_node("scoring", scoring_node)

    # 시작 노드 설정
    graph.set_entry_point("volatility")

    # 순차 연결 (volatility → ad_line → news → dart → scoring)
    graph.add_edge("volatility", "ad_line")
    graph.add_edge("ad_line", "news")
    graph.add_edge("news", "dart")
    graph.add_edge("dart", "scoring")
    graph.add_edge("scoring", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()
    result = app.invoke({"ticker": "005930"})
    print(result)
