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
import threading
from datetime import datetime
import strategy_config as sc
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

def run_single_stock(stock_code, stock_name, slot_no, budget, on_close=None):
    """
    단일 종목 매매 루프. 스레드로 실행.
    budget   : 포지션당 배정 예산 (원)
    on_close : 청산 시 호출할 콜백 (result, stock_code)
    """
    tag = f"[슬롯{slot_no}] {stock_name}({stock_code})"
    print(f"\n{'='*44}")
    print(f"  {tag} 진입 준비")
    print(f"  예산: {budget:,}원")
    print(f"{'='*44}")

    try:
        target_price = calc_target_price(stock_code)
    except Exception as e:
        print(f"\n{tag} 목표가 계산 실패: {e}")
        if on_close:
            on_close("오류", stock_code)
        return

    bought        = False
    buy_price     = 0
    quantity      = 0
    peak_price    = 0
    breakout_seen = False

    print(f"\n[{get_now()}] {tag} 매수 대기 중...")

    while True:
        now_str = datetime.now().strftime("%H:%M")

        if is_force_sell_time():
            if bought and quantity > 0:
                print(f"\n[{get_now()}] {tag} ⏰ 강제 청산")
                sell_stock(stock_code, quantity)
                result = "강제청산"
            else:
                result = "강제청산(미체결)"
            if on_close:
                on_close(result, stock_code)
            return

        if now_str > sc.MARKET_CLOSE:
            if bought and quantity > 0:
                sell_stock(stock_code, quantity)
            if on_close:
                on_close("장종료", stock_code)
            return

        try:
            current_price = get_current_price(stock_code)["현재가"]

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
                        sell_stock(stock_code, quantity)
                        if on_close:
                            on_close("트레일링스탑", stock_code)
                        return
                    elif signal == "손절":
                        print(f"\n[{get_now()}] {tag} 🔻 손절 ({rate_str})")
                        sell_stock(stock_code, quantity)
                        if on_close:
                            on_close("손절", stock_code)
                        return
                else:
                    signal, rate = check_profit_loss(buy_price, current_price)
                    rate_str     = f"{rate*100:+.2f}%"
                    print(f"[{get_now()}] {tag} {rate_str}", end="\r")
                    if signal:
                        print(f"\n[{get_now()}] {tag} {'✅ 익절' if signal == '익절' else '🔻 손절'} ({rate_str})")
                        sell_stock(stock_code, quantity)
                        if on_close:
                            on_close(signal, stock_code)
                        return

        except Exception as e:
            print(f"\n[{get_now()}] {tag} ⚠️ {e}")

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
        self.budget       = budget_per_slot
        self.lock         = threading.Lock()
        self.active       = {}   # {code: thread}
        self.cooldown_map = {}   # {code: timestamp}
        self.daily_log    = []
        self.trade_count  = 0

    @property
    def free_slots(self):
        return sc.MAX_POSITIONS - len(self.active)

    def in_cooldown(self, code):
        last = self.cooldown_map.get(code)
        return last and (time.time() - last) < sc.SAME_STOCK_COOLDOWN

    def open(self, stock, slot_no):
        """포지션 스레드 시작"""
        code = stock["code"]
        t = threading.Thread(
            target=run_single_stock,
            args=(code, stock["name"], slot_no, self.budget, self._on_close),
            daemon=True,
        )
        with self.lock:
            self.active[code] = t
            self.trade_count += 1
        t.start()
        print(f"[{get_now()}] 포지션 오픈: {stock['name']} (슬롯{slot_no}) "
              f"| 활성: {len(self.active)}/{sc.MAX_POSITIONS}")

    def _on_close(self, result, code):
        with self.lock:
            self.active.pop(code, None)
            self.cooldown_map[code] = time.time()
            self.daily_log.append({"코드": code, "결과": result})
        print(f"\n[{get_now()}] 포지션 종료: {code} → {result} "
              f"| 활성: {len(self.active)}/{sc.MAX_POSITIONS}")

        if _telegram_enabled():
            from telegram_bot import notify
            emoji = "✅" if result in ("익절", "트레일링스탑") else "🔻" if result == "손절" else "⏰"
            notify(f"{emoji} *{code}* 청산 완료\n결과: {result}\n"
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

def run_scheduler():
    """멀티 포지션 + 5분 주기 스케줄러"""
    sc.print_config()

    use_telegram = _telegram_enabled()
    print(f"  📱 텔레그램: {'ON' if use_telegram else 'OFF'}")
    print(f"  최대 포지션: {sc.MAX_POSITIONS}개")
    print(f"  스크리닝 주기: {sc.SCREENING_INTERVAL}분")

    wait_until_market_open()

    # 포지션당 예산 (장 시작 시 1회 계산)
    print(f"\n[{get_now()}] 포지션 예산 계산 중...")
    budget_per_slot = calc_position_budget()

    pm = PositionManager(budget_per_slot)
    slot_counter = 0
    last_screen_time = 0

    while True:
        # 종료 조건
        if is_force_sell_time():
            print(f"\n[{get_now()}] ⏰ 강제 청산 시간 — 신규 진입 중단, 기존 포지션 청산 대기")
            break

        if pm.trade_count >= sc.MAX_TRADES_PER_DAY:
            print(f"\n[{get_now()}] 최대 매매 횟수({sc.MAX_TRADES_PER_DAY}회) 도달")
            break

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

        # ── 종목 선택 & 포지션 오픈 ──
        slots_to_fill = min(pm.free_slots, len(candidates))

        if use_telegram:
            from telegram_bot import send_and_wait, notify

            # 포지션 상태 포함해서 전송
            active_names = [c for c in pm.active.keys()]
            print(f"\n[{get_now()}] 📱 텔레그램 전송 (빈 슬롯 {slots_to_fill}개)...")
            notify(
                f"📊 포지션 현황: {len(pm.active)}/{sc.MAX_POSITIONS}개 활성\n"
                f"빈 슬롯 {slots_to_fill}개 — 종목을 선택해주세요."
            )

            selected = send_and_wait(
                candidates[:5],
                timeout=sc.TELEGRAM_CONFIRM_TIMEOUT,
            )

            if selected is None:
                print(f"[{get_now()}] ⏰ 응답 없음 — 이번 라운드 패스")
                continue
            if selected == "PASS":
                print(f"[{get_now()}] ⏭ 패스")
                continue

            target = next((s for s in candidates if s["code"] == selected["code"]), None)
            if target and pm.free_slots > 0:
                slot_counter += 1
                pm.open(target, slot_counter)
        else:
            # 자동: 빈 슬롯 수만큼 상위 종목 진입
            for stock in candidates[:slots_to_fill]:
                if pm.free_slots <= 0:
                    break
                slot_counter += 1
                pm.open(stock, slot_counter)
                time.sleep(1)  # 동시 API 호출 간격

    # 기존 포지션 스레드 종료 대기
    print(f"\n[{get_now()}] 모든 포지션 종료 대기 중...")
    for t in list(pm.active.values()):
        t.join(timeout=300)  # 최대 5분 대기

    pm.print_summary()
