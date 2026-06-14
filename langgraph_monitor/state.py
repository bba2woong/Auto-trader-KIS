from typing import TypedDict, Optional


class TradeState(TypedDict):
    # 입력
    ticker: str                        # 종목 코드

    # 각 노드 점수
    volatility_score: Optional[float]  # 변동성 돌파 점수 (max 40)
    ad_line_score: Optional[float]     # AD Line 점수 (max 15)
    news_score: Optional[float]        # 뉴스 감성 점수 (max 10)
    dart_score: Optional[float]        # DART 공시 점수 (max 10)

    # 각 노드 실행 시간 (초)
    volatility_elapsed: Optional[float]
    ad_line_elapsed: Optional[float]
    news_elapsed: Optional[float]
    dart_elapsed: Optional[float]
    scoring_elapsed: Optional[float]

    # 집계 결과
    total_score: Optional[float]       # 종합 점수
    decision: Optional[str]            # "BUY" / "SKIP"
    reason: Optional[str]              # 판단 근거
