"""
파이프라인 노드별 배점 상수 — scorer.py 로직 기반 단일 출처(SSOT).

배점 변경 시 이 파일만 수정하면 nodes.py / pipeline_monitor_tab.py 에 자동 반영.

참조 근거 (scoring/scorer.py):
  변동성 돌파  : int(40 * ratio)          → max 40
  AD Line      : score += 15              → 15 (고정)
  캔들 패턴    : score += 10 (해머)       → max 10
  60분봉 강봉  : score += 15              → 15 (고정)
  LLM 뉴스     : llm_raw // 2 → 20//2=10  → max 10  (bullish=10/neutral=5/bearish=0)
  DART 공시    : -10 / 0 / +10            → max 10  (부정 시 -10)
  관심종목     : score += 10              → max 10 (고정)
  ─────────────────────────────────────────────
  합계 최대                               110점

BUY 임계값   : strategy_config.CONFIRM_SCORE_MIN = 60
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 노드별 최대 점수 ────────────────────────────────────────────
SCORE_VOLATILITY_MAX  = 40   # 변동성 돌파 (돌파여유율에 따라 0~40 비례)
SCORE_AD_LINE         = 15   # AD Line 상승 시 고정 가산
SCORE_CANDLE_MAX      = 10   # 캔들 패턴 (해머 +10 / 그 외 0)
SCORE_STRONG_BULL     = 15   # 60분봉 강한 양봉 감지 시 고정 가산
SCORE_LLM_MAX         = 10   # LLM 뉴스 감성 (bullish=10 / neutral=5 / bearish=0)
SCORE_DART_MAX        = 10   # DART 공시 (긍정=+10 / 중립=0 / 부정=-10)
SCORE_WATCHLIST       = 10   # 관심종목 등록 시 고정 가산

SCORE_TOTAL_MAX = (
    SCORE_VOLATILITY_MAX
    + SCORE_AD_LINE
    + SCORE_CANDLE_MAX
    + SCORE_STRONG_BULL
    + SCORE_LLM_MAX
    + SCORE_DART_MAX
    + SCORE_WATCHLIST
)  # 110

# ── BUY 판정 임계값 ─────────────────────────────────────────────
# strategy_config.CONFIRM_SCORE_MIN 을 동적으로 읽되,
# import 실패 시 기본값 60으로 fallback
try:
    import strategy_config as _sc
    BUY_THRESHOLD: int = _sc.CONFIRM_SCORE_MIN
except Exception:
    BUY_THRESHOLD: int = 60

# ── 조기종료 게이트 임계값 ───────────────────────────────────────
# 각 게이트에서 이 점수 미만이면 남은 노드를 건너뛰고 SKIP 처리
VOLATILITY_GATE = 10   # Gate 1: 변동성 돌파 단독 점수 하한
AD_LINE_GATE    = 15   # Gate 2: volatility + ad_line 합산 하한
TECH_GATE       = 25   # Gate 3: 기술적 4개 합산 하한 (외부 API 진입 기준)
