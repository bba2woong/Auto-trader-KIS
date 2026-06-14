"""
파이프라인 모니터 탭 -- app.py에서 호출
render_pipeline_monitor_tab() 함수를 import해서 사용.
"""
import sys
import os
import pandas as pd
import streamlit as st

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from score_config import (
    SCORE_VOLATILITY_MAX, SCORE_AD_LINE, SCORE_CANDLE_MAX,
    SCORE_STRONG_BULL, SCORE_LLM_MAX, SCORE_DART_MAX, SCORE_WATCHLIST,
    SCORE_TOTAL_MAX, BUY_THRESHOLD,
    VOLATILITY_GATE, AD_LINE_GATE, TECH_GATE,
)

# -- 노드 정의 (gate 필드: 해당 노드 직후에 걸리는 게이트 설명) ---

NODE_DEFS = [
    {"key": "volatility",  "label": "변동성 돌파", "score_key": "volatility_score",  "elapsed_key": "volatility_elapsed",  "max_score": SCORE_VOLATILITY_MAX, "icon": "📈", "gate": f"Gate 1 ≥{VOLATILITY_GATE}"},
    {"key": "ad_line",     "label": "AD Line",      "score_key": "ad_line_score",     "elapsed_key": "ad_line_elapsed",     "max_score": SCORE_AD_LINE,        "icon": "〰️", "gate": f"Gate 2 합산 ≥{AD_LINE_GATE}"},
    {"key": "candle",      "label": "캔들 패턴",    "score_key": "candle_score",      "elapsed_key": "candle_elapsed",      "max_score": SCORE_CANDLE_MAX,     "icon": "🕯️", "gate": None},
    {"key": "strong_bull", "label": "60분봉 강봉",  "score_key": "strong_bull_score", "elapsed_key": "strong_bull_elapsed", "max_score": SCORE_STRONG_BULL,    "icon": "💪", "gate": f"Gate 3 합산 ≥{TECH_GATE}"},
    {"key": "news",        "label": "뉴스 감성",    "score_key": "news_score",        "elapsed_key": "news_elapsed",        "max_score": SCORE_LLM_MAX,        "icon": "📰", "gate": None},
    {"key": "dart",        "label": "DART 공시",    "score_key": "dart_score",        "elapsed_key": "dart_elapsed",        "max_score": SCORE_DART_MAX,       "icon": "📋", "gate": None},
    {"key": "watchlist",   "label": "관심종목",     "score_key": "watchlist_score",   "elapsed_key": "watchlist_elapsed",   "max_score": SCORE_WATCHLIST,      "icon": "⭐", "gate": None},
    {"key": "scoring",     "label": "스코어 집계",  "score_key": "total_score",       "elapsed_key": "scoring_elapsed",     "max_score": SCORE_TOTAL_MAX,      "icon": "🎯", "gate": None},
]


# -- 내부 렌더 헬퍼 ------------------------------------------------------

def _render_node_card(container, nd: dict, status: str, score=None, elapsed=None):
    """
    status:
      waiting  -- 회색 대기
      running  -- 파란 스피너
      done     -- 초록 완료 + 점수 bar
      skipped  -- 회색 건너뜀
      error    -- 빨간 오류
    """
    max_s = nd["max_score"]
    badge = {
        "waiting": "□ 대기 중",
        "running": "🔄 실행 중...",
        "done":    "✅ 완료",
        "skipped": "⏭ 건너뜀",
        "error":   "❌ 오류",
    }.get(status, "--")

    with container.container(border=True):
        col_icon, col_info = st.columns([1, 5])
        with col_icon:
            st.markdown(f"## {nd['icon']}")
        with col_info:
            st.markdown(f"**{nd['label']}**")
            st.caption(badge)

        if status == "done" and score is not None:
            ratio = max(0.0, min(score / max_s, 1.0)) if max_s else 0.0
            score_text = (
                f"점수: **{score:+g}** / {max_s}"
                if nd["key"] == "dart"
                else f"점수: **{score}** / {max_s}"
            )
            st.progress(ratio, text=score_text)
        elif status == "running":
            st.progress(0.0, text="분석 중...")
        elif status == "skipped":
            st.progress(0.0, text="조기종료로 건너뜀")
        else:
            st.progress(0.0, text="--")

        if elapsed is not None:
            st.caption(f"⏱ {elapsed:.3f}초")


def _render_final(placeholder, final_state: dict, skipped_keys: set):
    decision = final_state.get("decision")
    reason   = final_state.get("reason", "--")
    total    = final_state.get("total_score", 0)

    with placeholder.container():
        st.divider()
        st.markdown("### 최종 판단")

        if decision == "BUY":
            st.success("## 🟢 BUY")
        elif decision == "SKIP":
            st.warning("## 🔴 SKIP")
        else:
            st.info("판단 없음")

        st.markdown(f"**근거:** {reason}")

        if skipped_keys:
            st.caption(f"⏭ 건너뜀 노드: {', '.join(skipped_keys)}")

        st.markdown("#### 점수 분해")
        rows = []
        for nd in NODE_DEFS[:-1]:
            s = final_state.get(nd["score_key"])
            skipped = nd["key"] in skipped_keys
            rows.append({
                "노드":  nd["icon"] + " " + nd["label"] + (" (건너뜀)" if skipped else ""),
                "점수":  "⏭" if skipped else (s if s is not None else "--"),
                "최대":  nd["max_score"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.metric("종합 점수", f"{total} / {SCORE_TOTAL_MAX}",
                  delta="BUY" if decision == "BUY" else "SKIP")


# -- 퍼블릭 탭 함수 ------------------------------------------------------

def render_pipeline_monitor_tab():
    """app.py의 '🔬 파이프라인 모니터' 탭 본문."""
    st.subheader("🔬 파이프라인 모니터")
    st.caption(
        f"총 {SCORE_TOTAL_MAX}점 기준, BUY ≥{BUY_THRESHOLD}점 | "
        f"조기종료 게이트: Gate1(변동성 <{VOLATILITY_GATE}) → "
        f"Gate2(합산 <{AD_LINE_GATE}) → Gate3(합산 <{TECH_GATE})"
    )

    # -- 종목 선택 --
    screen_results = st.session_state.get("screen_results") or []
    top5 = screen_results[:5]

    col_sel, col_manual = st.columns([3, 2])
    with col_sel:
        if top5:
            options = [f"{s['code']}  {s['name']}" for s in top5]
            sel_label = st.selectbox("스크리닝 상위 종목", options, key="pm_sel_stock")
            ticker = sel_label.split()[0]
        else:
            st.info("스크리닝 결과가 없습니다. 🔍 스크리닝 탭에서 먼저 실행하세요.")
            ticker = ""
    with col_manual:
        manual = st.text_input("직접 입력 (선택 덮어씀)", placeholder="예: 005930", key="pm_manual")
        if manual.strip():
            ticker = manual.strip()

    run_btn = st.button("▶ 분석 실행", type="primary", disabled=not ticker, key="pm_run")

    if not run_btn or not ticker:
        rows_md = "\n".join(
            f"| {i+1} | {nd['icon']} {nd['label']} | {nd['max_score']}점 | {nd['gate'] or ''} |"
            for i, nd in enumerate(NODE_DEFS[:-1])
        )
        st.markdown(f"""
---
| 순서 | 노드 | 최대 점수 | 게이트 |
|:----:|------|:---------:|--------|
{rows_md}
| **합계** | | **{SCORE_TOTAL_MAX}점** | |

> **BUY** 기준: 종합 **{BUY_THRESHOLD}점 이상** | 게이트 미달 시 이후 노드 건너뜀 ⏭
""")
        return

    # -- 파이프라인 실행 --
    st.markdown(f"### `{ticker}` 분석 파이프라인")
    st.markdown("#### 노드 실행 현황")

    analysis_nodes = NODE_DEFS[:-1]
    scoring_nd     = NODE_DEFS[-1]

    row1_cols = st.columns(4)
    row2_cols = st.columns(4)
    all_cols  = row1_cols + row2_cols

    placeholders = []
    for i, nd in enumerate(analysis_nodes):
        ph = all_cols[i].empty()
        _render_node_card(ph, nd, "waiting")
        placeholders.append(ph)

    scoring_ph = all_cols[7].empty()
    _render_node_card(scoring_ph, scoring_nd, "waiting")
    placeholders.append(scoring_ph)

    result_placeholder = st.empty()
    node_keys     = [nd["key"] for nd in NODE_DEFS]
    done_keys: set = set()
    current_state: dict = {"ticker": ticker}

    try:
        from graph import build_graph
        app_graph = build_graph()

        for chunk in app_graph.stream(current_state, stream_mode="updates"):
            for node_key, updates in chunk.items():
                if node_key not in node_keys:
                    continue

                idx = node_keys.index(node_key)

                # 이 노드 직전까지 아직 done/skipped 안 된 노드를 skipped 처리
                for prev_idx in range(idx):
                    if node_keys[prev_idx] not in done_keys:
                        _render_node_card(placeholders[prev_idx], NODE_DEFS[prev_idx], "skipped")
                        done_keys.add(node_keys[prev_idx])

                # 현재 노드 완료
                nd      = NODE_DEFS[idx]
                score   = updates.get(nd["score_key"])
                elapsed = updates.get(nd["elapsed_key"])
                _render_node_card(placeholders[idx], nd, "done", score, elapsed)
                done_keys.add(node_key)

                # 다음 분석 노드 running 예고 (scoring 제외)
                next_idx = idx + 1
                if next_idx < len(NODE_DEFS) - 1 and node_keys[next_idx] not in done_keys:
                    _render_node_card(placeholders[next_idx], NODE_DEFS[next_idx], "running")

                current_state.update(updates)

    except Exception as e:
        st.error(f"파이프라인 오류: {e}")
        import traceback
        st.code(traceback.format_exc())
        return

    # 스트림 종료 후 미처리 노드(scoring 제외)를 skipped 처리
    skipped_keys: set = set()
    for i, nd in enumerate(NODE_DEFS[:-1]):
        if nd["key"] not in done_keys:
            _render_node_card(placeholders[i], nd, "skipped")
            skipped_keys.add(nd["key"])

    _render_final(result_placeholder, current_state, skipped_keys)
    st.success("✅ 파이프라인 완료")


# ── 컴팩트 렌더 (트레이딩 탭용) ─────────────────────────────────

def _render_compact_card(container, nd: dict, status: str, score=None, elapsed=None):
    """
    트레이딩 탭 1행 8열 컴팩트 카드.
    상태는 색상(테두리/텍스트)으로만 구분, 이모지 없음.
    """
    max_s = nd["max_score"]

    # 상태별 스타일
    if status == "done":
        # 점수가 max의 1/3 미만이면 빨간 테두리, 이상이면 초록 테두리
        low_score = (score is not None) and (max_s > 0) and (score < max_s / 3)
        border_color = "#dc3545" if low_score else "#28a745"
        status_text  = "완료"
        text_color   = border_color
    elif status == "running":
        border_color = "#007bff"   # 파랑
        status_text  = "실행중"
        text_color   = "#007bff"
    elif status == "skipped":
        border_color = "#6c757d"   # 회색
        status_text  = "⏭건너뜀"
        text_color   = "#6c757d"
    elif status == "error":
        border_color = "#dc3545"   # 빨강
        status_text  = "오류"
        text_color   = "#dc3545"
    else:   # waiting
        border_color = "#ced4da"   # 연회색
        status_text  = "대기"
        text_color   = "#6c757d"

    with container.container():
        st.markdown(
            f"""<div style="border:2px solid {border_color};border-radius:6px;
                            padding:6px 4px;text-align:center;min-height:90px">
                <div style="font-size:0.72em;font-weight:600;color:#333;
                            white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                    {nd['label']}
                </div>
                <div style="font-size:0.68em;color:{text_color};margin:2px 0">
                    {status_text}
                </div>
                <div style="font-size:0.9em;font-weight:700;color:{text_color}">
                    {"--" if score is None
                      else (f"{score:+g}" if nd["key"] == "dart" else str(score))}
                    <span style="font-size:0.65em;color:#888">/{max_s}</span>
                </div>
                <div style="font-size:0.65em;color:#888">
                    {f"{elapsed:.2f}s" if elapsed is not None else ""}
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        # 진행바 (완료/건너뜀이 아닐 때만 숨김)
        if status == "done" and score is not None:
            ratio = max(0.0, min(score / max_s, 1.0)) if max_s else 0.0
            st.progress(ratio)
        elif status == "running":
            st.progress(0.0)


def _run_pipeline_stream(ticker: str, placeholders: list, node_keys: list,
                         done_keys: set, current_state: dict,
                         card_fn) -> tuple:
    """
    LangGraph 스트리밍 공통 실행 로직.
    card_fn(container, nd, status, score, elapsed) 으로 카드를 그린다.
    반환: (current_state, skipped_keys, error_msg)
    """
    try:
        from graph import build_graph
        app_graph = build_graph()

        for chunk in app_graph.stream(current_state, stream_mode="updates"):
            for node_key, updates in chunk.items():
                if node_key not in node_keys:
                    continue
                idx = node_keys.index(node_key)

                for prev_idx in range(idx):
                    if node_keys[prev_idx] not in done_keys:
                        card_fn(placeholders[prev_idx], NODE_DEFS[prev_idx], "skipped")
                        done_keys.add(node_keys[prev_idx])

                nd      = NODE_DEFS[idx]
                score   = updates.get(nd["score_key"])
                elapsed = updates.get(nd["elapsed_key"])
                card_fn(placeholders[idx], nd, "done", score, elapsed)
                done_keys.add(node_key)

                next_idx = idx + 1
                if next_idx < len(NODE_DEFS) - 1 and node_keys[next_idx] not in done_keys:
                    card_fn(placeholders[next_idx], NODE_DEFS[next_idx], "running")

                current_state.update(updates)

    except Exception as e:
        import traceback
        return current_state, set(), traceback.format_exc()

    skipped_keys: set = set()
    for i, nd in enumerate(NODE_DEFS[:-1]):
        if nd["key"] not in done_keys:
            card_fn(placeholders[i], nd, "skipped")
            skipped_keys.add(nd["key"])

    return current_state, skipped_keys, None


def render_pipeline_monitor_compact():
    """
    트레이딩 탭용 컴팩트 파이프라인 모니터.
    8개 노드를 1행 8열로 표시, 카드 크기 최소화.
    """
    st.markdown(
        f"#### 🔬 파이프라인 분석 &nbsp;"
        f"<span style='font-size:0.75em;color:gray'>"
        f"총{SCORE_TOTAL_MAX}점 · BUY≥{BUY_THRESHOLD}점 · "
        f"Gate1<{VOLATILITY_GATE} / Gate2합산<{AD_LINE_GATE} / Gate3합산<{TECH_GATE}</span>",
        unsafe_allow_html=True,
    )

    # 종목 선택
    screen_results = st.session_state.get("screen_results") or []
    top5 = screen_results[:5]

    c_sel, c_manual, c_btn = st.columns([3, 2, 1])
    with c_sel:
        if top5:
            options = [f"{s['code']}  {s['name']}" for s in top5]
            sel_label = st.selectbox(
                "스크리닝 상위 종목", options,
                key="pm_compact_sel", label_visibility="collapsed"
            )
            ticker = sel_label.split()[0]
        else:
            st.caption("스크리닝 결과 없음")
            ticker = ""
    with c_manual:
        manual = st.text_input(
            "직접 입력", placeholder="종목코드",
            key="pm_compact_manual", label_visibility="collapsed"
        )
        if manual.strip():
            ticker = manual.strip()
    with c_btn:
        run_btn = st.button(
            "▶ 분석", type="primary",
            disabled=not ticker, key="pm_compact_run",
            use_container_width=True,
        )

    if not run_btn or not ticker:
        return

    # 8칸 1행 레이아웃
    cols = st.columns(8)
    placeholders = [cols[i].empty() for i in range(8)]

    # 초기 상태 — 전체 대기
    for i, nd in enumerate(NODE_DEFS):
        _render_compact_card(placeholders[i], nd, "waiting")

    result_ph    = st.empty()
    node_keys    = [nd["key"] for nd in NODE_DEFS]
    done_keys: set = set()
    current_state: dict = {"ticker": ticker}

    final_state, skipped_keys, err = _run_pipeline_stream(
        ticker, placeholders, node_keys, done_keys, current_state,
        _render_compact_card,
    )

    if err:
        st.error(f"파이프라인 오류: {err}")
        return

    # 최종 판단 (인라인 — 별도 divider 없이)
    decision = final_state.get("decision")
    reason   = final_state.get("reason", "--")
    total    = final_state.get("total_score", 0)

    if decision == "BUY":
        result_ph.success(f"🟢 **BUY** | {ticker} | 종합 {total}/{SCORE_TOTAL_MAX}점 | {reason}")
    else:
        result_ph.warning(f"🔴 **SKIP** | {ticker} | 종합 {total}/{SCORE_TOTAL_MAX}점 | {reason}")
