"""
KIS Auto Trader — Streamlit GUI
실행: streamlit run app.py
"""
import os
import sys

# config 임포트 전에 TRADING_MODE 설정 필요
os.environ.setdefault("TRADING_MODE", "mock")
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import threading

# ──────────────────────────────────────────
# 로그 캡처 (scheduler print → 화면 출력)
# ──────────────────────────────────────────

class _LogBuffer:
    """스레드 안전 로그 버퍼 (전역 공유)"""
    REPEAT_KW    = ["[Auth]", "대기 중", "스크리닝까지", "수집 중",
                    "캐시된 토큰", "포지션 풀"]
    IMPORTANT_KW = ["매수", "매도", "손절", "트레일링", "스크리닝 완료",
                    "스크리닝 시작", "포지션 오픈", "포지션 종료",
                    "강제 청산", "자동 매수", "오류", "실패", "경고",
                    "장 시작", "장 종료", "HTS수동매도"]

    def __init__(self):
        self._lock   = threading.Lock()
        self.status  = ""
        self.history = []

    def update_status(self, msg):
        with self._lock:
            self.status = msg.rstrip()

    def add_history(self, msg):
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.history.append(f"[{ts}] {msg.rstrip()}")
            if len(self.history) > 200:
                self.history = self.history[-200:]

    def get_status(self):
        with self._lock: return self.status

    def get_history(self):
        with self._lock: return list(self.history)

    def clear(self):
        with self._lock:
            self.status  = ""
            self.history = []


class _LogCapture:
    """sys.stdout 가로채기 — 반복성/중요 이벤트 분류"""
    def __init__(self, original, buf: _LogBuffer):
        self.original = original
        self.buf      = buf
        self._line    = ""

    def write(self, msg):
        self.original.write(msg)
        text   = self._line + msg
        lines  = text.split("\n")
        self._line = lines[-1]
        for line in lines[:-1]:
            self._route(line)

    def _route(self, line):
        s = line.strip()
        if not s:
            return
        is_repeat = (
            any(k in s for k in self.buf.REPEAT_KW) or "\r" in s
        )
        if is_repeat:
            self.buf.update_status(s)
        elif any(k in s for k in self.buf.IMPORTANT_KW):
            self.buf.add_history(s)

    def flush(self):  self.original.flush()
    def isatty(self): return False


# 모듈 레벨 전역 버퍼 (스레드 간 공유)
_log_buf = _LogBuffer()


# ──────────────────────────────────────────
# 트레이딩 시작/정지 헬퍼
# ──────────────────────────────────────────

def _start_scheduler(mode: str):
    """config 재로드 → sys.stdout 교체 → scheduler 백그라운드 실행"""
    import config as cfg
    cfg.reload(mode)
    os.environ["TRADING_MODE"] = mode

    _log_buf.clear()
    capture = _LogCapture(sys.stdout, _log_buf)
    sys.stdout = capture

    def _run():
        try:
            from scheduler import run_scheduler
            run_scheduler()
        except Exception as e:
            _log_buf.add_history(f"⚠️ 스케줄러 오류: {e}")
        finally:
            sys.stdout = capture.original
            st.session_state["trader_running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    st.session_state["trader_thread"]  = t
    st.session_state["trader_running"] = True
    st.session_state["trader_mode"]    = mode

# ──────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────
st.set_page_config(
    page_title="KIS Auto Trader",
    page_icon="📈",
    layout="wide",
)

st.title("📈 KIS Auto Trader")

# ──────────────────────────────────────────
# 사이드바 — 투자 모드 & 파라미터
# ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    trading_mode = st.radio(
        "투자 모드",
        ["mock", "real"],
        format_func=lambda x: "🟡 모의투자" if x == "mock" else "🔴 실전투자",
    )
    os.environ["TRADING_MODE"] = trading_mode
    import config as _cfg_mod
    if _cfg_mod.MODE != trading_mode:
        _cfg_mod.reload(trading_mode)

    st.divider()
    st.subheader("전략 파라미터")

    import strategy_config as sc

    k = st.slider(
        "K (변동성 계수)", 0.3, 0.7, sc.K, 0.05,
        help="목표가 = 시가 + 전일변동폭 × K\n낮을수록 진입 빠름 / 높을수록 안전",
    )
    invest_ratio_pct = st.slider(
        "투자 비율 (%)", 10, 100, int(sc.INVEST_RATIO * 100), 5,
        format="%d%%",
        help="예수금 중 1회 매매에 사용할 비율\n예) 50% → 예수금 1,000만원이면 500만원 투자",
    )
    invest_ratio = invest_ratio_pct / 100

    loss_rate = st.slider(
        "하드 손절 (%)", 0.5, 5.0, sc.LOSS_RATE * 100, 0.1,
        format="%.1f%%",
        help="매수가 기준 이 % 하락 시 무조건 손절\n트레일링 스탑과 무관하게 항상 작동",
    ) / 100

    trailing_rate = st.slider(
        "트레일링 스탑 (%)", 0.5, 5.0, sc.TRAILING_STOP_RATE * 100, 0.1,
        format="%.1f%%",
        help="고점 대비 이 % 하락 시 매도\n수익 중에 눌리면 자동 청산",
    ) / 100

    max_positions = st.slider(
        "최대 포지션 수", 1, 10, sc.MAX_POSITIONS, 1,
        help="동시에 보유할 수 있는 최대 종목 수\n예) 3개 → 투자금을 3등분해서 각 종목에 진입",
    )

    st.caption(f"포지션당 예산 = 예수금 × {invest_ratio_pct}% ÷ {max_positions}개")

    pool_size = st.slider(
        "코스피 풀 크기", 10, 200, sc.KOSPI_POOL_SIZE, 10,
        help="코스피200 중 상위 N개 종목을 스크리닝\n클수록 기회 많지만 속도 느림",
    )

    # 런타임 파라미터 반영 (파일 저장은 안 함 — 화면 내 미리보기용)
    sc.K                     = k
    sc.INVEST_RATIO          = invest_ratio
    sc.LOSS_RATE             = loss_rate
    sc.TRAILING_STOP_RATE    = trailing_rate
    sc.MAX_POSITIONS         = max_positions
    sc.KOSPI_POOL_SIZE       = pool_size

    st.divider()
    st.caption(f"모드: **{'모의' if trading_mode == 'mock' else '실전'}** | "
               f"Base URL: {os.environ.get('BASE_URL', '...')}")

# ──────────────────────────────────────────
# 탭
# ──────────────────────────────────────────
tab_screen, tab_trade, tab_backtest, tab_log, tab_config = st.tabs(
    ["🔍 스크리닝", "🚀 트레이딩", "📊 백테스팅", "📋 매매 로그", "⚙️ 파라미터 현황"]
)


# ══════════════════════════════════════════
# 탭 1: 스크리닝
# ══════════════════════════════════════════
with tab_screen:
    st.subheader("종목 스크리닝")
    st.caption("변동성 돌파 + AD Line + 캔들 패턴 + AI 점수(LLM/DART) 기반 매수 후보 탐색")

    col_btn1, col_btn2 = st.columns([3, 1])
    with col_btn1:
        run_screen_btn = st.button("▶ 스크리닝 실행", type="primary", use_container_width=True)
    with col_btn2:
        refresh_ai_btn = st.button("🔄 AI 캐시 갱신", use_container_width=True,
                                   help="Perplexity LLM 재분석 (API 비용 발생)")

    # AI 캐시 갱신
    if refresh_ai_btn:
        with st.spinner("AI 분석 중..."):
            try:
                from screener import build_screening_pool
                from scoring.scorer import refresh_cache
                pool = build_screening_pool()
                refresh_cache(pool, "수동갱신")
                st.success(f"AI 캐시 갱신 완료 ({len(pool)}개 종목)")
            except Exception as e:
                st.error(f"AI 캐시 갱신 실패: {e}")

    if run_screen_btn:
        prog_bar  = st.progress(0)
        prog_text = st.empty()

        def screen_cb(cur, total, name):
            prog_bar.progress(cur / total)
            prog_text.caption(f"🔍 스크리닝 중...  ({cur}/{total})  {name}")

        try:
            from screener import run_screening
            results = run_screening(progress_cb=screen_cb)

            # AI 점수 적용
            if sc.USE_AI_SCORING and results:
                prog_text.caption("🤖 AI 점수 계산 중...")
                from scoring.scorer import total_score, routing
                for s in results:
                    sd    = total_score(s)
                    route = routing(sd["total"])
                    s["ai_score"]   = sd["total"]
                    s["ai_tech"]    = sd["tech"]
                    s["ai_llm"]     = sd["llm"]
                    s["ai_dart"]    = sd["dart"]
                    s["ai_route"]   = route
                    s["llm_opinion"]= sd.get("llm_opinion", "")
                    s["llm_reason"] = sd.get("llm_reason", "")

                results.sort(key=lambda x: -x.get("ai_score", 0))

            prog_bar.progress(1.0)
            prog_text.caption(f"✅ 완료! {len(results)}개 종목 통과")
            st.session_state["screen_results"] = results

        except Exception as e:
            prog_text.empty()
            st.error(f"오류: {e}")
            import traceback; st.code(traceback.format_exc())

    results = st.session_state.get("screen_results")

    if results is None:
        st.info("스크리닝 실행 버튼을 누르세요.")
    elif not results:
        st.warning("조건 충족 종목이 없습니다.")
    else:
        grade_emoji = {"A": "🥇", "B": "🥈", "C": "🥉"}
        pat_label   = {"hammer": "🔨 해머", "hanging_man": "⚠️ 행잉맨", None: "—"}
        route_emoji = {"auto_buy": "🤖 자동매수", "confirm": "📱 확인필요", "skip": "⏭ 스킵"}

        rows = []
        for s in results:
            row = {
                "등급":      grade_emoji.get(s.get("grade","B"),"") + " " + s.get("grade","B"),
                "종목명":    s["name"],
                "코드":      s["code"],
                "현재가":    f"{s['현재가']:,}",
                "목표가":    f"{s['목표가']:,}",
                "여유율(%)": round(s["돌파여유율"], 2),
                "패턴":      pat_label.get(s.get("패턴")),
            }
            if sc.USE_AI_SCORING and "ai_score" in s:
                row["AI총점"]  = s["ai_score"]
                row["기술"]    = s["ai_tech"]
                row["LLM"]     = s["ai_llm"]
                row["DART"]    = s["ai_dart"]
                row["라우팅"]  = route_emoji.get(s.get("ai_route",""), s.get("ai_route",""))
                row["LLM의견"] = s.get("llm_opinion","")
                row["LLM근거"] = s.get("llm_reason","")
            rows.append(row)

        df = pd.DataFrame(rows)

        # AI 점수 컬럼 색상 강조
        if sc.USE_AI_SCORING and "AI총점" in df.columns:
            st.dataframe(
                df.style.background_gradient(subset=["AI총점"], cmap="RdYlGn"),
                use_container_width=True, hide_index=True
            )
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)

        # 요약
        n_auto = sum(1 for r in results if r.get("ai_route") == "auto_buy")
        n_conf = sum(1 for r in results if r.get("ai_route") == "confirm")
        n_skip = sum(1 for r in results if r.get("ai_route") == "skip")
        a_cnt  = sum(1 for r in results if r.get("grade") == "A")
        b_cnt  = sum(1 for r in results if r.get("grade") == "B")
        c_cnt  = sum(1 for r in results if r.get("grade") == "C")

        if sc.USE_AI_SCORING:
            st.success(
                f"총 {len(results)}개  |  "
                f"등급: A {a_cnt} / B {b_cnt} / C {c_cnt}  |  "
                f"라우팅: 🤖자동매수 {n_auto} / 📱확인 {n_conf} / ⏭스킵 {n_skip}"
            )
        else:
            st.success(f"총 {len(results)}개 (A:{a_cnt} / B:{b_cnt} / C:{c_cnt})")


# ══════════════════════════════════════════
# 탭 2: 트레이딩
# ══════════════════════════════════════════
with tab_trade:
    st.subheader("🚀 트레이딩")

    running  = st.session_state.get("trader_running", False)
    t_mode   = st.session_state.get("trader_mode", "—")
    t_thread = st.session_state.get("trader_thread")

    # 스레드가 죽었으면 상태 정리
    if running and t_thread and not t_thread.is_alive():
        st.session_state["trader_running"] = False
        running = False

    # ── 상태 표시 ──
    c1, c2, c3 = st.columns(3)
    c1.metric("실행 상태",   "🟢 실행 중" if running else "⚫ 정지 중")
    c2.metric("모드",        "🟡 모의투자" if t_mode == "mock"
                             else "🔴 실전투자" if t_mode == "real" else "—")
    c3.metric("당일 매매",   f"{st.session_state.get('trade_count', 0)}회")

    st.divider()

    # ── 실전투자 확인 체크박스 ──
    real_ok = st.checkbox(
        "⚠️ 실전투자임을 확인합니다. 실제 자금이 사용됩니다.",
        key="real_confirm"
    )

    # ── 버튼 ──
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("▶ 모의투자 시작", type="primary",
                     use_container_width=True, disabled=running):
            import config as _cfg
            _cfg.reload("mock")
            os.environ["TRADING_MODE"] = "mock"
            _start_scheduler("mock")
            st.rerun()

    with b2:
        real_btn_disabled = running or not real_ok
        if st.button("▶ 실전투자 시작",
                     use_container_width=True,
                     disabled=real_btn_disabled,
                     type="secondary"):
            st.warning("⚠️ 실전투자를 시작합니다. 실제 돈이 사용됩니다.")
            import config as _cfg
            _cfg.reload("real")
            os.environ["TRADING_MODE"] = "real"
            _start_scheduler("real")
            st.rerun()

    with b3:
        if st.button("⏹ 정지", use_container_width=True, disabled=not running):
            st.session_state["trader_running"] = False
            _log_buf.add_history("⏹ 정지 요청 — 현재 포지션 청산 후 종료됩니다.")

    if not running and t_mode != "—":
        st.info("정지 요청됨 — 현재 포지션 청산 후 종료됩니다.")

    st.divider()

    # ── 현재 config 확인 ──
    import config as _cfg_check
    st.caption(
        f"🔑 현재 API 모드: **{_cfg_check.MODE.upper()}**  |  "
        f"Base URL: `{_cfg_check.BASE_URL}`"
    )

    # ── 실시간 로그 (st.fragment으로 자동 갱신) ──
    @st.fragment(run_every=3)
    def _trade_log_fragment():
        # 단일 상태 줄
        status = _log_buf.get_status()
        st.caption(f"📡 {status}" if status else "📡 대기 중...")

        # 중요 이벤트 누적 로그
        history = _log_buf.get_history()
        col_log, col_clear = st.columns([5, 1])
        with col_clear:
            if st.button("🗑 로그 지우기", key="clear_log"):
                _log_buf.clear()
        with col_log:
            if history:
                st.code("\n".join(reversed(history[-50:])),  # 최신 50줄, 최신이 위
                        language=None)
            else:
                st.info("중요 이벤트가 여기에 표시됩니다.")

    _trade_log_fragment()


# ══════════════════════════════════════════
# 탭 3: 백테스팅
# ══════════════════════════════════════════
import numpy as np
import json
from pathlib import Path

LOG_DIR = Path(__file__).parent / "backtest" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def _calc_summary(result):
    trades   = result["trades"]
    init_cap = result["initial_capital"]
    fin_cap  = result["final_capital"]
    equity   = result["equity_curve"]
    ret      = (fin_cap - init_cap) / init_cap * 100
    wins     = [t for t in trades if t["pnl_rate"] > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    peak, mdd = equity[0], 0.0
    for v in equity:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < mdd: mdd = dd
    return ret, len(trades), win_rate, mdd

def _save_log(entry: dict):
    log_file = LOG_DIR / f"backtest_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def _range_values(use_range, single, rmin, rmax, rstep):
    """범위 모드면 arange 반환, 단일 모드면 [single]"""
    if use_range:
        vals = np.arange(rmin, rmax + rstep / 2, rstep)
        return [round(float(v), 4) for v in vals]
    return [single]

def _make_cb(prog_bar, prog_text, label):
    def cb(cur, total, name):
        prog_bar.progress(cur / total)
        prog_text.caption(f"📥 {label}  ({cur}/{total})  {name}")
    return cb

def _build_stock_list_ui(pool_option, custom_codes):
    if pool_option == "kospi":
        from screener import build_screening_pool
        return build_screening_pool()
    elif pool_option == "watchlist":
        from watchlist import WATCHLIST_CODES
        from screener import KOSPI_200
        km = {s["code"]: s["name"] for s in KOSPI_200}
        return [{"code": c, "name": km.get(c, c)} for c in WATCHLIST_CODES]
    else:
        codes = [c.strip() for c in custom_codes.split(",") if c.strip()]
        return [{"code": c, "name": c} for c in codes]

def _show_single_result(result):
    """단일 파라미터 결과 상세 표시"""
    trades = result["trades"]
    ret, n_trades, win_rate, mdd = _calc_summary(result)
    init_cap = result["initial_capital"]
    equity   = result["equity_curve"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("수익률",    f"{ret:+.2f}%")
    m2.metric("총 거래",   f"{n_trades}회")
    m3.metric("승률",      f"{win_rate:.1f}%")
    m4.metric("최대 낙폭", f"{mdd:.2f}%")

    if len(equity) > 1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=equity, mode="lines", name="자산",
            line=dict(color="#00b4d8", width=2),
            fill="tozeroy", fillcolor="rgba(0,180,216,0.1)",
        ))
        fig.add_hline(y=init_cap, line_dash="dash", line_color="gray",
                      annotation_text="초기 자금")
        fig.update_layout(title="자산 곡선", xaxis_title="거래 횟수",
                          yaxis_title="자산 (원)", height=320,
                          margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

    if trades:
        st.subheader("거래 내역")
        emoji = {"트레일링스탑":"📉","손절":"🔻","강제청산":"⏰","익절":"✅","종가청산":"🔔"}
        rows = []
        for t in trades:
            en = t.get("entry_time",""); ex = t.get("exit_time","")
            rows.append({
                "날짜":   t.get("date") or result.get("date","—"),
                "진입":   f"{en[:2]}:{en[2:4]}" if en else "—",
                "청산":   f"{ex[:2]}:{ex[2:4]}" if ex else "—",
                "종목":   t["name"],
                "매수가": t["buy_price"],
                "매도가": t["sell_price"],
                "수익률": f"{t['pnl_rate']*100:+.2f}%",
                "사유":   emoji.get(t["reason"],"") + " " + t["reason"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def _pnl_color(val):
    """
    수익률 셀 색상
    양수 → 청색 (파랑), 음수 → 적색 (빨강)
    0.5%마다 한 단계씩 채도 증가, 최대 ±5% 기준 (10단계)
    """
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return "background-color: white"

    steps     = min(10, max(1, int(abs(v) / 0.5) + (1 if abs(v) % 0.5 > 0.05 else 0)))
    intensity = steps / 10.0   # 0.1 ~ 1.0

    base      = int(255 * (1 - intensity * 0.85))
    text_col  = "white" if intensity >= 0.6 else "#111111"

    if v > 0:
        color = f"rgb({base},{base},240)"
    else:
        color = f"rgb(255,{base},{base})"

    return f"background-color: {color}; color: {text_col}"


def _show_grid_result(grid_rows):
    """파라미터 범위 그리드 결과 테이블"""
    st.subheader(f"파라미터 최적화 결과  ({len(grid_rows)}개 조합)")
    df       = pd.DataFrame(grid_rows)
    sort_col = "전체수익률(%)" if "전체수익률(%)" in df.columns else "수익률(%)"
    df       = df.sort_values(sort_col, ascending=False)

    fixed      = {"K","손절(%)","트레일(%)","전체수익률(%)","수익률(%)","거래수","승률(%)","MDD(%)"}
    stock_cols = [c for c in df.columns if c not in fixed]
    color_cols = [sort_col] + stock_cols   # 수익률 관련 컬럼에 색상 적용

    st.dataframe(
        df.style.map(_pnl_color, subset=color_cols),
        use_container_width=True, hide_index=True,
    )
    best  = df.iloc[0]
    k_str = f"K: {best['K']} | " if 'K' in best.index else ""
    st.success(f"✅ 최적 조합 — {k_str}손절: {best['손절(%)']}% | "
               f"트레일링: {best['트레일(%)']}% → 전체수익률 {best[sort_col]:+.2f}%")


with tab_backtest:
    st.subheader("백테스팅")

    bt_type = st.radio(
        "백테스팅 유형",
        ["daily", "intraday"],
        format_func=lambda x: "📅 다일 (일봉 기반, 장기)" if x == "daily" else "⏱ 단타 (분봉 기반, 최근 7일)",
        horizontal=True,
    )

    # ── 기본 설정 ──
    col1, col2, col3 = st.columns(3)
    if bt_type == "daily":
        with col1:
            start_date = st.date_input("시작일", value=datetime.now() - timedelta(days=180))
        with col2:
            end_date   = st.date_input("종료일", value=datetime.now())
        with col3:
            initial_capital = st.number_input("초기 자금 (원)", value=10_000_000, step=1_000_000)

        pool_option  = st.selectbox("종목 풀", ["kospi","watchlist","custom"],
                                    format_func=lambda x: {"kospi": f"코스피200 상위 {sc.KOSPI_POOL_SIZE}개 + 관심종목",
                                                           "watchlist":"관심종목만","custom":"직접 입력"}[x])
        custom_codes = st.text_input("종목 코드 (콤마 구분)", placeholder="005930,000660") if pool_option == "custom" else ""
    else:
        # 단타: 날짜 + 초기자금만 (종목 풀은 매매 로그에서 자동)
        with col1:
            bt_date = st.date_input("날짜 (최근 7일 이내)", value=datetime.now() - timedelta(days=1))
        with col3:
            initial_capital = st.number_input("초기 자금 (원)", value=10_000_000, step=1_000_000)
        pool_option  = "log_based"
        custom_codes = ""

    # ── 파라미터 범위 설정 (단타 전용) ──
    if bt_type == "intraday":
        st.divider()

        # ── 매매 로그에서 당일 스크리닝 후보 불러오기 ──
        date_str = bt_date.strftime("%Y%m%d")
        from trading_logger import load_log

        log_events   = load_log(date_str)
        screen_events = [e for e in log_events if e["event"] == "screening_result"]

        if screen_events:
            # 스크리닝 후보 종목 추출
            # cand_map: {code: {**candidate_info, "entry_time": HHMMSS}}
            # 같은 종목이 여러 라운드에 나오면 가장 처음 나온 시각(= 가장 이른 진입 기회)을 사용
            cand_map = {}
            for evt in screen_events:
                ts_raw     = evt.get("ts", "093000")
                entry_time = ts_raw.replace(":", "")[:6]   # "09:35:22" → "093522"
                for c in evt.get("candidates", []):
                    code = c["code"]
                    if code not in cand_map:
                        cand_map[code] = {**c, "entry_time": entry_time}
                    # 이미 있으면 entry_time 유지 (첫 등장 시각 사용)

            st.markdown(f"##### 📋 당일 스크리닝 후보 종목 ({date_str}, {len(cand_map)}개)")

            # 실제 매수 종목 표시
            bought_codes = {e["code"] for e in log_events if e["event"] == "buy_executed"}

            # 종목 선택 체크박스
            selected_codes = []
            cols = st.columns(2)
            for i, (code, c) in enumerate(cand_map.items()):
                ai_score = c.get("score", "—")
                grade    = c.get("grade", "")
                bought   = "✅ 매수됨" if code in bought_codes else ""
                label    = f"{c['name']} ({code})  AI:{ai_score}점  {grade}  {bought}"
                default  = True  # 기본 전체 선택
                if cols[i % 2].checkbox(label, value=default, key=f"bt_cand_{code}"):
                    selected_codes.append(code)

            if not selected_codes:
                st.warning("최소 1개 이상 선택하세요.")

            # 실제 포지션 수 / 포지션당 예산
            actual_pos_count = len(bought_codes) if bought_codes else sc.MAX_POSITIONS
            st.divider()
            st.markdown("##### 💰 포지션 예산 설정")
            n_positions = st.number_input(
                "포지션 수 (당일 실제 매수 기준 자동입력, 수정 가능)",
                min_value=1,
                value=max(actual_pos_count, len(selected_codes)),
                key="bt_n_positions"
            )
            budget_per_pos = initial_capital / n_positions
            st.caption(f"포지션당 예산: **{budget_per_pos:,.0f}원**  =  초기자금 {initial_capital:,}원 ÷ {n_positions}개")

            # 선택 종목 리스트 구성 (entry_time 포함)
            stock_list_for_bt = [
                {"code": c, "name": cand_map[c]["name"],
                 "entry_time": cand_map[c].get("entry_time", "093000")}
                for c in selected_codes
            ]
            pool_option = "log_based"

        else:
            st.info(f"📋 {date_str} 매매 로그 없음 — 표준 종목 풀로 진행합니다.")
            stock_list_for_bt = None
            budget_per_pos    = initial_capital / sc.MAX_POSITIONS
            n_positions       = sc.MAX_POSITIONS

        st.divider()
        st.markdown("##### 📐 파라미터 범위 설정")
        st.caption("범위 체크 시 모든 조합을 캐시 데이터로 한번에 계산합니다.")

        def _param_row(label, single_val, single_min, single_max, single_step,
                       r_min_def, r_max_def, r_step_def, fmt=".2f"):
            c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1.5])
            with c1:
                use_range = st.checkbox(f"범위: {label}", key=f"rng_{label}")
            if use_range:
                with c2: rmin = st.number_input("최소", value=r_min_def, step=r_step_def, key=f"rmin_{label}", format=f"%{fmt}")
                with c3: rmax = st.number_input("최대", value=r_max_def, step=r_step_def, key=f"rmax_{label}", format=f"%{fmt}")
                with c4: rstep = st.number_input("단위", value=r_step_def, step=r_step_def/2, key=f"rstep_{label}", format=f"%{fmt}")
                n = max(1, round((rmax - rmin) / rstep) + 1)
                with c5: st.caption(f"{n}개 값")
                return use_range, None, rmin, rmax, rstep
            else:
                with c2: sv = st.number_input("단일값", value=single_val, min_value=single_min,
                                              max_value=single_max, step=single_step,
                                              key=f"sv_{label}", format=f"%{fmt}")
                return use_range, sv, None, None, None

        # 단타 로그 기반: K 제거 (진입가 이미 확정), 손절/트레일만
        sv_k   = sc.K   # K는 고정값으로만 사용 (그리드 불필요)
        rng_k  = False; rmin_k = rmax_k = rstep_k = None
        rng_ls, sv_ls, rmin_ls, rmax_ls, rstep_ls  = _param_row("손절(%)",  sc.LOSS_RATE*100,          0.5, 5.0, 0.1, 1.0, 4.0, 0.5, ".1f")
        rng_tr, sv_tr, rmin_tr, rmax_tr, rstep_tr  = _param_row("트레일(%)", sc.TRAILING_STOP_RATE*100, 0.5, 5.0, 0.1, 1.0, 4.0, 0.5, ".1f")
        is_grid = rng_ls or rng_tr
    else:
        is_grid = False

    # ── 단타: 종목/파라미터 변경 감지 → 결과 자동 초기화 ──
    if bt_type == "intraday":
        _sel_codes = selected_codes if pool_option == "log_based" and 'selected_codes' in dir() else []
        _fingerprint = (
            tuple(sorted(_sel_codes)),
            round(sv_ls, 2) if not rng_ls else (round(rmin_ls,2), round(rmax_ls,2), round(rstep_ls,2)),
            round(sv_tr, 2) if not rng_tr else (round(rmin_tr,2), round(rmax_tr,2), round(rstep_tr,2)),
            bt_date.strftime("%Y%m%d"),
        )
        if st.session_state.get("bt_fingerprint") != _fingerprint:
            st.session_state["bt_fingerprint"] = _fingerprint
            st.session_state.pop("bt_result", None)
            st.session_state.pop("bt_grid",   None)

    # ── 캐시 상태 표시 (단타) ──
    if bt_type == "intraday":
        st.divider()
        date_str     = bt_date.strftime("%Y%m%d")
        _cur_codes   = tuple(sorted(selected_codes)) if pool_option == "log_based" and 'selected_codes' in dir() else ()
        _stocks_hash = str(hash(_cur_codes))[:8]
        expected     = f"{date_str}_{pool_option}_{_stocks_hash}"
        cache_key    = st.session_state.get("bt_cache_key", "")
        if cache_key == expected:
            cached_n = len(st.session_state.get("bt_minute_data", {}))
            st.success(f"✅ 캐시 사용 가능 — {date_str} / {cached_n}개 종목 로드됨")
        else:
            st.info("📥 캐시 없음 — 실행 시 데이터를 수집합니다.")

    # ── 실행 버튼 ──
    col_run1, col_run2 = st.columns([4, 1])
    with col_run1:
        run_btn = st.button("▶ 백테스트 실행", type="primary", use_container_width=True)
    with col_run2:
        if st.button("🗑 캐시 초기화", use_container_width=True):
            for k in ["bt_cache_key","bt_minute_data","bt_daily_data","bt_result","bt_grid"]:
                st.session_state.pop(k, None)
            st.rerun()

    if run_btn:
        prog_bar  = st.progress(0)
        prog_text = st.empty()
        try:
            if bt_type == "intraday":
                # 단타: 로그 기반 or 폴백
                if pool_option == "log_based" and 'stock_list_for_bt' in dir():
                    if not selected_codes:
                        st.error("종목을 1개 이상 선택하세요.")
                        st.stop()
                    stock_list = stock_list_for_bt
                else:
                    stock_list = _build_stock_list_ui("kospi", "")
                budget_per_pos = initial_capital / st.session_state.get("bt_n_positions", sc.MAX_POSITIONS)
            else:
                stock_list     = _build_stock_list_ui(pool_option, custom_codes)
                budget_per_pos = initial_capital * sc.INVEST_RATIO / sc.MAX_POSITIONS

            if bt_type == "daily":
                sd = start_date.strftime("%Y%m%d")
                ed = end_date.strftime("%Y%m%d")
                from backtest.data_loader import fetch_multi_ohlcv
                from backtest.engine import run_backtest
                all_data = fetch_multi_ohlcv(stock_list, sd, ed, progress_cb=_make_cb(prog_bar, prog_text, "일봉 수집"))
                prog_text.caption("⚙️ 계산 중...")
                result = run_backtest(all_data, stock_list, sd, ed, initial_capital)
                prog_bar.progress(1.0); prog_text.caption("✅ 완료!")
                st.session_state["bt_result"] = result
                st.session_state.pop("bt_grid", None)
                ret, n_tr, wr, mdd = _calc_summary(result)
                _save_log({"timestamp": datetime.now().isoformat(), "type":"daily",
                           "start":sd,"end":ed,"params":{"K":sc.K,"loss":sc.LOSS_RATE,"trail":sc.TRAILING_STOP_RATE},
                           "initial_capital":initial_capital,"return_pct":round(ret,2),
                           "trades":n_tr,"win_rate":round(wr,1),"mdd":round(mdd,2)})
            else:
                d_str        = bt_date.strftime("%Y%m%d")
                _run_codes   = tuple(sorted(s["code"] for s in stock_list))
                _run_hash    = str(hash(_run_codes))[:8]
                cache_key    = f"{d_str}_{pool_option}_{_run_hash}"

                # 캐시 미스 → 데이터 수집
                if st.session_state.get("bt_cache_key") != cache_key:
                    from backtest.data_loader_yf import fetch_multi_minute_bars_yf
                    from backtest.data_loader import fetch_multi_ohlcv
                    actual_date, minute_data = fetch_multi_minute_bars_yf(
                        stock_list, d_str, progress_cb=_make_cb(prog_bar, prog_text, "분봉 수집"))
                    from datetime import datetime as dt2
                    fetch_from = (dt2.strptime(actual_date, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
                    prog_bar.progress(0)
                    daily_data = fetch_multi_ohlcv(stock_list, fetch_from, actual_date,
                                                   progress_cb=_make_cb(prog_bar, prog_text, "일봉 수집"))
                    st.session_state["bt_cache_key"]    = cache_key
                    st.session_state["bt_minute_data"]  = minute_data
                    st.session_state["bt_daily_data"]   = daily_data
                    st.session_state["bt_actual_date"]  = actual_date
                else:
                    minute_data  = st.session_state["bt_minute_data"]
                    daily_data   = st.session_state["bt_daily_data"]
                    actual_date  = st.session_state["bt_actual_date"]
                    prog_text.caption("✅ 캐시 데이터 사용")

                from backtest.engine_intraday import run_intraday_backtest, run_log_intraday_backtest
                is_log_mode = (pool_option == "log_based")

                def _make_params(kv, lv, tv):
                    return {
                        "K": kv, "LOSS_RATE": lv/100,
                        "TRAILING_STOP_RATE": tv/100,
                        "TRAILING_STOP_ACTIVATE_RATE": sc.TRAILING_STOP_ACTIVATE_RATE,
                        "USE_TRAILING_STOP": sc.USE_TRAILING_STOP,
                        "PROFIT_RATE": sc.PROFIT_RATE,
                        "INVEST_RATIO": sc.INVEST_RATIO,
                        "MAX_TRADES_PER_DAY": sc.MAX_TRADES_PER_DAY,
                        "budget_per_position": budget_per_pos,
                    }

                def _run_one(params):
                    if is_log_mode:
                        # 로그 기반: 스크리닝 시각에 즉시 매수
                        return run_log_intraday_backtest(
                            minute_data, stock_list, budget_per_pos, params, actual_date
                        )
                    else:
                        return run_intraday_backtest(
                            minute_data, daily_data, stock_list, actual_date,
                            initial_capital, params=params
                        )

                if is_grid:
                    # 로그 모드: K는 진입에 영향 없으므로 K 그리드 제거
                    k_vals  = _range_values(rng_k,  sv_k,  rmin_k,  rmax_k,  rstep_k) if not is_log_mode \
                              else [sv_k]
                    ls_vals = _range_values(rng_ls, sv_ls, rmin_ls, rmax_ls, rstep_ls)
                    tr_vals = _range_values(rng_tr, sv_tr, rmin_tr, rmax_tr, rstep_tr)
                    total_combos = len(k_vals) * len(ls_vals) * len(tr_vals)
                    grid_rows, combo_i = [], 0
                    for kv in k_vals:
                        for lv in ls_vals:
                            for tv in tr_vals:
                                combo_i += 1
                                prog_bar.progress(combo_i / total_combos)
                                label_k = f"K={kv} " if not is_log_mode else ""
                                prog_text.caption(f"⚙️ ({combo_i}/{total_combos})  {label_k}손절={lv}% 트레일={tv}%")
                                r = _run_one(_make_params(kv, lv, tv))
                                ret, n_tr, wr, mdd = _calc_summary(r)
                                row = {"손절(%)": lv, "트레일(%)": tv}
                                if not is_log_mode:
                                    row["K"] = kv
                                # 종목별 수익률 (로그 기반 모드)
                                if is_log_mode:
                                    for t in r["trades"]:
                                        row[t["name"]] = round(t["pnl_rate"] * 100, 2)
                                row.update({"전체수익률(%)": round(ret,2), "거래수": n_tr,
                                            "승률(%)": round(wr,1), "MDD(%)": round(mdd,2)})
                                grid_rows.append(row)
                                _save_log({"timestamp":datetime.now().isoformat(),"type":"intraday_grid",
                                           "date":actual_date,"K":kv,"loss_pct":lv,"trail_pct":tv,
                                           "initial_capital":initial_capital,"return_pct":round(ret,2),
                                           "trades":n_tr,"win_rate":round(wr,1),"mdd":round(mdd,2)})
                    prog_bar.progress(1.0); prog_text.caption(f"✅ {total_combos}개 조합 완료!")
                    st.session_state["bt_grid"]   = grid_rows
                    st.session_state.pop("bt_result", None)
                else:
                    prog_text.caption("⚙️ 계산 중...")
                    result = _run_one(_make_params(sv_k, sv_ls, sv_tr))
                    prog_bar.progress(1.0); prog_text.caption("✅ 완료!")
                    st.session_state["bt_result"] = result
                    st.session_state.pop("bt_grid", None)
                    ret, n_tr, wr, mdd = _calc_summary(result)
                    _save_log({"timestamp":datetime.now().isoformat(),"type":"intraday",
                               "date":actual_date,"K":sv_k,"loss_pct":sv_ls,"trail_pct":sv_tr,
                               "initial_capital":initial_capital,"return_pct":round(ret,2),
                               "trades":n_tr,"win_rate":round(wr,1),"mdd":round(mdd,2)})

        except Exception as e:
            prog_text.empty()
            st.error(f"오류: {e}")
            import traceback; st.code(traceback.format_exc())

    # ── 결과 표시 ──
    st.divider()
    if st.session_state.get("bt_grid"):
        _show_grid_result(st.session_state["bt_grid"])
    elif st.session_state.get("bt_result"):
        _show_single_result(st.session_state["bt_result"])
    else:
        st.info("백테스트 실행 버튼을 누르세요.")


# ══════════════════════════════════════════
# 탭 3: 매매 로그
# ══════════════════════════════════════════
with tab_log:
    st.subheader("매매 로그")
    from trading_logger import load_log, list_log_dates

    log_dates = list_log_dates()

    if not log_dates:
        st.info("저장된 매매 로그가 없습니다. 실투/모의투자를 실행하면 자동으로 기록됩니다.")
    else:
        sel_date = st.selectbox("날짜 선택", log_dates,
                                format_func=lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]} ({d})")

        events = load_log(sel_date)
        if not events:
            st.warning("해당 날짜 로그가 비어 있습니다.")
        else:
            # ── 요약 지표 ──
            buys  = [e for e in events if e["event"] == "buy_executed"]
            sells = [e for e in events if e["event"] == "sell_executed"]
            total_pnl  = sum(s.get("pnl", 0) for s in sells)
            wins       = [s for s in sells if s.get("pnl_rate", 0) > 0]
            win_rate   = len(wins) / len(sells) * 100 if sells else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("매수",   f"{len(buys)}건")
            m2.metric("매도",   f"{len(sells)}건")
            m3.metric("실현손익", f"{total_pnl:+,.0f}원")
            m4.metric("승률",   f"{win_rate:.1f}%")

            st.divider()

            # ── 탭으로 이벤트 구분 ──
            lt1, lt2, lt3 = st.tabs(["📈 매수/매도", "🔍 스크리닝", "📜 전체 이벤트"])

            with lt1:
                reason_emoji = {"트레일링스탑":"📉","손절":"🔻","강제청산":"⏰","익절":"✅","종가청산":"🔔"}
                rows = []
                for s in sells:
                    buy_ts = next((b["ts"] for b in buys if b["code"] == s["code"]), "—")
                    rows.append({
                        "매수시각": buy_ts,
                        "매도시각": s["ts"],
                        "종목":     s["name"],
                        "코드":     s["code"],
                        "매수가":   s["buy_price"],
                        "매도가":   s["sell_price"],
                        "수량":     s["quantity"],
                        "손익(원)": s.get("pnl", 0),
                        "수익률":   f"{s.get('pnl_rate',0):+.2f}%",
                        "사유":     reason_emoji.get(s["reason"],"") + " " + s["reason"],
                    })
                if rows:
                    df = pd.DataFrame(rows)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("매도 내역 없음")

            with lt2:
                screens = [e for e in events if e["event"] == "screening_result"]
                if not screens:
                    st.info("스크리닝 이벤트 없음")
                for sc_evt in screens:
                    with st.expander(f"스크리닝 #{sc_evt.get('round','')}  ({sc_evt.get('ts','')})  — {len(sc_evt.get('candidates',[]))}개 후보"):
                        cands = sc_evt.get("candidates", [])
                        if cands:
                            df = pd.DataFrame([{
                                "종목":   c["name"],
                                "코드":   c["code"],
                                "총점":   c.get("score", 0),
                                "기술":   c.get("tech", 0),
                                "LLM":    c.get("llm", 0),
                                "DART":   c.get("dart", 0),
                                "라우팅": c.get("route", ""),
                                "여유율": f"{c.get('gap',0):.2f}%",
                                "패턴":   c.get("pattern") or "—",
                                "등급":   c.get("grade") or "—",
                            } for c in cands])
                            st.dataframe(df, use_container_width=True, hide_index=True)

            with lt3:
                event_label = {
                    "screening_result": "🔍 스크리닝",
                    "auto_buy":         "🤖 자동매수결정",
                    "confirm_sent":     "📱 텔레그램전송",
                    "confirm_selected": "✅ 종목선택",
                    "buy_executed":     "💰 매수체결",
                    "sell_executed":    "🏁 매도체결",
                    "daily_summary":    "📊 일별요약",
                }
                rows = []
                for e in events:
                    label = event_label.get(e["event"], e["event"])
                    detail = ""
                    if e["event"] == "buy_executed":
                        detail = f"{e['name']} {e['buy_price']:,}원 × {e['quantity']}주"
                    elif e["event"] == "sell_executed":
                        detail = f"{e['name']} {e['sell_price']:,}원 ({e.get('pnl_rate',0):+.2f}%) [{e['reason']}]"
                    elif e["event"] == "auto_buy":
                        detail = f"{e['name']} {e.get('score',0)}점"
                    elif e["event"] == "screening_result":
                        detail = f"{len(e.get('candidates',[]))}개 후보"
                    rows.append({"시각": e.get("ts",""), "이벤트": label, "내용": detail})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════
# 탭 4: 파라미터 현황
# ══════════════════════════════════════════
with tab_config:
    st.subheader("현재 전략 파라미터")
    st.caption("사이드바에서 값을 조정하면 실시간으로 반영됩니다. 영구 저장은 strategy_config.py를 직접 수정하세요.")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### 매매 전략")
        st.dataframe(pd.DataFrame([
            {"파라미터": "K (변동성 계수)",      "값": str(sc.K)},
            {"파라미터": "투자 비율",             "값": f"{sc.INVEST_RATIO*100:.0f}%"},
            {"파라미터": "하드 손절",             "값": f"{sc.LOSS_RATE*100:.1f}%"},
            {"파라미터": "트레일링 스탑",          "값": f"{sc.TRAILING_STOP_RATE*100:.1f}%"},
            {"파라미터": "트레일 활성화 기준",     "값": f"+{sc.TRAILING_STOP_ACTIVATE_RATE*100:.1f}%"},
            {"파라미터": "강제 청산",             "값": str(sc.FORCE_SELL_TIME)},
        ]).astype(str), use_container_width=True, hide_index=True)

    with col_b:
        st.markdown("#### 스크리닝 & 실행")
        st.dataframe(pd.DataFrame([
            {"파라미터": "코스피 풀 크기",         "값": str(sc.KOSPI_POOL_SIZE)},
            {"파라미터": "최대 포지션",            "값": str(sc.MAX_POSITIONS)},
            {"파라미터": "최대 매매 횟수/일",      "값": str(sc.MAX_TRADES_PER_DAY)},
            {"파라미터": "돌파여유율 상한",         "값": f"{sc.MAX_BREAKOUT_GAP}%"},
            {"파라미터": "재스크리닝 주기",         "값": f"{sc.SCREENING_INTERVAL}분"},
            {"파라미터": "쿨다운",                 "값": f"{sc.SAME_STOCK_COOLDOWN}초"},
        ]).astype(str), use_container_width=True, hide_index=True)

        st.markdown("#### AI 점수")
        st.dataframe(pd.DataFrame([
            {"파라미터": "AI 점수 사용",    "값": str(sc.USE_AI_SCORING)},
            {"파라미터": "DART 점수 사용",  "값": str(sc.USE_DART_SCORING)},
            {"파라미터": "자동매수 기준",    "값": f"{sc.AUTO_BUY_SCORE}점 이상"},
            {"파라미터": "확인 요청 기준",   "값": f"{sc.CONFIRM_SCORE_MIN}점 이상"},
        ]).astype(str), use_container_width=True, hide_index=True)
