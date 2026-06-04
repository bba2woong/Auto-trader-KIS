"""
scheduler.py — 멀티 포지션 + 5분 주기 실시간 스크리닝 스케줄러

흐름:
  장 시작 → 포지션 예산 계산 (총예산 / MAX_POSITIONS)
  → SCREENING_INTERVAL 분마다:
       스크리닝 → 빈 슬롯 수만큼 텔레그램 전송 → 종목 선택 → 매수
       (각 포지션은 독립 스레드로 트레일링/손절 감시)
  → 15:20 강제 청산
"""
import os
import time
import random
import threading
from datetime import datetime
import strategy_config as sc
import trading_logger as tlog
from strategy import (
    calc_target_price,
    calc_quantity,
    calc_position_budget,
    get_current_price,
    is_force_sell_time,
    check_profit_loss,
    update_trailing_stop,
)
from order import buy_stock, sell_stock
from screener import run_screening


def get_now():
    return datetime.now().strftime("%H:%M:%S")


def wait_until_market_open():
    while True:
        now = datetime.now().strftime("%H:%M")
        if now >= sc.MARKET_OPEN:
            print(f"\n[{get_now()}] 장 시작! 매매 시작합니다.")
            break
        print(f"[{get_now()}] 장 시작 대기 중... (시작: {sc.MARKET_OPEN})", end="\r")
        time.sleep(10)


def _telegram_enabled():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


# ──────────────────────────────────────────
# 단일 종목 매매 루프 (스레드로 실행)
# ──────────────────────────────────────────

def run_single_stock(stock_code, stock_name, slot_no, budget, on_close=None,
                     restore_buy_price=0, restore_quantity=0, stop_event=None):
    """
    단일 종목 매매 루프. 스레드로 실행.
    budget             : 포지션당 배정 예산 (원)
    on_close           : 청산 시 호출할 콜백 (result, stock_code)
    restore_buy_price  : 재시작 복구 시 기존 매수가 (0이면 신규 진입 대기)
    restore_quantity   : 재시작 복구 시 기존 보유 수량
    stop_event         : 외부에서 강제 청산 요청 시 set()
    """
    tag = f"[슬롯{slot_no}] {stock_name}({stock_code})"
    print(f"\n{'='*44}")
    print(f"  {tag} {'복구 모니터링' if restore_buy_price else '진입 준비'}")
    print(f"  예산: {budget:,}원")
    print(f"{'='*44}")

    # 복구 모드: 이미 보유 중인 포지션 → 즉시 모니터링 시작
    if restore_buy_price > 0:
        bought    = True
        buy_price = restore_buy_price
        quantity  = restore_quantity
        peak_price = restore_buy_price
        target_price = 0
        print(f"  {tag} ↩️ 복구: 매수가 {buy_price:,}원 × {quantity}주")
    else:
        try:
            target_price = calc_target_price(stock_code)
        except Exception as e:
            print(f"\n{tag} 목표가 계산 실패: {e}")
            if on_close:
                on_close("오류", stock_code)
            return
        bought    = False
        buy_price = 0
        quantity  = 0
        peak_price = 0

    breakout_seen = False
    error_count   = 0          # 연속 에러 횟수
    MAX_ERRORS    = 10         # 이 횟수 초과 시 강제 청산

    print(f"\n[{get_now()}] {tag} 매수 대기 중...")

    def _do_sell(sell_price, reason):
        """매도 실행 + 로그 + 알람봇 공통 처리"""
        sell_stock(stock_code, quantity)
        tlog.log_sell(stock_code, stock_name, buy_price, sell_price, quantity, reason, slot_no)
        try:
            from telegram_alarm import notify_sell_filled
            notify_sell_filled(stock_name, buy_price, sell_price, quantity, reason)
        except Exception:
            pass

    while True:
        now_str = datetime.now().strftime("%H:%M")

        # 외부 강제 청산 요청 (전량매도 버튼 등)
        if stop_event and stop_event.is_set() and bought and quantity > 0:
            print(f"\n[{get_now()}] {tag} 📤 외부 전량매도 요청")
            try:
                cp = get_current_price(stock_code).get("현재가", buy_price)
                _do_sell(cp, "전량매도")
            except Exception as e:
                print(f"  ⚠️ 전량매도 실패: {e}")
            if on_close:
                on_close("전량매도", stock_code)
            return

        if is_force_sell_time():
            if bought and quantity > 0:
                print(f"\n[{get_now()}] {tag} ⏰ 강제 청산")
                try:
                    cp = get_current_price(stock_code).get("현재가", buy_price)
                    _do_sell(cp, "강제청산")
                except Exception:
                    tlog.log_sell(stock_code, stock_name, buy_price, buy_price, quantity, "강제청산", slot_no)
                result = "강제청산"
            else:
                result = "강제청산(미체결)"
            if on_close:
                on_close(result, stock_code)
            return

        if now_str > sc.MARKET_CLOSE:
            if bought and quantity > 0:
                try:
                    sell_stock(stock_code, quantity)
                except Exception as e:
                    print(f"\n{tag} 장종료 매도 실패: {e}")
            if on_close:
                on_close("장종료", stock_code)
            return

        try:
            current_price = get_current_price(stock_code)["현재가"]
            error_count = 0  # 성공 시 에러 카운터 리셋

            if not bought:
                if current_price >= target_price:
                    gap       = (current_price - target_price) / target_price * 100
                    can_enter = gap <= sc.MAX_BREAKOUT_GAP

                    if can_enter:
                        quantity = calc_quantity(current_price, budget=budget)
                        if quantity < 1:
                            print(f"  {tag} ⚠️ 수량 부족 — 포기")
                            if on_close:
                                on_close("수량부족", stock_code)
                            return
                        buy_stock(stock_code, quantity)
                        buy_price  = current_price
                        peak_price = current_price
                        bought     = True
                        print(f"  {tag} 매수 @ {buy_price:,}원 × {quantity}주")
                        tlog.log_buy(stock_code, stock_name, buy_price, quantity, budget, slot_no)
                        # 알람봇: 매수 체결 알림
                        try:
                            from telegram_alarm import notify_buy_filled
                            notify_buy_filled(stock_name, buy_price, quantity)
                        except Exception:
                            pass
                        # PositionManager에 포지션 정보 등록 (수익률 알림용)
                        if on_close and hasattr(on_close, '__self__'):
                            on_close.__self__.register_buy(stock_code, stock_name, buy_price, quantity)
                    else:
                        if not breakout_seen:
                            print(f"\n[{get_now()}] {tag} ⚠️ 고점 보류 (여유율 {gap:.2f}%)")
                        breakout_seen = True
                        print(f"[{get_now()}] {tag} 고점보류 {current_price:,}원", end="\r")
                else:
                    drop_floor = target_price * (1 - sc.DROP_BUFFER / 100)
                    if breakout_seen and current_price < drop_floor:
                        print(f"\n[{get_now()}] {tag} ❌ 돌파 실패")
                        if on_close:
                            on_close("돌파실패", stock_code)
                        return
                    print(f"[{get_now()}] {tag} 대기 {current_price:,} / 목표 {target_price:,}", end="\r")
            else:
                if sc.USE_TRAILING_STOP:
                    signal, rate, peak_price, stop_price, activated = update_trailing_stop(
                        buy_price, current_price, peak_price
                    )
                    rate_str = f"{rate*100:+.2f}%"
                    if activated and stop_price:
                        print(f"[{get_now()}] {tag} {rate_str} | 고점:{peak_price:,} 스탑:{stop_price:,.0f}", end="\r")
                    if signal == "트레일링스탑":
                        print(f"\n[{get_now()}] {tag} 📉 트레일링 스탑 ({rate_str})")
                        _do_sell(current_price, "트레일링스탑")
                        if on_close:
                            on_close("트레일링스탑", stock_code)
                        return
                    elif signal == "손절":
                        print(f"\n[{get_now()}] {tag} 🔻 손절 ({rate_str})")
                        _do_sell(current_price, "손절")
                        if on_close:
                            on_close("손절", stock_code)
                        return
                else:
                    signal, rate = check_profit_loss(buy_price, current_price)
                    rate_str     = f"{rate*100:+.2f}%"
                    print(f"[{get_now()}] {tag} {rate_str}", end="\r")
                    if signal:
                        print(f"\n[{get_now()}] {tag} {'✅ 익절' if signal == '익절' else '🔻 손절'} ({rate_str})")
                        _do_sell(current_price, signal)
                        if on_close:
                            on_close(signal, stock_code)
                        return

        except Exception as e:
            error_count += 1
            print(f"\n[{get_now()}] {tag} ⚠️ API 오류 ({error_count}/{MAX_ERRORS}): {e}")

            # 연속 에러 한도 초과 → 보유 중이면 강제 청산 후 종료
            if error_count >= MAX_ERRORS:
                print(f"\n[{get_now()}] {tag} 🚨 연속 오류 {MAX_ERRORS}회 — 강제 청산")
                if bought and quantity > 0:
                    try:
                        sell_stock(stock_code, quantity)
                        tlog.log_sell(stock_code, stock_name, buy_price, buy_price,
                                      quantity, "오류청산", slot_no)
                    except Exception as sell_err:
                        print(f"  ⚠️ 오류청산 매도 실패: {sell_err}")
                if on_close:
                    on_close("오류청산", stock_code)
                return

        time.sleep(sc.CHECK_INTERVAL)


# ──────────────────────────────────────────
# 포지션 매니저
# ──────────────────────────────────────────

class PositionManager:
    """
    멀티 포지션 스레드 관리
    - 최대 MAX_POSITIONS개 동시 보유
    - 각 포지션은 독립 스레드
    """
    def __init__(self, budget_per_slot):
        self.budget        = budget_per_slot
        self.lock          = threading.Lock()
        self.active        = {}    # {code: thread}
        self.stop_events   = {}    # {code: threading.Event}  외부 강제 청산용
        self.positions_info = {}   # {code: {"name","buy_price","quantity"}}
        self.cooldown_map  = {}    # {code: timestamp}
        self.daily_log     = []
        self.trade_count   = 0

    @property
    def free_slots(self):
        return sc.MAX_POSITIONS - len(self.active)

    def in_cooldown(self, code):
        last = self.cooldown_map.get(code)
        return last and (time.time() - last) < sc.SAME_STOCK_COOLDOWN

    def register_buy(self, code, name, buy_price, quantity):
        """매수 체결 시 포지션 정보 등록 (수익률 알림용)"""
        with self.lock:
            self.positions_info[code] = {
                "name": name, "buy_price": buy_price, "quantity": quantity
            }

    def stop_all(self):
        """모든 포지션에 강제 청산 요청"""
        with self.lock:
            for event in self.stop_events.values():
                event.set()

    def open(self, stock, slot_no, jitter=True):
        """
        포지션 스레드 시작.
        jitter=True : 0~3초 랜덤 지연으로 동시 API 호출 분산
        stock에 buy_price_hint, qty_hint가 있으면 복구 모드로 실행
        """
        code              = stock["code"]
        restore_price     = stock.get("buy_price_hint", 0)
        restore_qty       = stock.get("qty_hint", 0)

        stop_event = threading.Event()
        with self.lock:
            self.stop_events[code] = stop_event

        def _run_with_jitter():
            if jitter:
                time.sleep(random.uniform(0, 3))
            run_single_stock(
                code, stock["name"], slot_no, self.budget, self._on_close,
                restore_buy_price=restore_price,
                restore_quantity=restore_qty,
                stop_event=stop_event,
            )

        t = threading.Thread(target=_run_with_jitter, daemon=True)
        with self.lock:
            self.active[code] = t
            self.trade_count += 1
        t.start()
        print(f"[{get_now()}] 포지션 오픈: {stock['name']} (슬롯{slot_no}) "
              f"| 활성: {len(self.active)}/{sc.MAX_POSITIONS}")

    def _on_close(self, result, code):
        pinfo = {}
        with self.lock:
            self.active.pop(code, None)
            self.stop_events.pop(code, None)
            pinfo = self.positions_info.pop(code, {})
            self.cooldown_map[code] = time.time()
            self.daily_log.append({"코드": code, "이름": pinfo.get("name", code), "결과": result})
        name = pinfo.get("name", code)
        print(f"\n[{get_now()}] 포지션 종료: {name} → {result} "
              f"| 활성: {len(self.active)}/{sc.MAX_POSITIONS}")

        # 기존 선택봇 알림 (종목명으로)
        if _telegram_enabled():
            from telegram_bot import notify
            emoji = "✅" if result in ("익절", "트레일링스탑") else "🔻" if result == "손절" else "⏰"
            notify(f"{emoji} {name} 청산 완료\n결과: {result}\n"
                   f"활성 포지션: {len(self.active)}/{sc.MAX_POSITIONS}")

    def print_summary(self):
        print(f"\n{'='*44}")
        print(f"  당일 매매 결과 요약 ({self.trade_count}회)")
        print(f"{'='*44}")
        for i, log in enumerate(self.daily_log):
            print(f"  {i+1}. {log['코드']} → {log['결과']}")
        if not self.daily_log:
            print("  매매 없음")
        print(f"{'='*44}\n")


# ──────────────────────────────────────────
# 메인 스케줄러
# ──────────────────────────────────────────

def _run_ai_cache_if_needed(stock_list, label):
    """필요 시 AI 캐시 갱신"""
    if not sc.USE_AI_SCORING:
        return
    from scoring.scorer import refresh_cache, needs_refresh
    if needs_refresh():
        refresh_cache(stock_list, label)


def _score_and_route(candidate):
    """
    종목 총점 계산 + 라우팅 결정
    candidate : screener.py run_screening() 반환 항목
                (변동성돌파, AD상승, 패턴, 돌파여유율 등 포함)
    반환      : (score_dict, route)  route = "auto_buy"|"confirm"|"skip"
    """
    if not sc.USE_AI_SCORING:
        from scoring.scorer import technical_score
        tech   = technical_score(candidate)
        auto_t = int(sc.AUTO_BUY_SCORE    * 0.7)
        conf_t = int(sc.CONFIRM_SCORE_MIN * 0.7)
        route  = "auto_buy" if tech >= auto_t else "confirm" if tech >= conf_t else "skip"
        return {"total": tech, "tech": tech, "llm": 0, "dart": 0}, route

    from scoring.scorer import total_score, routing
    score_dict = total_score(candidate)
    route      = routing(score_dict["total"])
    return score_dict, route


def _start_alert_thread(pm):
    """보유 종목 수익률 정기 알림 백그라운드 스레드"""
    def _alert_loop():
        import calendar
        last_alert_min = -1
        while True:
            now = datetime.now()
            hhmm = now.strftime("%H:%M")
            # 장 시작 30분 후(09:30)부터 15:00까지, POSITION_ALERT_INTERVAL 분마다
            if "09:30" <= hhmm <= "15:00":
                # 알림 주기에 해당하는 분인지 확인
                cur_min = now.hour * 60 + now.minute
                if cur_min % sc.POSITION_ALERT_INTERVAL == 0 and cur_min != last_alert_min:
                    last_alert_min = cur_min
                    _send_position_alert(pm)
            time.sleep(30)

    t = threading.Thread(target=_alert_loop, daemon=True)
    t.start()


def _send_position_alert(pm):
    """현재 보유 종목 수익률 조회 후 알람봇 전송"""
    try:
        from telegram_alarm import notify_position_status
        positions = []
        with pm.lock:
            infos = dict(pm.positions_info)
        for code, info in infos.items():
            try:
                cp = get_current_price(code)["현재가"]
                positions.append({
                    "name":          info["name"],
                    "buy_price":     info["buy_price"],
                    "current_price": cp,
                    "quantity":      info["quantity"],
                })
            except Exception:
                pass
        notify_position_status(positions)
    except Exception:
        pass


def _handle_mass_sell_query(pm, q_time):
    """개별 종목 선택 매도 문의 처리 (14:00, 14:30)"""
    from telegram_bot import send_partial_sell_query
    print(f"\n[{get_now()}] 📤 매도 종목 선택 문의 전송 ({q_time})")

    # 포지션 정보 + 현재가 조회
    positions = []
    with pm.lock:
        infos       = dict(pm.positions_info)
        stop_events = dict(pm.stop_events)
    for code, info in infos.items():
        try:
            cp = get_current_price(code)["현재가"]
        except Exception:
            cp = info["buy_price"]
        positions.append({
            "code":          code,
            "name":          info["name"],
            "buy_price":     info["buy_price"],
            "current_price": cp,
            "quantity":      info["quantity"],
        })

    if not positions:
        return

    sell_codes = send_partial_sell_query(positions, timeout=sc.TELEGRAM_CONFIRM_TIMEOUT)

    if not sell_codes:
        print(f"[{get_now()}] 🔒 전체 유지")
        return

    print(f"[{get_now()}] 📤 매도 실행: {sell_codes}")
    for code in sell_codes:
        ev = stop_events.get(code)
        if ev:
            ev.set()   # 해당 종목 스레드에만 강제 청산 신호


def restore_positions(pm):
    """
    재시작 시 KIS 잔고 조회 → 기존 보유 종목을 포지션 스레드로 복구.
    매수가는 평균단가(pchs_avg_pric)를 사용.
    """
    from api import get_balance
    from screener import KOSPI_200
    from watchlist import WATCHLIST_CODES

    try:
        holdings = get_balance()["보유종목"]
    except Exception as e:
        print(f"  [복구] 잔고 조회 실패: {e}")
        return

    if not holdings:
        print(f"  [복구] 보유 종목 없음 — 새로 시작")
        return

    # 종목명 조회용 맵
    name_map = {s["code"]: s["name"] for s in KOSPI_200}
    for code in WATCHLIST_CODES:
        if code not in name_map:
            name_map[code] = code

    restored = 0
    for h in holdings:
        code = h.get("pdno", "")
        qty  = int(h.get("hldg_qty", 0))
        if qty <= 0 or not code:
            continue
        name      = h.get("prdt_name") or name_map.get(code, code)
        avg_price = int(float(h.get("pchs_avg_pric", 0)))
        print(f"  [복구] {name} ({code}) {qty}주 @ {avg_price:,}원 — 포지션 복구 중...")

        # 기존 포지션 정보를 스레드에 주입 (jitter 없이 즉시 시작)
        slot_no = -(restored + 1)  # 복구 슬롯은 음수로 구분
        pm.open(
            {"code": code, "name": name, "buy_price_hint": avg_price, "qty_hint": qty},
            slot_no,
            jitter=False,
        )
        restored += 1

    if restored:
        print(f"  [복구] {restored}개 포지션 복구 완료")


def run_scheduler():
    """멀티 포지션 + 5분 주기 스케줄러 + AI 점수 기반 라우팅"""
    sc.print_config()

    use_telegram = _telegram_enabled()
    print(f"  📱 텔레그램: {'ON' if use_telegram else 'OFF'}")
    print(f"  최대 포지션: {sc.MAX_POSITIONS}개")
    print(f"  스크리닝 주기: {sc.SCREENING_INTERVAL}분")
    print(f"  AI 점수: {'ON' if sc.USE_AI_SCORING else 'OFF'}")
    print(f"  자동매수 Threshold: {sc.AUTO_BUY_SCORE}점 이상")
    print(f"  확인 요청 범위: {sc.CONFIRM_SCORE_MIN}~{sc.AUTO_BUY_SCORE}점")

    # 종목 풀 구성 (장 전 AI 분석용)
    from screener import build_screening_pool
    stock_list = build_screening_pool()

    # 장 전 AI 캐시 갱신
    _run_ai_cache_if_needed(stock_list, "장전")

    wait_until_market_open()

    # 포지션당 예산 (장 시작 시 1회 계산)
    print(f"\n[{get_now()}] 포지션 예산 계산 중...")
    budget_per_slot = calc_position_budget()

    pm = PositionManager(budget_per_slot)
    slot_counter     = 0
    last_screen_time = 0
    mass_sell_sent   = set()   # 전량매도 문의를 보낸 시각 추적

    # 재시작 시 기존 보유 포지션 복구
    print(f"\n[{get_now()}] 기존 포지션 복구 확인 중...")
    restore_positions(pm)

    # 보유 종목 수익률 정기 알림 스레드 시작
    _start_alert_thread(pm)

    while True:
        now_hhmm = datetime.now().strftime("%H:%M")

        # 종료 조건
        if is_force_sell_time():
            print(f"\n[{get_now()}] ⏰ 강제 청산 시간 — 신규 진입 중단, 기존 포지션 청산 대기")
            break

        if pm.trade_count >= sc.MAX_TRADES_PER_DAY:
            print(f"\n[{get_now()}] 최대 매매 횟수({sc.MAX_TRADES_PER_DAY}회) 도달")
            break

        # ── 14:00 / 14:30 전량매도 문의 ──
        for q_time in sc.MASS_SELL_QUERY_TIMES:
            if now_hhmm >= q_time and q_time not in mass_sell_sent:
                mass_sell_sent.add(q_time)
                if pm.active and use_telegram:
                    _handle_mass_sell_query(pm, q_time)

        # ── 스크리닝 종료 시각 이후 신규 진입 중단 ──
        if now_hhmm >= sc.SCREENING_END_TIME:
            print(f"[{get_now()}] 스크리닝 종료 시각({sc.SCREENING_END_TIME}) 이후 — 신규 진입 없음", end="\r")
            time.sleep(30)
            continue

        # 빈 슬롯 없으면 대기
        if pm.free_slots <= 0:
            print(f"[{get_now()}] 포지션 풀 ({sc.MAX_POSITIONS}/{sc.MAX_POSITIONS}) — 대기 중...", end="\r")
            time.sleep(10)
            continue

        # SCREENING_INTERVAL 분 경과 시에만 스크리닝
        now_ts = time.time()
        if now_ts - last_screen_time < sc.SCREENING_INTERVAL * 60:
            remaining = int(sc.SCREENING_INTERVAL * 60 - (now_ts - last_screen_time))
            print(f"[{get_now()}] 다음 스크리닝까지 {remaining}초 | "
                  f"활성 포지션: {len(pm.active)}/{sc.MAX_POSITIONS}", end="\r")
            time.sleep(10)
            continue

        # ── 스크리닝 ──
        print(f"\n[{get_now()}] 스크리닝 시작... (빈 슬롯: {pm.free_slots}개)")
        screened = run_screening()
        last_screen_time = time.time()

        # 필터: 쿨다운 제외 + 이미 보유 중 제외
        candidates = [
            s for s in screened
            if s["code"] not in pm.active and not pm.in_cooldown(s["code"])
        ]

        if not candidates:
            print(f"[{get_now()}] 조건 충족 종목 없음 — {sc.SCREENING_INTERVAL}분 후 재스크리닝")
            continue

        # ── 오후 1시 AI 캐시 갱신 체크 ──
        _run_ai_cache_if_needed(stock_list, "오후1시")

        # ── AI 점수 계산 + 라우팅 분류 ──
        auto_list    = []
        confirm_list = []
        screen_round = getattr(pm, "_screen_round", 0) + 1
        pm._screen_round = screen_round

        for cand in candidates:
            score_dict, route = _score_and_route(cand)
            cand["score"]        = score_dict["total"]
            cand["score_detail"] = score_dict
            cand["route"]        = route
            print(f"  {cand['name']:12s} 총점: {score_dict['total']:3d}점 "
                  f"(기술:{score_dict['tech']} LLM:{score_dict['llm']} DART:{score_dict['dart']}) "
                  f"→ {route}")
            if route == "auto_buy":
                auto_list.append(cand)
            elif route == "confirm":
                confirm_list.append(cand)

        # 스크리닝 결과 로그
        tlog.log_screening(screen_round, auto_list + confirm_list)

        # ── 자동 매수 ──
        for stock in auto_list:
            if pm.free_slots <= 0 or pm.trade_count >= sc.MAX_TRADES_PER_DAY:
                break
            print(f"\n[{get_now()}] 🤖 자동 매수: {stock['name']} ({stock['score']}점)")
            slot_counter += 1
            pm.open(stock, slot_counter)
            if use_telegram:
                from telegram_bot import notify
                d = stock["score_detail"]
                notify(f"🤖 자동 매수\n{stock['name']} — {stock['score']}점\n"
                       f"기술:{d['tech']} LLM:{d['llm']} DART:{d['dart']}")
            time.sleep(1)

        # ── 텔레그램 확인 요청 ──
        if confirm_list and pm.free_slots > 0:
            if use_telegram:
                from telegram_bot import send_and_wait_multi, notify
                free = pm.free_slots
                tlog.log_confirm_sent(confirm_list[:5])
                notify(f"📊 포지션: {len(pm.active)}/{sc.MAX_POSITIONS}개 활성\n"
                       f"빈 슬롯 {free}개 — 최대 {free}개 선택 가능합니다.")
                selected_list = send_and_wait_multi(
                    confirm_list[:5],
                    max_select=free,
                    timeout=sc.TELEGRAM_CONFIRM_TIMEOUT,
                )
                if selected_list == "PASS":
                    print(f"[{get_now()}] ⏭ 패스")
                elif not selected_list:
                    print(f"[{get_now()}] ⏰ 응답 없음 — 이번 라운드 패스")
                else:
                    for sel in selected_list:
                        if pm.free_slots <= 0:
                            break
                        target = next((s for s in confirm_list if s["code"] == sel["code"]), None)
                        if target:
                            tlog.log_confirm_selected(target)
                            slot_counter += 1
                            pm.open(target, slot_counter)
                            time.sleep(0.5)
            else:
                # 텔레그램 없으면 confirm도 자동 진입
                for stock in confirm_list:
                    if pm.free_slots <= 0:
                        break
                    slot_counter += 1
                    pm.open(stock, slot_counter)
                    time.sleep(1)

    # 기존 포지션 스레드 종료 대기
    print(f"\n[{get_now()}] 모든 포지션 종료 대기 중...")
    for t in list(pm.active.values()):
        t.join(timeout=300)  # 최대 5분 대기

    pm.print_summary()
