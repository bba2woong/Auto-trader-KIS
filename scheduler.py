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
                     restore_buy_price=0, restore_quantity=0, stop_event=None,
                     on_buy=None):
    """
    단일 종목 매매 루프. 스레드로 실행.
    budget             : 포지션당 배정 예산 (원)
    on_close           : 청산 시 호출할 콜백 (result, stock_code)
    restore_buy_price  : 재시작 복구 시 기존 매수가 (0이면 신규 진입 대기)
    restore_quantity   : 재시작 복구 시 기존 보유 수량
    stop_event         : 외부에서 강제 청산 요청 시 set()
    on_buy             : 매수 체결 시 호출할 콜백 (stock_code) — 슬롯 메타 갱신용
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
            # 수동매수([수동] 태그)는 목표가 실패해도 즉시 시장가 매수로 폴백
            if "[수동]" in stock_name:
                print(f"\n{tag} ⚠️ 목표가 조회 실패 ({e}) — 시장가 즉시 매수로 폴백")
                target_price = 0   # 0이면 while 루프 첫 틱에 current_price >= 0 → 즉시 매수
            else:
                print(f"\n{tag} 목표가 계산 실패: {e}")
                if on_close:
                    on_close("오류", stock_code)
                return
        bought    = False
        buy_price = 0
        quantity  = 0
        peak_price = 0

    breakout_seen = False
    error_count   = 0    # 연속 에러 횟수
    MAX_ERRORS    = 10   # 이 횟수 초과 시 강제 청산
    wait_start    = time.time()   # 매수 대기 시작 시각 (1시간 타임아웃용)

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
            _price_exc = None
            try:
                current_price = get_current_price(stock_code)["현재가"]
            except Exception as _e1:
                _price_exc = _e1
                try:
                    # strategy.py 실패 시 api.py 경로로 폴백
                    from api import get_stock_price as _gsp
                    current_price = _gsp(stock_code)["현재가"]
                    _price_exc = None   # 폴백 성공
                except Exception as _e2:
                    # 두 경로 모두 실패 → 수동매수이고 미체결 상태면 즉시 포기
                    if "[수동]" in stock_name and not bought:
                        msg = (f"⚠️ 수동매수 취소: {stock_name}({stock_code})\n"
                               f"현재가 조회 불가 (모의투자 서버 미지원 종목일 수 있음)\n"
                               f"실전투자 모드에서 시도하거나 HTS에서 직접 매수하세요.")
                        print(f"\n[{get_now()}] {tag} {msg}")
                        try:
                            from telegram_bot import notify
                            notify(msg)
                        except Exception:
                            pass
                        if on_close:
                            on_close("오류", stock_code)
                        return
                    raise _e2   # 보유 중이면 기존 에러 카운터로 처리
            if _price_exc:
                raise _price_exc
            error_count = 0  # 성공 시 에러 카운터 리셋

            # ── HTS 수동매도 감지: 매 루프마다 실제 잔고 확인 ──
            # 잔고 조회 오류는 error_count에 영향 없이 별도 처리
            if bought:
                try:
                    from order import get_holding_quantity
                    actual_qty = get_holding_quantity(stock_code)
                    if actual_qty == 0:
                        sell_p = current_price  # 현재가로 기록 (이미 조회됨)
                        print(f"\n[{get_now()}] {tag} 📤 잔고 0 감지 — HTS 수동매도 처리")
                        tlog.log_sell(stock_code, stock_name, buy_price, sell_p,
                                      quantity, "HTS수동매도", slot_no)
                        try:
                            from telegram_alarm import notify_sell_filled
                            notify_sell_filled(stock_name, buy_price, sell_p,
                                               quantity, "HTS수동매도")
                        except Exception:
                            pass
                        if on_close:
                            on_close("HTS수동매도", stock_code)
                        return
                except Exception:
                    pass  # 잔고 조회 실패 시 무시, error_count 증가 없음

            if not bought:
                # 1시간 타임아웃 — 장기 미체결 슬롯 반환
                if time.time() - wait_start > 3600:
                    print(f"\n[{get_now()}] {tag} ⏰ 매수 대기 1시간 초과 — 슬롯 반환")
                    try:
                        from telegram_alarm import notify_alarm
                        notify_alarm(
                            f"⏰ [{stock_name}] 매수 대기 1시간 초과\n"
                            f"슬롯 반환 — 새 종목 탐색 재개"
                        )
                    except Exception:
                        pass
                    if on_close:
                        on_close("타임아웃", stock_code)
                    return

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
                        # 슬롯 메타 bought 상태 갱신 (교체 로직용)
                        if on_buy:
                            try:
                                on_buy(stock_code)
                            except Exception:
                                pass
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
            err_msg = str(e)
            error_count += 1
            print(f"\n[{get_now()}] {tag} ⚠️ API 오류 ({error_count}/{MAX_ERRORS}): {e}")

            # 주문가능금액 초과 → 실제 잔액으로 수량 재계산 후 1회 재시도
            BUDGET_ERRORS = ("주문가능금액을 초과", "매수가능금액 초과", "잔고부족", "증거금 부족")
            if not bought and any(kw in err_msg for kw in BUDGET_ERRORS):
                try:
                    from api import get_balance as _gb
                    _bal = _gb()
                    _avail = int(float(_bal["계좌요약"][0].get("ord_psbl_cash", 0)))
                    if _avail <= 0:
                        _avail = int(float(_bal["계좌요약"][0].get("dnca_tot_amt", 0)))
                    _new_qty = _avail // current_price if current_price > 0 else 0
                    print(f"\n[{get_now()}] {tag} 💰 주문가능금액 {_avail:,}원 → 수량 재조정 {quantity}주 → {_new_qty}주")
                    if _new_qty >= 1:
                        buy_stock(stock_code, _new_qty)
                        quantity   = _new_qty
                        buy_price  = current_price
                        peak_price = current_price
                        bought     = True
                        print(f"  {tag} 매수 @ {buy_price:,}원 × {quantity}주 (수량 재조정)")
                        tlog.log_buy(stock_code, stock_name, buy_price, quantity, budget, slot_no)
                        try:
                            from telegram_alarm import notify_buy_filled
                            notify_buy_filled(stock_name, buy_price, quantity)
                        except Exception:
                            pass
                        if on_close and hasattr(on_close, '__self__'):
                            on_close.__self__.register_buy(stock_code, stock_name, buy_price, quantity)
                        if on_buy:
                            try:
                                on_buy(stock_code)
                            except Exception:
                                pass
                        error_count = 0
                    else:
                        print(f"\n[{get_now()}] {tag} 🚫 주문가능금액 부족 ({_avail:,}원) — 슬롯 반환")
                        try:
                            from telegram_alarm import notify_alarm
                            notify_alarm(
                                f"🚫 [{stock_name}] 주문가능금액 부족\n"
                                f"가용금액: {_avail:,}원 / 필요: {current_price:,}원 × 1주\n"
                                f"슬롯 반환"
                            )
                        except Exception:
                            pass
                        if on_close:
                            on_close("매수불가", stock_code)
                        return
                except Exception as _retry_err:
                    print(f"\n[{get_now()}] {tag} 수량 재조정 실패: {_retry_err}")
                    if on_close:
                        on_close("매수불가", stock_code)
                    return

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
        self.slot_meta     = {}    # {code: {"score","bought","slot_no","name"}} 교체 로직용
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
            if code in self.slot_meta:
                self.slot_meta[code]["bought"] = True

    def mark_bought(self, code):
        """on_buy 콜백에서 호출 — bought 상태 True로 갱신"""
        with self.lock:
            if code in self.slot_meta:
                self.slot_meta[code]["bought"] = True

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
        already_bought = restore_price > 0   # 복구 모드는 이미 매수 완료
        with self.lock:
            self.stop_events[code] = stop_event
            self.slot_meta[code] = {
                "score":   stock.get("score", 0),
                "bought":  already_bought,
                "slot_no": slot_no,
                "name":    stock.get("name", code),
            }

        def _run_with_jitter():
            if jitter:
                time.sleep(random.uniform(0, 3))
            run_single_stock(
                code, stock["name"], slot_no, self.budget, self._on_close,
                restore_buy_price=restore_price,
                restore_quantity=restore_qty,
                stop_event=stop_event,
                on_buy=self.mark_bought,
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
            self.slot_meta.pop(code, None)
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


STOP_KEY = "_kis_scheduler_stop"   # sys.modules 정지 신호 키


def _get_stop_event() -> threading.Event:
    """앱과 공유하는 정지 이벤트 (sys.modules에 저장)"""
    import sys as _sys
    if STOP_KEY not in _sys.modules:
        _sys.modules[STOP_KEY] = threading.Event()
    return _sys.modules[STOP_KEY]


def run_scheduler():
    """멀티 포지션 + 5분 주기 스케줄러 + AI 점수 기반 라우팅"""
    stop_ev = _get_stop_event()
    stop_ev.clear()   # 시작 시 초기화

    # 상태 파일 저장 (watchdog 재시작 후 복구 감지용)
    try:
        import atexit, config as _cfg_state
        from trading_state import save_state, clear_state as _cs
        save_state(mode=_cfg_state.MODE, running=True)
        # 재부팅/강제 종료 시에도 clear_state 보장
        atexit.register(_cs)
    except Exception:
        pass

    pm = None   # finally에서 참조하므로 try 앞에 초기화

    try:
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

        # 09:00 직후 KIS 서버 Rate Limit 완화 대기 (수만 건 동시 접속 분산)
        print(f"[{get_now()}] 잔고 조회 전 5초 대기 (서버 부하 분산)...")
        time.sleep(10)

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

        # 텔레그램 수동 매수 모니터 시작 (6자리 코드 메시지 → 즉시 매수)
        if _telegram_enabled():
            from telegram_bot import start_manual_buy_monitor
            start_manual_buy_monitor(pm, budget_per_slot, stop_event=_get_stop_event())
            print(f"[{get_now()}] 📱 수동매수 모니터 시작 — 종목코드 6자리 메시지로 즉시 매수 가능")

        while True:
            now_hhmm = datetime.now().strftime("%H:%M")

            # 외부 정지 신호 (app.py 정지 버튼)
            if stop_ev.is_set():
                print(f"\n[{get_now()}] ⏹ 정지 요청 수신 — 모니터링 중단 (포지션 KIS 유지)")
                break

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

            # ── HTS 수동 매수 감지 (스크리닝 직전 잔고 확인) ──
            try:
                from api import get_balance as _get_bal
                _bal = _get_bal()
                _active_codes = set(pm.active.keys())
                for _item in _bal.get("보유종목", []):
                    _code = _item.get("pdno", "")
                    _qty  = int(_item.get("hldg_qty", 0))
                    _avg  = int(float(_item.get("pchs_avg_pric", 0)))
                    _name = _item.get("prdt_name", _code)
                    if _code and _code not in _active_codes and _qty > 0 and _avg > 0:
                        print(f"[{get_now()}] 📌 HTS 수동 매수 감지: {_name} — 모니터링 추가")
                        slot_counter += 1
                        pm.open(
                            {"code": _code, "name": _name,
                             "buy_price_hint": _avg, "qty_hint": _qty,
                             "score": 0, "route": "수동"},
                            slot_counter,
                        )
                        try:
                            from telegram_alarm import notify_alarm
                            notify_alarm(
                                f"📌 수동 매수 종목 모니터링 시작\n"
                                f"종목: {_name} ({_code})\n"
                                f"평균단가: {_avg:,}원 × {_qty}주\n"
                                f"자동 손절/트레일링 스탑 적용됩니다."
                            )
                        except Exception:
                            pass
            except Exception as _e:
                print(f"[{get_now()}] 잔고 조회 실패 (수동매수 감지): {_e}")

            # ── 스크리닝 ──
            print(f"\n[{get_now()}] 스크리닝 시작... (빈 슬롯: {pm.free_slots}개)")
            screened = run_screening(stop_event=stop_ev)   # 정지 신호 전달 → 즉시 중단 가능
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
            try:
                from telegram_alarm import notify_screening_result
                notify_screening_result(screen_round, auto_list + confirm_list)
            except Exception:
                pass

            # ── 매수 대기 중 슬롯 교체 (더 높은 점수 후보 등장 시) ──
            all_new = auto_list + confirm_list
            if all_new:
                with pm.lock:
                    waiting = [
                        (code, meta) for code, meta in pm.slot_meta.items()
                        if not meta.get("bought", True)
                    ]
                replaced_codes = set()
                for new_s in all_new:
                    for w_code, w_meta in waiting:
                        if w_code in replaced_codes:
                            continue
                        score_gap = new_s.get("score", 0) - w_meta.get("score", 0)
                        if score_gap >= 10:
                            print(f"\n[{get_now()}] 🔄 슬롯 교체: {w_meta['name']} "
                                  f"({w_meta['score']}점) → {new_s['name']} ({new_s.get('score',0)}점)")
                            try:
                                from telegram_alarm import notify_alarm
                                notify_alarm(
                                    f"🔄 포지션 교체\n"
                                    f"대기 중: {w_meta['name']} ({w_meta['score']}점)\n"
                                    f"→ 신규: {new_s['name']} ({new_s.get('score',0)}점)"
                                )
                            except Exception:
                                pass
                            ev = pm.stop_events.get(w_code)
                            if ev:
                                ev.set()
                            replaced_codes.add(w_code)
                            # 새 종목이 auto_list면 즉시 오픈, confirm_list면 아래 확인 단계에서 처리
                            if new_s in auto_list and pm.free_slots <= 0:
                                # 슬롯이 아직 닫히기 전이므로 아래 자동매수 루프가 잡을 수 있도록 유지
                                pass  # auto_list에 그대로 남겨 아래 자동매수 루프에서 처리
                            break

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
                    if selected_list == "RESTART":
                        print(f"[{get_now()}] 🔄 텔레그램 재시작 요청 — 즉시 재스크리닝")
                        last_screen_time = 0
                        continue
                    elif selected_list == "PASS":
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

        # while 루프 정상 탈출 → 정상 종료
        from trading_state import clear_state
        clear_state()

    except KeyboardInterrupt:
        print(f"\n[{get_now()}] 사용자 중지 (Ctrl+C) — 정상 종료 처리")
        try:
            from trading_state import clear_state
            from telegram_alarm import notify_alarm
            clear_state()
            notify_alarm("⏹ 트레이딩 수동 종료 (Ctrl+C)")
        except Exception:
            pass

    except Exception as e:
        # 예기치 못한 오류 → running=True 유지 (워치독이 비정상 종료로 감지)
        print(f"\n[{get_now()}] 🚨 예외 발생: {e}")
        try:
            from telegram_alarm import notify_alarm
            notify_alarm(f"🚨 트레이딩 비정상 종료\n오류: {e}")
        except Exception:
            pass
        raise

    finally:
        # 포지션 스레드 종료 대기 — 정상/비정상 무관하게 항상 실행
        if pm is not None:
            print(f"\n[{get_now()}] 모든 포지션 종료 대기 중...")
            for t in list(pm.active.values()):
                t.join(timeout=300)
            pm.print_summary()
