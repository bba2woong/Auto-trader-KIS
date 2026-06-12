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
        self.verbose  = []   # 전체 상세 로그 (VS Code 터미널 수준)

    def update_status(self, msg):
        with self._lock:
            self.status = msg.rstrip()

    def add_history(self, msg):
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            entry = f"[{ts}] {msg.rstrip()}"
            self.history.append(entry)
            if len(self.history) > 200:
                self.history = self.history[-200:]

    def add_verbose(self, msg):
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.verbose.append(f"[{ts}] {msg.rstrip()}")
            if len(self.verbose) > 2000:
                self.verbose = self.verbose[-2000:]

    def get_status(self):
        with self._lock: return self.status

    def get_history(self):
        with self._lock: return list(self.history)

    def get_verbose(self):
        with self._lock: return list(self.verbose)

    def clear(self):
        with self._lock:
            self.status  = ""
            self.history = []
            self.verbose  = []


class _LogCapture:
    """sys.stdout 가로채기 — 반복성/중요 이벤트 분류"""
    def __init__(self, original, buf: _LogBuffer):
        self.original = original
        self.buf      = buf
        self._line    = ""

    def write(self, msg):
        try:
            self.original.write(msg)
        except (UnicodeEncodeError, UnicodeDecodeError):
            self.original.write(msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
        text   = self._line + msg
        lines  = text.split("\n")
        self._line = lines[-1]
        for line in lines[:-1]:
            self._route(line)

    def _route(self, line):
        s = line.strip()
        if not s:
            return
        # 전체 상세 로그 (항상 기록)
        self.buf.add_verbose(s)
        is_repeat = (
            any(k in s for k in self.buf.REPEAT_KW) or "\r" in s
        )
        if is_repeat:
            self.buf.update_status(s)
        elif any(k in s for k in self.buf.IMPORTANT_KW):
            self.buf.add_history(s)

    def flush(self):  self.original.flush()
    def isatty(self): return False


# 모듈 레벨 전역 버퍼
# sys.modules에 저장 → Streamlit 리런 시 재생성 방지 (스레드와 공유)
# 구버전 인스턴스(add_verbose 없음)는 자동으로 교체
_LOG_BUF_KEY = "_kis_trader_log_buf"
_existing = sys.modules.get(_LOG_BUF_KEY)
if _existing is None or not hasattr(_existing, "add_verbose"):
    sys.modules[_LOG_BUF_KEY] = _LogBuffer()
_log_buf: _LogBuffer = sys.modules[_LOG_BUF_KEY]

# 스케줄러 중복 시작 방지 — sys.modules에 저장하여 Streamlit rerun 간 공유
_SCHED_KEY = "_kis_trader_sched_lock"
if _SCHED_KEY not in sys.modules:
    sys.modules[_SCHED_KEY] = threading.Lock()
_sched_lock: threading.Lock = sys.modules[_SCHED_KEY]

# 복구 모드 진입 횟수 (프로세스 재시작 시 0으로 초기화)
_RECOVERY_COUNT_KEY = "_kis_trader_recovery_count"
if _RECOVERY_COUNT_KEY not in sys.modules:
    sys.modules[_RECOVERY_COUNT_KEY] = 0


# ──────────────────────────────────────────
# 트레이딩 시작/정지 헬퍼
# ──────────────────────────────────────────

def _start_scheduler(mode: str):
    """config 재로드 → sys.stdout 교체 → scheduler 백그라운드 실행"""
    # 프로세스 레벨 lock — Streamlit rerun 중복 호출 방지
    # 정지 후 재시작 시 이전 스레드가 종료되기까지 최대 15초 대기
    if not _sched_lock.acquire(timeout=15):
        print("[Scheduler] 이전 스케줄러 종료 대기 시간 초과 — 강제 해제 후 재시작")
        try:
            _sched_lock.release()
        except RuntimeError:
            pass
        if not _sched_lock.acquire(blocking=False):
            return
    # 스레드가 여전히 살아있으면(정지 처리 중) 즉시 해제 후 종료
    existing_thread = st.session_state.get("trader_thread")
    if existing_thread and existing_thread.is_alive():
        _sched_lock.release()
        return

    import config as cfg
    # Windows cp949 환경에서 이모지 출력 시 인코딩 오류 방지
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    cfg.reload(mode)
    os.environ["TRADING_MODE"] = mode

    _log_buf.clear()
    capture = _LogCapture(sys.stdout, _log_buf)
    sys.stdout = capture

    # 시작 전 정지 이벤트 초기화
    from scheduler import _get_stop_event
    _get_stop_event().clear()

    def _run():
        try:
            import time as _time
            import strategy_config as _sc
            now_str = datetime.now().strftime("%H:%M")

            # 시간대별 처리
            if now_str < "06:00":
                _log_buf.add_history(
                    f"⛔ 너무 이른 시간입니다 (현재 {now_str}). "
                    f"06:00 이후에 시작하세요."
                )
                _time.sleep(1.5)
                return
            elif now_str >= _sc.MARKET_CLOSE:
                _log_buf.add_history(
                    f"⛔ 장 종료 후입니다 (현재 {now_str}, "
                    f"장 운영: {_sc.MARKET_OPEN}~{_sc.MARKET_CLOSE})"
                )
                _time.sleep(1.5)
                return
            elif now_str < _sc.MARKET_OPEN:
                # 06:00~09:00 → 대기 모드로 진행
                _log_buf.add_history(
                    f"🕐 장 시작 대기 모드 (현재 {now_str}) — "
                    f"{_sc.MARKET_OPEN} 장 시작 시 자동 가동됩니다."
                )

            from scheduler import run_scheduler
            run_scheduler()
        except Exception as e:
            _log_buf.add_history(f"⚠️ 스케줄러 오류: {e}")
        finally:
            sys.stdout = capture.original
            st.session_state["trader_running"] = False
            try:
                _sched_lock.release()  # 스케줄러 종료 시 lock 해제
            except RuntimeError:
                pass  # 이미 해제된 경우 무시

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    st.session_state["trader_thread"]  = t
    st.session_state["trader_running"] = True
    st.session_state["trader_mode"]    = mode

    # 워치독 스레드 시작
    wd = threading.Thread(target=_watchdog_loop, args=(mode,), daemon=True)
    wd.start()
    st.session_state["watchdog_thread"] = wd


_telegram_error_count = 0


def _restart_scheduler(mode: str):
    """워치독이 스케줄러를 재시작할 때 사용하는 내부 헬퍼."""
    import config as cfg
    from scheduler import _get_stop_event
    from telegram_alarm import notify_alarm

    _get_stop_event().set()  # 기존 스케줄러 정지 요청
    import time as _time
    _time.sleep(2)
    _get_stop_event().clear()
    cfg.reload(mode)

    capture = _LogCapture(sys.stdout, _log_buf)
    sys.stdout = capture

    def _run():
        try:
            from scheduler import run_scheduler
            run_scheduler()
        except Exception as e:
            _log_buf.add_history(f"⚠️ 스케줄러 재시작 오류: {e}")
        finally:
            sys.stdout = capture.original
            st.session_state["trader_running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    st.session_state["trader_thread"]  = t
    st.session_state["trader_running"] = True
    notify_alarm("✅ 트레이딩 재시작 완료")


def _watchdog_loop(mode: str):
    """10초 주기로 트레이더 스레드와 텔레그램 봇 상태 감시."""
    import time as _time
    global _telegram_error_count

    while True:
        _time.sleep(10)

        # trader_running이 False이면 워치독 종료
        if not st.session_state.get("trader_running", False):
            break

        t_thread = st.session_state.get("trader_thread")

        # 스레드 비정상 종료 감지
        if t_thread and not t_thread.is_alive():
            try:
                from telegram_alarm import notify_alarm
                notify_alarm("🚨 트레이딩 스레드 비정상 종료 감지 — 3초 후 재시작")
            except Exception:
                pass
            _time.sleep(3)
            try:
                _restart_scheduler(mode)
            except Exception as e:
                _log_buf.add_history(f"⚠️ 워치독 재시작 실패: {e}")
            continue

        # 텔레그램 봇 polling 무응답 감지
        try:
            from telegram_bot import _last_poll_success
            if _time.time() - _last_poll_success > 120:
                _telegram_error_count += 1
                if _telegram_error_count >= 3:
                    try:
                        from telegram_alarm import notify_alarm
                        notify_alarm("🚨 텔레그램 봇 2분 이상 무응답 — 스케줄러 재시작")
                    except Exception:
                        pass
                    _telegram_error_count = 0
                    try:
                        _restart_scheduler(mode)
                    except Exception as e:
                        _log_buf.add_history(f"⚠️ 워치독 텔레그램 재시작 실패: {e}")
            else:
                _telegram_error_count = 0
        except Exception:
            pass

# ──────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────
st.set_page_config(
    page_title="KIS Auto Trader",
    page_icon="🚀",
    layout="wide",
)

# Streamlit 핫리로드로 인한 봇 중복 실행 방지
if "bot_guard" not in st.session_state:
    st.session_state["bot_guard"] = True
    try:
        from telegram_bot import _bot_running
        _bot_running.clear()
    except Exception:
        pass

# 비정상 종료 감지 (watchdog 재시작 후 1회만 실행)
if "recovery_checked" not in st.session_state:
    st.session_state["recovery_checked"] = True
    try:
        import os as _os
        from trading_state import load_state, is_market_hours
        _rs = load_state()
        if _rs.get("running"):
            # PID 비교: 같은 PID면 F5 새로고침 → 복구 불필요
            _saved_pid    = _rs.get("pid")
            _same_process = (_saved_pid is not None and _saved_pid == _os.getpid())

            # 저장된 PID 프로세스가 실제로 살아있는지 확인 (Windows: tasklist)
            _pid_alive = False
            if _saved_pid and not _same_process:
                try:
                    import subprocess as _sp
                    _r = _sp.run(
                        ["tasklist", "/fi", f"PID eq {_saved_pid}", "/fo", "csv", "/nh"],
                        capture_output=True, text=True, timeout=3
                    )
                    _pid_alive = str(_saved_pid) in _r.stdout
                except Exception:
                    _pid_alive = False

            # 날짜 비교: 전날(재부팅 전 세션) 상태면 crash 아님
            from datetime import date as _date
            _updated_at  = _rs.get("updated_at", "")
            _state_today = _updated_at[:10] == str(_date.today()) if _updated_at else False

            from trading_state import clear_state
            if _same_process:
                pass  # F5 새로고침 — 정상 실행 중
            elif not _pid_alive:
                # 저장된 PID가 이미 죽음 → 정상/비정상 종료 후 남은 상태
                clear_state()
                st.session_state["recovery_mode"] = False
            elif not _state_today:
                # 전날 기록 → 재부팅으로 인한 정상 종료
                clear_state()
                st.session_state["recovery_mode"] = False
            elif is_market_hours():
                st.session_state["recovery_mode"]      = True
                st.session_state["recovery_mode_last"] = _rs.get("mode", "mock")
            else:
                clear_state()
                st.session_state["recovery_mode"] = False
    except Exception:
        pass

st.title("📈 KIS Auto Trader")

# ──────────────────────────────────────────
# 사이드바 — 투자 모드 & 파라미터
# ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

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
    kosdaq_size = st.slider(
        "코스닥 풀 크기", 0, 150, sc.KOSDAQ_POOL_SIZE, 10,
        help="코스닥150 중 상위 N개 종목을 스크리닝\n0이면 코스닥 비활성화",
    )

    # 런타임 파라미터 반영 (파일 저장은 안 함 — 화면 내 미리보기용)
    sc.K                     = k
    sc.INVEST_RATIO          = invest_ratio
    sc.LOSS_RATE             = loss_rate
    sc.TRAILING_STOP_RATE    = trailing_rate
    sc.MAX_POSITIONS         = max_positions
    sc.KOSPI_POOL_SIZE       = pool_size
    sc.KOSDAQ_POOL_SIZE      = kosdaq_size

    st.divider()

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

    # ── 비정상 종료 복구 배너 ──
    # 장외 시간에 recovery_mode가 남아있는 경우 (탭 전환 등으로 재진입 시)
    if st.session_state.get("recovery_mode"):
        from trading_state import is_market_hours as _imh
        if not _imh():
            from trading_state import clear_state as _cs
            _cs()
            st.session_state["recovery_mode"] = False
            st.info("ℹ️ 장 외 시간입니다. 장 시작 후 수동으로 트레이딩을 시작하세요.")

    if st.session_state.get("recovery_mode"):
        _last_mode = st.session_state.get("recovery_mode_last", "mock")
        _last_label = "모의투자" if _last_mode == "mock" else "실전투자"
        st.warning(
            f"⚠️ **비정상 종료가 감지되었습니다.**\n\n"
            f"마지막 실행 모드: **{_last_label}**\n\n"
            f"텔레그램으로 재시작 모드 선택 요청을 전송했습니다.\n"
            f"3분 내 응답 없으면 **모의투자**로 자동 진입합니다."
        )

        # 2회 이상 복구 모드 진입 시 수동 버튼 표시
        if sys.modules.get(_RECOVERY_COUNT_KEY, 0) >= 2:
            _rc1, _rc2, _rc3 = st.columns([3, 1, 1])
            with _rc2:
                if st.button("모의투자로 진입", key="recovery_manual_mock"):
                    st.session_state["recovery_mode"] = False
                    st.session_state["recovery_done"] = True
                    st.session_state["trading_mode"] = "mock"
                    if _sched_lock.locked():
                        try: _sched_lock.release()
                        except RuntimeError: pass
                    _start_scheduler("mock")
                    st.rerun()
            with _rc3:
                if st.button("실전투자로 진입", key="recovery_manual_real"):
                    st.session_state["recovery_mode"] = False
                    st.session_state["recovery_done"] = True
                    st.session_state["trading_mode"] = "real"
                    if _sched_lock.locked():
                        try: _sched_lock.release()
                        except RuntimeError: pass
                    _start_scheduler("real")
                    st.rerun()

        # 복구 스레드가 아직 시작 안 됐으면 시작
        if not st.session_state.get("recovery_thread_started"):
            st.session_state["recovery_thread_started"] = True
            sys.modules[_RECOVERY_COUNT_KEY] = sys.modules.get(_RECOVERY_COUNT_KEY, 0) + 1

            def _send_recovery_query(last_mode):
                selected_mode = "mock"
                try:
                    from telegram_bot import send_recovery_query
                    result = send_recovery_query(last_mode=last_mode, timeout=180)
                    selected_mode = result if result in ("mock", "real") else "mock"
                    if result is None:
                        try:
                            from telegram_alarm import notify_alarm
                            notify_alarm("⏰ 복구 응답 없음 — 모의투자로 자동 진입합니다.")
                        except Exception:
                            pass
                    try:
                        import config as _cfg
                        _cfg.reload(selected_mode)
                        os.environ["TRADING_MODE"] = selected_mode
                    except Exception as _e:
                        print(f"[Recovery] config.reload 오류: {_e}")
                except Exception as _e:
                    import traceback
                    print(f"[Recovery] send_recovery_query 오류: {_e}")
                    print(traceback.format_exc())
                finally:
                    # 어떤 예외가 발생해도 반드시 recovery 상태 해제
                    st.session_state["trading_mode"]  = selected_mode
                    st.session_state["recovery_mode"] = False
                    st.session_state["recovery_done"] = True
                    # 혹시 락이 잠겨 있으면 강제 해제 후 재시도
                    if _sched_lock.locked():
                        try:
                            _sched_lock.release()
                        except RuntimeError:
                            pass
                    try:
                        _start_scheduler(selected_mode)
                    except Exception as _e:
                        import traceback
                        print(f"[Recovery] _start_scheduler 오류: {_e}")
                        print(traceback.format_exc())

            _rt = threading.Thread(
                target=_send_recovery_query,
                args=(st.session_state.get("recovery_mode_last", "mock"),),
                daemon=True,
            )
            _rt.start()

        # 복구 대기 중 3초마다 자동 rerun → 완료 시 즉시 UI 갱신
        import time as _t
        _t.sleep(3)
        st.rerun()

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
            from scheduler import _get_stop_event
            from trading_state import clear_state as _clear_state
            _get_stop_event().set()
            _clear_state()   # 정상 종료 → 다음 재시작 시 복구 모드 미발동
            # UI 즉시 비활성화 — 백그라운드 정리는 스레드가 계속 수행
            st.session_state["trader_running"] = False
            _log_buf.add_history(
                "⏹ 정지 요청 — 모니터링 중단됩니다. "
                "보유 포지션은 KIS 계좌에 그대로 유지됩니다. "
                "재시작 시 KIS 잔고에서 자동 복구됩니다."
            )
            st.rerun()

    if not running and t_mode != "—":
        st.info("⏹ 모니터링 정지됨 — 재시작 버튼을 누르면 KIS 잔고에서 포지션을 자동 복구합니다.")

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
        # 스레드 종료 감지 → 전체 페이지 리런으로 상태 동기화
        _t = st.session_state.get("trader_thread")
        _r = st.session_state.get("trader_running", False)
        if _r and _t and not _t.is_alive():
            st.session_state["trader_running"] = False
            st.rerun()          # 전체 재렌더링으로 메트릭 갱신

        # 상태 줄 (반복성)
        status = _log_buf.get_status()
        st.caption(f"📡 {status}" if status else "📡 대기 중...")

        # ── 중요 이벤트 누적 로그 ──
        history = _log_buf.get_history()
        col_log, col_clear = st.columns([5, 1])
        with col_clear:
            if st.button("🗑 로그 지우기", key="clear_log"):
                _log_buf.clear()
        with col_log:
            if history:
                st.code("\n".join(reversed(history[-50:])),
                        language=None)
            else:
                st.info("중요 이벤트가 여기에 표시됩니다.")

        # ── 상세 로그 (VS Code 터미널 수준 전체 출력) ──
        st.divider()
        verbose_lines = _log_buf.get_verbose()
        verbose_count = len(verbose_lines)

        col_v1, col_v2, col_v3 = st.columns([3, 1, 1])
        with col_v1:
            st.markdown(f"**📟 상세 로그** &nbsp; <span style='color:gray;font-size:0.85em'>({verbose_count}줄 누적)</span>",
                        unsafe_allow_html=True)
        with col_v2:
            show_n = st.selectbox("표시 줄 수", [100, 200, 500, 1000],
                                  index=0, key="verbose_show_n", label_visibility="collapsed")
        with col_v3:
            if st.button("🗑 상세 로그 지우기", key="clear_verbose"):
                with _log_buf._lock:
                    _log_buf.verbose = []

        if verbose_lines:
            # 최신 N줄을 역순으로 (최신이 위)
            display = list(reversed(verbose_lines[-show_n:]))
            st.code("\n".join(display), language=None)
        else:
            st.info("상세 로그가 여기에 표시됩니다. (트레이딩 시작 후 모든 출력 포함)")

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

_BT_PRESET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_presets.json")

def _bt_load_presets() -> dict:
    try:
        import json
        with open(_BT_PRESET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _bt_save_presets(presets: dict):
    import json
    with open(_BT_PRESET_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)

# 프리셋에 저장/복원할 session_state 키 목록
_BT_PRESET_KEYS = [
    "bt_opt_mode",
    "rng_K값", "sv_K값", "rmin_K값", "rmax_K값", "rstep_K값",
    "rng_손절(%)", "sv_손절(%)", "rmin_손절(%)", "rmax_손절(%)", "rstep_손절(%)",
    "rng_트레일(%)", "sv_트레일(%)", "rmin_트레일(%)", "rmax_트레일(%)", "rstep_트레일(%)",
    "rng_변동성돌파(최대점)", "sv_변동성돌파(최대점)", "rmin_변동성돌파(최대점)", "rmax_변동성돌파(최대점)", "rstep_변동성돌파(최대점)",
    "rng_AD Line 점수",   "sv_AD Line 점수",   "rmin_AD Line 점수",   "rmax_AD Line 점수",   "rstep_AD Line 점수",
    "rng_캔들패턴(해머)", "sv_캔들패턴(해머)", "rmin_캔들패턴(해머)", "rmax_캔들패턴(해머)", "rstep_캔들패턴(해머)",
    "rng_강봉(60분) 점수","sv_강봉(60분) 점수","rmin_강봉(60분) 점수","rmax_강봉(60분) 점수","rstep_강봉(60분) 점수",
    "rng_관심종목 보너스","sv_관심종목 보너스","rmin_관심종목 보너스","rmax_관심종목 보너스","rstep_관심종목 보너스",
    "sv_llm_fixed", "sv_dart_fixed", "sv_min_score",
    "bt_n_trials",
]


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

    if "_period" in result:
        _p   = result["_period"]
        _sd  = datetime.strptime(_p["sd"], "%Y%m%d").strftime("%Y/%m/%d")
        _ed  = datetime.strptime(_p["ed"], "%Y%m%d").strftime("%Y/%m/%d")
        st.caption(f"분석 기간: {_p['n_dates']}일 ({_sd} ~ {_ed})")

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


def _show_bayes_result(opt_result):
    """베이지안 최적화 결과 표시"""
    st.subheader(f"🧠 베이지안 최적화 결과  ({opt_result['n_trials']}회 탐색)")
    best_p = opt_result["best_params"]
    best_s = opt_result["best_sharpe"]

    col1, col2 = st.columns(2)
    with col1:
        st.metric("최고 샤프 비율", f"{best_s:.4f}")
        st.caption(f"Trial #{opt_result['best_trial']} 에서 달성")
    with col2:
        st.markdown("**최적 파라미터**")
        for k, v in best_p.items():
            if isinstance(v, float):
                # LOSS_RATE / TRAILING_STOP_RATE → % 변환
                if "RATE" in k and v < 1.0:
                    st.caption(f"`{k}` = **{v*100:.2f}%**")
                else:
                    st.caption(f"`{k}` = **{v:.4f}**")
            else:
                st.caption(f"`{k}` = **{v}**")

    # 전체 trial 결과 테이블
    with st.expander("📋 전체 Trial 결과 보기", expanded=False):
        trial_df = pd.DataFrame(opt_result["all_trials"])
        if not trial_df.empty:
            trial_df = trial_df.sort_values("sharpe", ascending=False)
            st.dataframe(
                trial_df.style.map(_pnl_color, subset=["sharpe"]),
                use_container_width=True, hide_index=True,
            )


def _show_grid_result(grid_rows):
    """파라미터 범위 그리드 결과 테이블"""
    st.subheader(f"파라미터 최적화 결과  ({len(grid_rows)}개 조합)")
    df       = pd.DataFrame(grid_rows)
    sort_col = "전체수익률(%)" if "전체수익률(%)" in df.columns else "수익률(%)"
    df       = df.sort_values(sort_col, ascending=False)

    fixed      = {"K","손절(%)","트레일(%)","전체수익률(%)","수익률(%)","거래수","승률(%)","MDD(%)",
                  "돌파점","AD점","캔들점","강봉점","관심점","샤프비율"}
    stock_cols = [c for c in df.columns if c not in fixed]
    sharpe_col = ["샤프비율"] if "샤프비율" in df.columns else []
    color_cols = [c for c in [sort_col] + stock_cols + sharpe_col if c in df.columns]

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

    # ── 기본 설정 ──
    initial_capital = st.number_input("초기 자금 (원)", value=10_000_000, step=1_000_000)
    st.caption(f"종목 풀: 사이드바 설정 사용 (코스피 상위 {sc.KOSPI_POOL_SIZE}개 + 관심종목)")
    _use_custom = st.checkbox("직접 종목 입력", key="bt_intraday_custom")
    if _use_custom:
        custom_codes = st.text_input("종목 코드 (콤마 구분)", placeholder="005930,000660",
                                     key="bt_custom_codes_intraday")
        pool_option  = "custom"
    else:
        custom_codes = ""
        pool_option  = "kospi"

        # ── 1분봉 데이터 캐시 관리 ──────────────────────────────
        from backtest.data_cache import (
            load_manifest      as _dc_lm,
            collect_and_cache  as _dc_collect,
            load_minute_data_from_cache as _dc_load,
            delete_cached_date as _dc_del,
        )
        _dc_batches = sorted(_dc_lm().get("batches", []), key=lambda b: b["date"])

        with st.expander("📦 1분봉 데이터 캐시 관리", expanded=len(_dc_batches) == 0):
            _dcc1, _dcc2 = st.columns([4, 1])
            with _dcc1:
                st.caption("yfinance로 최근 7일치 1분봉을 수집해 로컬에 저장합니다. 이미 수집된 날짜는 자동 스킵됩니다.")
            with _dcc2:
                _dc_collect_btn = st.button("🔄 데이터 수집", key="bt_dc_collect", use_container_width=True)
            if _dc_collect_btn:
                _dc_prog = st.progress(0)
                _dc_txt  = st.empty()
                _dc_sl   = _build_stock_list_ui(pool_option, custom_codes)
                def _dc_cb(cur, tot, msg):
                    _dc_prog.progress(cur / max(tot, 1))
                    _dc_txt.caption(msg)
                _dc_res = _dc_collect(_dc_sl, progress_cb=_dc_cb)
                _dc_prog.progress(1.0)
                _dc_txt.caption(
                    f"✅ 완료! 신규 {len(_dc_res['new_dates'])}일 / "
                    f"스킵 {len(_dc_res['skipped_dates'])}일 / "
                    f"오류 {len(_dc_res['error_codes'])}종목"
                )
                st.rerun()
            if _dc_batches:
                import pandas as _pd_dc
                st.dataframe(
                    _pd_dc.DataFrame([{
                        "날짜": b["date"], "종목수": b["stocks"],
                        "수집일시": b["collected_at"][:19],
                    } for b in reversed(_dc_batches)]),
                    hide_index=True, use_container_width=True,
                )
                _dc_del_sel = st.selectbox(
                    "삭제할 날짜", ["(선택)"] + [b["date"] for b in reversed(_dc_batches)],
                    key="bt_dc_del_sel",
                )
                if _dc_del_sel != "(선택)" and st.button("🗑 선택 날짜 삭제", key="bt_dc_del_btn"):
                    _dc_del(_dc_del_sel)
                    st.rerun()
            else:
                st.info("수집된 캐시 없음 — 위 버튼으로 먼저 수집하세요.")

        # ── 백테스트 날짜 선택 ──────────────────────────────────
        bt_use_cache      = False
        bt_selected_dates = []
        if _dc_batches:
            _dc_avail = sorted(b["date"] for b in _dc_batches)

            st.markdown("**📅 백테스트 날짜 선택**")
            _date_mode = st.radio(
                "선택 모드",
                ["range", "individual"],
                format_func=lambda x: "📅 범위 선택" if x == "range" else "☑️ 개별 선택",
                horizontal=True,
                key="bt_date_mode",
            )

            if _date_mode == "range":
                # 빠른 선택 버튼
                _qc = st.columns(4)
                if _qc[0].button("최근 5일",  key="bt_q5",   use_container_width=True):
                    st.session_state["bt_range_start"] = datetime.strptime(_dc_avail[max(0, len(_dc_avail)-5)],  "%Y%m%d").date()
                    st.session_state["bt_range_end"]   = datetime.strptime(_dc_avail[-1], "%Y%m%d").date()
                if _qc[1].button("최근 10일", key="bt_q10",  use_container_width=True):
                    st.session_state["bt_range_start"] = datetime.strptime(_dc_avail[max(0, len(_dc_avail)-10)], "%Y%m%d").date()
                    st.session_state["bt_range_end"]   = datetime.strptime(_dc_avail[-1], "%Y%m%d").date()
                if _qc[2].button("최근 20일", key="bt_q20",  use_container_width=True):
                    st.session_state["bt_range_start"] = datetime.strptime(_dc_avail[max(0, len(_dc_avail)-20)], "%Y%m%d").date()
                    st.session_state["bt_range_end"]   = datetime.strptime(_dc_avail[-1], "%Y%m%d").date()
                if _qc[3].button("전체",      key="bt_qall", use_container_width=True):
                    st.session_state["bt_range_start"] = datetime.strptime(_dc_avail[0],  "%Y%m%d").date()
                    st.session_state["bt_range_end"]   = datetime.strptime(_dc_avail[-1], "%Y%m%d").date()

                # 시작/종료일 date_input (빠른 버튼이 session_state를 먼저 갱신)
                _rcols = st.columns(2)
                with _rcols[0]:
                    _rng_start = st.date_input(
                        "시작일",
                        value=st.session_state.get("bt_range_start",
                              datetime.strptime(_dc_avail[0], "%Y%m%d").date()),
                        key="bt_range_start",
                    )
                with _rcols[1]:
                    _rng_end = st.date_input(
                        "종료일",
                        value=st.session_state.get("bt_range_end",
                              datetime.strptime(_dc_avail[-1], "%Y%m%d").date()),
                        key="bt_range_end",
                    )

                _rs = _rng_start.strftime("%Y%m%d")
                _re = _rng_end.strftime("%Y%m%d")
                bt_selected_dates = [d for d in _dc_avail if _rs <= d <= _re]
                if bt_selected_dates:
                    bt_use_cache = True
                    _ds_fmt = datetime.strptime(bt_selected_dates[0],  "%Y%m%d").strftime("%Y/%m/%d")
                    _de_fmt = datetime.strptime(bt_selected_dates[-1], "%Y%m%d").strftime("%Y/%m/%d")
                    st.caption(f"✅ {len(bt_selected_dates)}일 선택됨 ({_ds_fmt} ~ {_de_fmt})")
                else:
                    st.caption("⚠️ 선택된 범위 내 수집된 날짜가 없습니다.")

            else:  # individual
                _sel_btns = st.columns([1, 1, 4])
                if _sel_btns[0].button("전체 선택", key="bt_sel_all",   use_container_width=True):
                    for _d in _dc_avail:
                        st.session_state[f"bt_cd_{_d}"] = True
                if _sel_btns[1].button("전체 해제", key="bt_desel_all", use_container_width=True):
                    for _d in _dc_avail:
                        st.session_state[f"bt_cd_{_d}"] = False

                _dc_n    = min(5, max(1, len(_dc_avail)))
                _dc_cols = st.columns(_dc_n)
                for _dci, _dcd in enumerate(_dc_avail):
                    if _dc_cols[_dci % _dc_n].checkbox(_dcd, key=f"bt_cd_{_dcd}"):
                        bt_selected_dates.append(_dcd)
                if bt_selected_dates:
                    bt_use_cache = True
                    _ds_fmt = datetime.strptime(bt_selected_dates[0],  "%Y%m%d").strftime("%Y/%m/%d")
                    _de_fmt = datetime.strptime(bt_selected_dates[-1], "%Y%m%d").strftime("%Y/%m/%d")
                    st.caption(f"✅ {len(bt_selected_dates)}개 날짜 선택됨 ({_ds_fmt} ~ {_de_fmt})")
                else:
                    st.caption("날짜를 선택하세요.")

    # ── 파라미터 범위 설정 ──
    st.divider()

    # ── 당일 매매 로그 참고 (표시 전용, 종목 풀과 무관) ──
    date_str = bt_selected_dates[-1] if bt_selected_dates else datetime.now().strftime("%Y%m%d")
    from trading_logger import load_log
    log_events    = load_log(date_str)
    bought_codes  = {e["code"] for e in log_events if e["event"] == "buy_executed"}
    screen_events = [e for e in log_events if e["event"] == "screening_result"]

    if bought_codes or screen_events:
        with st.expander(f"📋 {date_str} 매매 로그 참고 — 실제 매수 종목", expanded=False):
            cand_map = {}
            for evt in screen_events:
                for c in evt.get("candidates", []):
                    if c["code"] not in cand_map:
                        cand_map[c["code"]] = c
            if bought_codes:
                ref_cols = st.columns(3)
                for i, code in enumerate(sorted(bought_codes)):
                    info     = cand_map.get(code, {})
                    ai_score = info.get("score", "—")
                    grade    = info.get("grade", "")
                    name     = info.get("name", code)
                    ref_cols[i % 3].success(f"**{name}** ({code})  AI:{ai_score}점 {grade}")
            else:
                st.info("스크리닝 후보 있으나 실제 매수 종목 없음")

    budget_per_pos = initial_capital / sc.MAX_POSITIONS

    # ── 프리셋 관리 ──────────────────────────────────────────
    st.divider()
    _presets = _bt_load_presets()
    with st.expander("💾 파라미터 프리셋", expanded=False):
        # 저장
        c_pn, c_ps = st.columns([3, 1])
        with c_pn:
            _pname = st.text_input("프리셋 이름", key="bt_preset_name", placeholder="예) 공격적 손절 세팅")
        with c_ps:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("💾 현재 설정 저장", key="bt_preset_save", use_container_width=True):
                if _pname.strip():
                    _snap = {k: st.session_state.get(k) for k in _BT_PRESET_KEYS}
                    _presets[_pname.strip()] = _snap
                    _bt_save_presets(_presets)
                    st.success(f"'{_pname.strip()}' 저장 완료!")
                    st.rerun()
                else:
                    st.warning("이름을 입력하세요.")
        # 불러오기 / 삭제
        if _presets:
            c_ps2, c_pl, c_pd = st.columns([3, 1, 1])
            with c_ps2:
                _sel = st.selectbox("저장된 프리셋", list(_presets.keys()), key="bt_preset_sel")
            with c_pl:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                if st.button("📂 불러오기", key="bt_preset_load", use_container_width=True):
                    for _k, _v in _presets[_sel].items():
                        if _v is not None:
                            st.session_state[_k] = _v
                    st.rerun()
            with c_pd:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                if st.button("🗑 삭제", key="bt_preset_del", use_container_width=True):
                    del _presets[_sel]
                    _bt_save_presets(_presets)
                    st.rerun()
        else:
            st.caption("저장된 프리셋 없음")

    st.divider()
    st.markdown("##### 📐 파라미터 설정")

    opt_mode = st.radio(
        "최적화 방식",
        ["none", "grid", "bayesian"],
        format_func=lambda x: {"none": "▶ 단일 실행", "grid": "🔲 그리드 서치", "bayesian": "🧠 베이지안 최적화"}[x],
        horizontal=True,
        key="bt_opt_mode",
    )
    if opt_mode == "grid":
        st.caption("범위 체크 시 모든 조합을 캐시 데이터로 한번에 계산합니다.")
    elif opt_mode == "bayesian":
        st.caption("optuna TPE 샘플러로 샤프 비율 최대화 파라미터를 자동 탐색합니다.")

    def _param_row(label, single_val, single_min, single_max, single_step,
                   r_min_def, r_max_def, r_step_def, fmt=".2f"):
        c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1.5])
        with c1:
            use_range = st.checkbox(f"범위: {label}", key=f"rng_{label}") if opt_mode != "none" else False
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

    st.markdown("**트레이딩 파라미터**")
    rng_k, sv_k, rmin_k, rmax_k, rstep_k = _param_row("K값",     sc.K,                      0.1, 1.0, 0.05, 0.3, 0.7, 0.1, ".2f")
    rng_ls, sv_ls, rmin_ls, rmax_ls, rstep_ls = _param_row("손절(%)",  sc.LOSS_RATE*100,          0.5, 5.0, 0.1,  1.0, 4.0, 0.5, ".1f")
    rng_tr, sv_tr, rmin_tr, rmax_tr, rstep_tr = _param_row("트레일(%)", sc.TRAILING_STOP_RATE*100, 0.5, 5.0, 0.1,  1.0, 4.0, 0.5, ".1f")

    with st.expander("🤖 Scorer 점수 배점 파라미터", expanded=False):
        rng_sbr, sv_sbr, rmin_sbr, rmax_sbr, rstep_sbr = _param_row("변동성돌파(최대점)", 40.0, 10.0, 60.0, 1.0, 20.0, 60.0, 5.0, ".0f")
        rng_sad, sv_sad, rmin_sad, rmax_sad, rstep_sad = _param_row("AD Line 점수",      15.0,  5.0, 30.0, 1.0,  5.0, 25.0, 5.0, ".0f")
        rng_sca, sv_sca, rmin_sca, rmax_sca, rstep_sca = _param_row("캔들패턴(해머)",    10.0,  0.0, 20.0, 1.0,  0.0, 20.0, 5.0, ".0f")
        rng_ssb, sv_ssb, rmin_ssb, rmax_ssb, rstep_ssb = _param_row("강봉(60분) 점수",  15.0,  0.0, 30.0, 1.0,  5.0, 25.0, 5.0, ".0f")
        rng_swl, sv_swl, rmin_swl, rmax_swl, rstep_swl = _param_row("관심종목 보너스",  10.0,  0.0, 20.0, 1.0,  0.0, 20.0, 5.0, ".0f")
        sv_llm      = st.number_input("LLM 고정 점수 (백테스트용, 중립=5)",  min_value=0,   max_value=10,  value=5,                      step=1, key="sv_llm_fixed")
        sv_dart     = st.number_input("DART 고정 점수 (백테스트용, 중립=0)", min_value=-10, max_value=10,  value=0,                      step=1, key="sv_dart_fixed")
        sv_minscore = st.number_input("스크리닝 최소 점수 (MIN_SCORE)",      min_value=0,   max_value=100, value=sc.CONFIRM_SCORE_MIN,   step=5, key="sv_min_score")

    if opt_mode == "bayesian":
        n_trials = st.slider("베이지안 시도 횟수 (n_trials)", 10, 200, 50, key="bt_n_trials")
    else:
        n_trials = 50

    is_grid  = (opt_mode == "grid") and (
        rng_k or rng_ls or rng_tr or
        rng_sbr or rng_sad or rng_sca or rng_ssb or rng_swl
    )
    is_bayes = opt_mode == "bayesian"

    # ── 파라미터 변경 감지 → 결과 자동 초기화 ──
    _fingerprint = (
        tuple(sorted(bt_selected_dates)) if bt_selected_dates else "",
        pool_option,
        round(sv_k, 2) if not rng_k else (round(rmin_k, 2), round(rmax_k, 2), round(rstep_k, 2)),
        round(sv_ls, 2) if not rng_ls else (round(rmin_ls, 2), round(rmax_ls, 2), round(rstep_ls, 2)),
        round(sv_tr, 2) if not rng_tr else (round(rmin_tr, 2), round(rmax_tr, 2), round(rstep_tr, 2)),
        opt_mode,
        round(sv_sbr or 0), round(sv_sad or 0), round(sv_sca or 0), round(sv_ssb or 0), round(sv_swl or 0),
        sv_llm, sv_dart, sv_minscore,
    )
    if st.session_state.get("bt_fingerprint") != _fingerprint:
        st.session_state["bt_fingerprint"] = _fingerprint
        st.session_state.pop("bt_result", None)
        st.session_state.pop("bt_grid",   None)
        st.session_state.pop("bt_bayes",  None)

    # ── 캐시 상태 표시 ──
    st.divider()
    if bt_use_cache:
        st.success(f"✅ 캐시 {len(bt_selected_dates)}일 선택됨 — {', '.join(bt_selected_dates)}")
    else:
        st.info("📥 위 '백테스트 날짜 선택'에서 날짜를 선택하세요.")

    # ── 실행 버튼 ──
    col_run1, col_run2 = st.columns([4, 1])
    with col_run1:
        run_btn = st.button("▶ 백테스트 실행", type="primary", use_container_width=True)
    with col_run2:
        if st.button("🗑 캐시 초기화", use_container_width=True):
            for k in ["bt_cache_key","bt_minute_data_range","bt_daily_data","bt_result","bt_grid"]:
                st.session_state.pop(k, None)
            st.rerun()

    if run_btn:
        prog_bar  = st.progress(0)
        prog_text = st.empty()
        try:
            if not bt_use_cache:
                st.error("백테스트 날짜를 선택하세요. 먼저 '1분봉 데이터 캐시 관리'에서 데이터를 수집하고 날짜를 선택하세요.")
                st.stop()

            stock_list     = _build_stock_list_ui(pool_option, custom_codes)
            budget_per_pos = initial_capital / sc.MAX_POSITIONS

            # ── 캐시 CSV에서 분봉 로드 ────────────────────────────
            from backtest.data_cache import load_minute_data_from_cache as _dc_load_r
            prog_text.caption("📦 캐시 로드 중…")
            _codes = {s["code"] for s in stock_list}
            minute_data_by_date = _dc_load_r(bt_selected_dates, codes=_codes)
            missing = [d for d in bt_selected_dates if d not in minute_data_by_date]
            if missing:
                st.warning(f"캐시 없는 날짜 스킵: {', '.join(missing)}")
            if not minute_data_by_date:
                st.error("선택된 날짜의 캐시 데이터가 없습니다. 먼저 데이터를 수집하세요.")
                st.stop()
            sd_str = min(bt_selected_dates)
            ed_str = max(bt_selected_dates)
            # 일봉: AD Line 계산용 버퍼 (시작일 20일 전부터) — yfinance 사용
            fetch_from = (datetime.strptime(sd_str, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")
            prog_bar.progress(0.3)
            from backtest.data_loader_yf import fetch_multi_ohlcv_yf
            daily_data = fetch_multi_ohlcv_yf(
                stock_list, fetch_from, ed_str,
                progress_cb=_make_cb(prog_bar, prog_text, "일봉 수집"))
            prog_bar.progress(0.7)

            from backtest.engine_multi_intraday import run_multi_intraday_backtest

            def _make_params(kv, lv, tv,
                             sbr=None, sad=None, sca=None, ssb=None, swl=None):
                # range 체크 시 sv값이 None일 수 있으므로 sc 기본값으로 보호
                _kv  = kv  if kv  is not None else sc.K
                _lv  = lv  if lv  is not None else sc.LOSS_RATE * 100
                _tv  = tv  if tv  is not None else sc.TRAILING_STOP_RATE * 100
                return {
                    "K": _kv, "LOSS_RATE": _lv/100,
                    "TRAILING_STOP_RATE": _tv/100,
                    "TRAILING_STOP_ACTIVATE_RATE": sc.TRAILING_STOP_ACTIVATE_RATE,
                    "USE_TRAILING_STOP": sc.USE_TRAILING_STOP,
                    "PROFIT_RATE": sc.PROFIT_RATE,
                    "INVEST_RATIO": sc.INVEST_RATIO,
                    "MAX_TRADES_PER_DAY": sc.MAX_TRADES_PER_DAY,
                    "budget_per_position": budget_per_pos,
                    # Scorer 배점 (백테스트 격리)
                    "SCORE_BREAKOUT_MAX": sbr if sbr is not None else (sv_sbr or 40),
                    "SCORE_AD_LINE":      sad if sad is not None else (sv_sad or 15),
                    "SCORE_CANDLE":       sca if sca is not None else (sv_sca or 10),
                    "SCORE_STRONG_BULL":  ssb if ssb is not None else (sv_ssb or 15),
                    "SCORE_WATCHLIST":    swl if swl is not None else (sv_swl or 10),
                    "LLM_FIXED":          sv_llm  if sv_llm  is not None else 5,
                    "DART_FIXED":         sv_dart if sv_dart is not None else 0,
                    "MIN_SCORE":          sv_minscore if sv_minscore is not None else 0,
                }

            def _run_one(params):
                return run_multi_intraday_backtest(
                    minute_data_by_date, daily_data, stock_list,
                    initial_capital, params=params
                )

            if is_bayes:
                # ── 베이지안 최적화 ─────────────────────────────────
                from backtest.optimizer import run_bayesian_optimization_multi
                from backtest.report import calc_sharpe as _calc_sharpe

                # 범위 체크된 파라미터만 최적화 bounds로 등록
                _bayes_bounds = {}
                if rng_k:
                    _bayes_bounds["K"] = (rmin_k, rmax_k)
                if rng_ls:
                    _bayes_bounds["LOSS_RATE"] = (rmin_ls / 100, rmax_ls / 100)
                if rng_tr:
                    _bayes_bounds["TRAILING_STOP_RATE"] = (rmin_tr / 100, rmax_tr / 100)
                if rng_sbr:
                    _bayes_bounds["SCORE_BREAKOUT_MAX"] = (rmin_sbr, rmax_sbr)
                if rng_sad:
                    _bayes_bounds["SCORE_AD_LINE"] = (rmin_sad, rmax_sad)
                if rng_sca:
                    _bayes_bounds["SCORE_CANDLE"] = (rmin_sca, rmax_sca)
                if rng_ssb:
                    _bayes_bounds["SCORE_STRONG_BULL"] = (rmin_ssb, rmax_ssb)
                if rng_swl:
                    _bayes_bounds["SCORE_WATCHLIST"] = (rmin_swl, rmax_swl)

                if not _bayes_bounds:
                    st.warning("베이지안 최적화: 탐색할 파라미터가 없습니다. 최소 1개 이상 '범위' 체크 후 실행하세요.")
                else:
                    _trial_counter = [0]
                    def _bayes_progress_cb(trial_no, total, sharpe):
                        _trial_counter[0] = trial_no
                        prog_bar.progress(trial_no / total)
                        prog_text.caption(f"🧠 Trial {trial_no}/{total}  최근 샤프={sharpe:.4f}")

                    # 기본 params에 현재 UI 값 반영 (범위 미설정 파라미터는 고정값)
                    _base_params = _make_params(sv_k, sv_ls, sv_tr)

                    opt_result = run_bayesian_optimization_multi(
                        minute_data_by_date, daily_data, stock_list,
                        initial_capital, _bayes_bounds, n_trials=n_trials,
                        progress_cb=_bayes_progress_cb,
                    )
                    prog_bar.progress(1.0)
                    prog_text.caption(f"✅ {opt_result['n_trials']}회 탐색 완료!  최고 샤프={opt_result['best_sharpe']:.4f}")
                    st.session_state["bt_bayes"]  = opt_result
                    st.session_state.pop("bt_result", None)
                    st.session_state.pop("bt_grid",   None)

            elif is_grid:
                # ── 그리드 서치 ────────────────────────────────────
                k_vals   = _range_values(rng_k,  sv_k,  rmin_k,  rmax_k,  rstep_k)
                ls_vals  = _range_values(rng_ls, sv_ls, rmin_ls, rmax_ls, rstep_ls)
                tr_vals  = _range_values(rng_tr, sv_tr, rmin_tr, rmax_tr, rstep_tr)
                sbr_vals = _range_values(rng_sbr, sv_sbr, rmin_sbr, rmax_sbr, rstep_sbr)
                sad_vals = _range_values(rng_sad, sv_sad, rmin_sad, rmax_sad, rstep_sad)
                sca_vals = _range_values(rng_sca, sv_sca, rmin_sca, rmax_sca, rstep_sca)
                ssb_vals = _range_values(rng_ssb, sv_ssb, rmin_ssb, rmax_ssb, rstep_ssb)
                swl_vals = _range_values(rng_swl, sv_swl, rmin_swl, rmax_swl, rstep_swl)

                import itertools
                combos = list(itertools.product(k_vals, ls_vals, tr_vals,
                                                sbr_vals, sad_vals, sca_vals, ssb_vals, swl_vals))
                total_combos = len(combos)
                grid_rows, combo_i = [], 0
                for (kv, lv, tv, sbrv, sadv, scav, ssbv, swlv) in combos:
                    combo_i += 1
                    prog_bar.progress(combo_i / total_combos)
                    prog_text.caption(f"⚙️ ({combo_i}/{total_combos})  손절={lv}% 트레일={tv}%")
                    r = _run_one(_make_params(kv, lv, tv, sbr=sbrv, sad=sadv, sca=scav, ssb=ssbv, swl=swlv))
                    ret, n_tr, wr, mdd = _calc_summary(r)
                    from backtest.report import calc_sharpe as _cs
                    row = {"K": kv, "손절(%)": lv, "트레일(%)": tv}
                    if rng_sbr: row["돌파점"] = sbrv
                    if rng_sad: row["AD점"]   = sadv
                    if rng_sca: row["캔들점"] = scav
                    if rng_ssb: row["강봉점"] = ssbv
                    if rng_swl: row["관심점"] = swlv
                    row.update({"전체수익률(%)": round(ret, 2), "거래수": n_tr,
                                "승률(%)": round(wr, 1), "MDD(%)": round(mdd, 2),
                                "샤프비율": round(_cs(r), 4)})
                    grid_rows.append(row)
                    _save_log({"timestamp": datetime.now().isoformat(), "type": "intraday_grid",
                               "date": sd_str, "K": kv, "loss_pct": lv, "trail_pct": tv,
                               "initial_capital": initial_capital, "return_pct": round(ret, 2),
                               "trades": n_tr, "win_rate": round(wr, 1), "mdd": round(mdd, 2)})
                prog_bar.progress(1.0); prog_text.caption(f"✅ {total_combos}개 조합 완료!")
                st.session_state["bt_grid"]   = grid_rows
                st.session_state.pop("bt_result", None)
                st.session_state.pop("bt_bayes",  None)
            else:
                # ── 단일 실행 ──────────────────────────────────────
                prog_text.caption("⚙️ 계산 중...")
                result = _run_one(_make_params(sv_k, sv_ls, sv_tr))
                prog_bar.progress(1.0); prog_text.caption("✅ 완료!")
                result["_period"] = {
                    "sd":      sd_str,
                    "ed":      ed_str,
                    "n_dates": len(minute_data_by_date),
                }
                st.session_state["bt_result"] = result
                st.session_state.pop("bt_grid",  None)
                st.session_state.pop("bt_bayes", None)
                ret, n_tr, wr, mdd = _calc_summary(result)
                _save_log({"timestamp": datetime.now().isoformat(), "type": "intraday",
                           "date": sd_str, "K": sv_k, "loss_pct": sv_ls, "trail_pct": sv_tr,
                           "initial_capital": initial_capital, "return_pct": round(ret, 2),
                           "trades": n_tr, "win_rate": round(wr, 1), "mdd": round(mdd, 2)})

        except Exception as e:
            prog_text.empty()
            st.error(f"오류: {e}")
            import traceback; st.code(traceback.format_exc())

    # ── 결과 표시 ──
    st.divider()
    if st.session_state.get("bt_bayes"):
        _show_bayes_result(st.session_state["bt_bayes"])
    elif st.session_state.get("bt_grid"):
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
    from trading_logger import load_log, list_log_dates, delete_log_dates, save_log_events

    log_dates = list_log_dates()

    if not log_dates:
        st.info("저장된 매매 로그가 없습니다. 실투/모의투자를 실행하면 자동으로 기록됩니다.")
    else:
        # ── 날짜별 관리 (다중 삭제) ──
        with st.expander("🗑 날짜별 로그 삭제", expanded=False):
            st.caption("삭제할 날짜를 선택하세요. 선택한 날짜의 전체 로그가 삭제됩니다.")
            dates_to_delete = st.multiselect(
                "삭제할 날짜",
                options=log_dates,
                format_func=lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}",
                key="del_dates"
            )
            if dates_to_delete:
                if st.button(f"🗑 선택한 {len(dates_to_delete)}개 날짜 삭제",
                             type="primary", key="btn_del_dates"):
                    delete_log_dates(dates_to_delete)
                    st.success(f"{len(dates_to_delete)}개 날짜 삭제 완료")
                    st.rerun()

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
                for i, e in enumerate(events):
                    label  = event_label.get(e["event"], e["event"])
                    detail = ""
                    if e["event"] == "buy_executed":
                        detail = f"{e['name']} {e['buy_price']:,}원 × {e['quantity']}주"
                    elif e["event"] == "sell_executed":
                        detail = f"{e['name']} {e['sell_price']:,}원 ({e.get('pnl_rate',0):+.2f}%) [{e['reason']}]"
                    elif e["event"] == "auto_buy":
                        detail = f"{e['name']} {e.get('score',0)}점"
                    elif e["event"] == "screening_result":
                        detail = f"{len(e.get('candidates',[]))}개 후보"
                    rows.append({"_idx": i, "삭제": False,
                                 "시각": e.get("ts",""), "이벤트": label, "내용": detail})

                if rows:
                    edit_df = pd.DataFrame(rows)
                    edited  = st.data_editor(
                        edit_df.drop(columns=["_idx"]),
                        use_container_width=True,
                        hide_index=True,
                        column_config={"삭제": st.column_config.CheckboxColumn("삭제", width="small")},
                        disabled=["시각","이벤트","내용"],
                        key=f"log_editor_{sel_date}",
                    )
                    del_indices = edited.index[edited["삭제"] == True].tolist()
                    if del_indices:
                        if st.button(f"🗑 선택한 {len(del_indices)}개 행 삭제",
                                     key="btn_del_rows"):
                            remaining = [e for i, e in enumerate(events)
                                         if i not in del_indices]
                            save_log_events(sel_date, remaining)
                            st.success(f"{len(del_indices)}개 행 삭제 완료")
                            st.rerun()


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
            {"파라미터": "코스닥 풀 크기",         "값": str(sc.KOSDAQ_POOL_SIZE)},
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
