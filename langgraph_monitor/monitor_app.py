"""
LangGraph 파이프라인 모니터링 UI
streamlit run langgraph_monitor/monitor_app.py
"""
import sys
import os
import pandas as pd

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

# ── 노드 정의 ────────────────────────────────────────────────────

NODE_DEFS = [
    {"key": "volatility", "label": "변동성 돌파", "score_key": "volatility_score", "elapsed_key": "volatility_elapsed", "max_score": 40, "icon": "📈"},
    {"key": "ad_line",    "label": "AD Line",      "score_key": "ad_line_score",    "elapsed_key": "ad_line_elapsed",    "max_score": 15, "icon": "〰️"},
    {"key": "news",       "label": "뉴스 감성",    "score_key": "news_score",       "elapsed_key": "news_elapsed",       "max_score": 10, "icon": "📰"},
    {"key": "dart",       "label": "DART 공시",    "score_key": "dart_score",       "elapsed_key": "dart_elapsed",       "max_score": 10, "icon": "📋"},
    {"key": "scoring",    "label": "스코어 집계",  "score_key": "total_score",      "elapsed_key": "scoring_elapsed",    "max_score": 75, "icon": "🎯"},
]

THRESHOLD = 50  # BUY 판정 임계 점수


# ── 노드 카드 렌더링 헬퍼 ────────────────────────────────────────

def _render_node_card(container, nd: dict, status: str, score=None, elapsed=None):
    """주어진 st container(또는 empty placeholder)에 노드 카드를 그린다."""
    max_s = nd["max_score"]
    badge = {
        "waiting": "⬜ 대기 중",
        "running": "🔄 실행 중...",
        "done":    "✅ 완료",
        "error":   "❌ 오류",
    }.get(status, "—")

    with container.container(border=True):
        col_icon, col_info = st.columns([1, 5])
        with col_icon:
            st.markdown(f"## {nd['icon']}")
        with col_info:
            st.markdown(f"**{nd['label']}**")
            st.caption(badge)

        if status == "done" and score is not None:
            ratio = min(score / max_s, 1.0) if max_s else 0.0
            st.progress(ratio, text=f"점수: **{score}** / {max_s}")
        elif status == "running":
            st.progress(0.0, text="분석 중...")
        else:
            st.progress(0.0, text="—")

        if elapsed is not None:
            st.caption(f"⏱ {elapsed:.3f}초")


# ── 최종 판단 렌더링 ─────────────────────────────────────────────

def _render_final(placeholder, final_state: dict):
    decision = final_state.get("decision")
    reason   = final_state.get("reason", "—")
    total    = final_state.get("total_score", 0)

    with placeholder.container():
        st.divider()
        st.markdown("### 최종 판단")

        if decision == "BUY":
            st.success(f"## 🟢 BUY")
        elif decision == "SKIP":
            st.warning(f"## 🔴 SKIP")
        else:
            st.info("판단 없음")

        st.markdown(f"**근거:** {reason}")

        st.markdown("#### 점수 분해")
        rows = []
        for nd in NODE_DEFS[:-1]:
            s = final_state.get(nd["score_key"])
            rows.append({
                "노드":  nd["icon"] + " " + nd["label"],
                "점수":  s if s is not None else "—",
                "최대":  nd["max_score"],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.metric("종합 점수", f"{total} / 75",
                  delta="BUY" if decision == "BUY" else "SKIP")


# ── 메인 앱 ──────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="LangGraph 파이프라인 모니터",
        page_icon="🤖",
        layout="wide",
    )

    st.title("🤖 LangGraph 파이프라인 모니터")
    st.caption("종목 코드를 입력하고 파이프라인을 실행하면 각 분석 노드의 진행 상황을 실시간으로 확인합니다.")

    # ── 사이드바 ──
    with st.sidebar:
        st.header("⚙️ 설정")
        ticker = st.text_input("종목 코드", value="005930", placeholder="예: 005930")
        run_btn = st.button("▶ 파이프라인 실행", type="primary", use_container_width=True)

        st.divider()
        st.markdown(f"""
**파이프라인 순서**
1. 📈 변동성 돌파 (max 40점)
2. 〰️ AD Line (max 15점)
3. 📰 뉴스 감성 (max 10점)
4. 📋 DART 공시 (max 10점)
5. 🎯 스코어 집계 (합산 75점)

> **BUY** 기준: 종합 {THRESHOLD}점 이상
""")

    if not run_btn:
        st.info("왼쪽 사이드바에서 종목 코드를 입력하고 **파이프라인 실행**을 누르세요.")
        return

    ticker = ticker.strip()
    if not ticker:
        st.warning("종목 코드를 입력하세요.")
        return

    # ── 노드 카드 영역 (placeholder per node) ──
    st.markdown(f"### `{ticker}` 분석 파이프라인 실행 중...")
    st.markdown("#### 노드 실행 현황")
    node_cols = st.columns(len(NODE_DEFS))
    placeholders = []
    for i, nd in enumerate(NODE_DEFS):
        ph = node_cols[i].empty()
        _render_node_card(ph, nd, "waiting")
        placeholders.append(ph)

    # 결과 placeholder (최종 판단)
    result_placeholder = st.empty()

    # ── 파이프라인 스트리밍 실행 ──
    from graph import build_graph

    app = build_graph()
    current_state: dict = {"ticker": ticker}

    # 현재 실행 중인 노드 인덱스 추적
    node_keys = [nd["key"] for nd in NODE_DEFS]

    try:
        for chunk in app.stream(current_state, stream_mode="updates"):
            for node_key, updates in chunk.items():
                if node_key not in node_keys:
                    continue
                idx = node_keys.index(node_key)
                nd  = NODE_DEFS[idx]

                # 이전 노드들은 done 유지 (이미 렌더됨)
                # 현재 노드를 done으로 업데이트
                score   = updates.get(nd["score_key"])
                elapsed = updates.get(nd["elapsed_key"])
                _render_node_card(placeholders[idx], nd, "done", score, elapsed)

                # 다음 노드를 running으로 표시
                if idx + 1 < len(NODE_DEFS):
                    _render_node_card(placeholders[idx + 1], NODE_DEFS[idx + 1], "running")

                # state 누적
                current_state.update(updates)

    except Exception as e:
        st.error(f"파이프라인 오류: {e}")
        return

    # ── 최종 판단 렌더링 ──
    _render_final(result_placeholder, current_state)
    st.success("✅ 파이프라인 완료")


# ── app.py 탭에서 호출하는 함수 ─────────────────────────────────

def render_pipeline_monitor_tab():
    """
    app.py의 "🔬 파이프라인 모니터" 탭 본문.
    st.session_state["screen_results"] 에서 상위 5종목을 읽어 선택 UI를 제공한다.
    """
    import os, sys
    # langgraph_monitor/ 폴더를 sys.path에 추가 (graph.py import용)
    _mon_dir = os.path.dirname(os.path.abspath(__file__))
    if _mon_dir not in sys.path:
        sys.path.insert(0, _mon_dir)

    st.subheader("🔬 파이프라인 모니터")
    st.caption("스크리닝 상위 종목을 선택해 LangGraph 분석 노드를 실행합니다. (Mock 데이터)")

    # ── 종목 선택 ──
    screen_results = st.session_state.get("screen_results") or []
    top5 = screen_results[:5]

    col_sel, col_manual = st.columns([3, 2])
    with col_sel:
        if top5:
            options = [f"{s['code']}  {s['name']}" for s in top5]
            sel_label = st.selectbox("스크리닝 상위 종목", options, key="pm_sel_stock")
            ticker = sel_label.split()[0]
        else:
            st.info("스크리닝 결과가 없습니다. 스크리닝 탭에서 먼저 실행하세요.")
            ticker = ""
    with col_manual:
        manual = st.text_input("직접 입력 (선택 덮어씀)", placeholder="예: 005930", key="pm_manual")
        if manual.strip():
            ticker = manual.strip()

    run_btn = st.button("▶ 분석 실행", type="primary", disabled=not ticker, key="pm_run")

    if not run_btn or not ticker:
        st.markdown("""
---
**파이프라인 순서**

| 순서 | 노드 | 최대 점수 |
|------|------|-----------|
| 1 | 📈 변동성 돌파 | 40점 |
| 2 | 〰️ AD Line | 15점 |
| 3 | 📰 뉴스 감성 | 10점 |
| 4 | 📋 DART 공시 | 10점 |
| 5 | 🎯 스코어 집계 | 75점 합산 |

> **BUY** 기준: 종합 **50점 이상**
""")
        return

    # ── 파이프라인 실행 ──
    st.markdown(f"### `{ticker}` 분석 파이프라인")
    st.markdown("#### 노드 실행 현황")

    node_cols = st.columns(len(NODE_DEFS))
    placeholders = []
    for i, nd in enumerate(NODE_DEFS):
        ph = node_cols[i].empty()
        _render_node_card(ph, nd, "waiting")
        placeholders.append(ph)

    result_placeholder = st.empty()
    node_keys = [nd["key"] for nd in NODE_DEFS]
    current_state: dict = {"ticker": ticker}

    try:
        from graph import build_graph
        app_graph = build_graph()

        for chunk in app_graph.stream(current_state, stream_mode="updates"):
            for node_key, updates in chunk.items():
                if node_key not in node_keys:
                    continue
                idx  = node_keys.index(node_key)
                nd   = NODE_DEFS[idx]
                score   = updates.get(nd["score_key"])
                elapsed = updates.get(nd["elapsed_key"])
                _render_node_card(placeholders[idx], nd, "done", score, elapsed)
                if idx + 1 < len(NODE_DEFS):
                    _render_node_card(placeholders[idx + 1], NODE_DEFS[idx + 1], "running")
                current_state.update(updates)

    except Exception as e:
        st.error(f"파이프라인 오류: {e}")
        import traceback; st.code(traceback.format_exc())
        return

    _render_final(result_placeholder, current_state)
    st.success("✅ 파이프라인 완료")


if __name__ == "__main__":
    main()
