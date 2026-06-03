import os
import time
from datetime import datetime
import strategy_config as sc
from strategy import (
    calc_target_price,
    calc_quantity,
    get_current_price,
    is_force_sell_time,
    check_profit_loss,
    update_trailing_stop,
)
from order import buy_stock, sell_stock, get_holding_quantity
from screener import run_screening

def get_now():
    return datetime.now().strftime("%H:%M:%S")

def wait_until_market_open():
    """장 시작 전 대기"""
    while True:
        now = datetime.now().strftime("%H:%M")
        if now >= sc.MARKET_OPEN:
            print(f"\n[{get_now()}] 장 시작! 매매 시작합니다.")
            break
        print(f"[{get_now()}] 장 시작 대기 중... (시작: {sc.MARKET_OPEN})", end="\r")
        time.sleep(10)

def run_single_stock(stock_code, stock_name, trade_no):
    """단일 종목 매매 루프"""
    print(f"\n{'='*40}")
    print(f"  [{trade_no}번째 매매] {stock_name} ({stock_code})")
    print(f"{'='*40}")

    # 목표 돌파가 계산
    print(f"\n[{get_now()}] 목표가 계산 중...")
    target_price = calc_target_price(stock_code)

    bought       = False  # 매수 여부
    buy_price    = 0      # 매수가
    quantity     = 0      # 보유 수량
    peak_price   = 0      # 매수 후 최고가 (트레일링 스탑용)
    breakout_seen = False  # 돌파 후 고점 보류 상태인지 (재진입 판단용)

    print(f"\n[{get_now()}] 매수 대기 중...")

    while True:
        now_str = datetime.now().strftime("%H:%M")

        # 강제 청산 시간 도달
        if is_force_sell_time():
            if bought and quantity > 0:
                print(f"\n[{get_now()}] ⏰ 강제 청산 시간 도달")
                sell_stock(stock_code, quantity)
            else:
                print(f"\n[{get_now()}] ⏰ 강제 청산 시간 — 미체결 상태로 종료")
            return "강제청산"

        # 장 종료
        if now_str > sc.MARKET_CLOSE:
            print(f"\n[{get_now()}] 장 종료")
            return "장종료"

        try:
            price_info    = get_current_price(stock_code)
            current_price = price_info["현재가"]

            if not bought:
                # 현재가가 목표 돌파가 이상일 때만 검토
                if current_price >= target_price:
                    # 돌파여유율 계산
                    gap = (current_price - target_price) / target_price * 100

                    # 진입 가능 조건:
                    # (1) 처음 돌파인데 여유율이 상한선 이내  → 즉시 진입
                    # (2) 고점 보류 후 재진입 밴드 안으로 내려옴 → 재진입
                    can_enter = gap <= sc.MAX_BREAKOUT_GAP

                    if can_enter:
                        if breakout_seen:
                            print(f"\n[{get_now()}] 🔁 재진입! 목표가 근처로 복귀 (여유율 {gap:.2f}%)")
                        else:
                            print(f"\n[{get_now()}] 🔔 돌파 감지! 현재가: {current_price:,}원 >= 목표가: {target_price:,}원 (여유율 {gap:.2f}%)")

                        quantity = calc_quantity(current_price)
                        if quantity < 1:
                            print(f"  ⚠️ 매수 가능 수량 없음 — 이 종목 건너뜀")
                            return "수량부족"
                        buy_stock(stock_code, quantity)
                        buy_price  = current_price
                        peak_price = current_price
                        bought     = True
                        print(f"  매수가: {buy_price:,}원 | 수량: {quantity}주")
                    else:
                        # 여유율이 상한선 초과 = 이미 고점, 보류하고 계속 감시
                        if not breakout_seen:
                            print(f"\n[{get_now()}] ⚠️ 돌파했으나 여유율 {gap:.2f}% > 상한 {sc.MAX_BREAKOUT_GAP}% — 고점 보류, 복귀 대기 시작")
                        breakout_seen = True
                        print(f"[{get_now()}] 고점 보류 중 | 현재가: {current_price:,}원 | 여유율: {gap:.2f}%", end="\r")

                else:
                    # 목표가 아래
                    # 완충 하한선 = 목표가 × (1 - 완충구간%)
                    drop_floor = target_price * (1 - sc.DROP_BUFFER / 100)

                    if breakout_seen:
                        if current_price < drop_floor:
                            # 완충구간마저 뚫고 떨어짐 = 진짜 돌파 실패
                            print(f"\n[{get_now()}] ❌ 완충선({drop_floor:,.0f}원) 하회 — 돌파 실패로 판단, 이 종목 포기")
                            return "돌파실패"
                        else:
                            # 살짝 밑돌았지만 완충구간 안 — 계속 감시
                            print(f"[{get_now()}] 완충구간 감시 중 | 현재가: {current_price:,}원 | 완충선: {drop_floor:,.0f}원", end="\r")
                    else:
                        print(f"[{get_now()}] 대기 중 | 현재가: {current_price:,}원 | 목표가: {target_price:,}원", end="\r")
            else:
                # 매도 조건 체크
                if sc.USE_TRAILING_STOP:
                    signal, rate, peak_price, stop_price, activated = update_trailing_stop(
                        buy_price, current_price, peak_price
                    )
                    rate_str = f"{rate*100:+.2f}%"
                    if activated and stop_price:
                        print(
                            f"[{get_now()}] 보유 중 | 현재가: {current_price:,}원 | "
                            f"수익률: {rate_str} | 고점: {peak_price:,}원 | 스탑: {stop_price:,.0f}원",
                            end="\r"
                        )
                    else:
                        print(
                            f"[{get_now()}] 보유 중 | 현재가: {current_price:,}원 | "
                            f"수익률: {rate_str} | 트레일 대기 중",
                            end="\r"
                        )
                    if signal == "트레일링스탑":
                        print(f"\n[{get_now()}] 📉 트레일링 스탑 발동! 고점 {peak_price:,}원 대비 하락 ({rate_str})")
                        sell_stock(stock_code, quantity)
                        return signal
                    elif signal == "손절":
                        print(f"\n[{get_now()}] 🔻 하드 손절 발동! ({rate_str})")
                        sell_stock(stock_code, quantity)
                        return signal
                else:
                    signal, rate = check_profit_loss(buy_price, current_price)
                    rate_str     = f"{rate*100:+.2f}%"
                    print(f"[{get_now()}] 보유 중 | 현재가: {current_price:,}원 | 수익률: {rate_str}", end="\r")
                    if signal:
                        print(f"\n[{get_now()}] {'✅ 익절' if signal == '익절' else '🔻 손절'} 신호! ({rate_str})")
                        sell_stock(stock_code, quantity)
                        return signal

        except Exception as e:
            print(f"\n[{get_now()}] ⚠️ 오류 발생: {e} — 재시도 중...")

        time.sleep(sc.CHECK_INTERVAL)


SCAN_CLOSE_TIME   = "100000"   # 장 시작 1시간 후 — 이 시각이 지나면 수집 종료
SCAN_TARGET_COUNT = 5          # 이 수 이상 모이면 즉시 수집 종료


def _telegram_enabled():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _collect_candidates(cooldown_map):
    """
    조건 충족 종목 수집 루프.
    종료 조건 (OR):
      1) 누적 후보 5개 이상
      2) 장 시작 후 1시간 경과 (10:00)
    반환: 쿨다운 제외된 후보 리스트 (돌파여유율 오름차순)
    """
    collected = {}   # code → 종목 dict (중복 방지, 여유율 낮은 것 유지)
    round_no  = 0

    while True:
        now_str = datetime.now().strftime("%H%M%S")

        # 종료 조건 2: 10:00 이후
        if now_str >= SCAN_CLOSE_TIME:
            reason = f"10:00 도달"
            break

        # 강제 청산 시간 초과 방어
        if is_force_sell_time():
            reason = "강제 청산 시간"
            break

        round_no += 1
        print(f"\n[{get_now()}] 스크리닝 #{round_no} — 현재 후보 {len(collected)}개")
        screened = run_screening()

        now_ts = time.time()
        for s in screened:
            code = s["code"]

            # 쿨다운 제외
            last_sold = cooldown_map.get(code)
            if last_sold and (now_ts - last_sold) < sc.SAME_STOCK_COOLDOWN:
                continue

            # 더 낮은 여유율로 갱신
            if code not in collected or s["돌파여유율"] < collected[code]["돌파여유율"]:
                collected[code] = s

        # 종료 조건 1: 5개 이상 수집
        if len(collected) >= SCAN_TARGET_COUNT:
            reason = f"후보 {len(collected)}개 달성"
            break

        # 아직 부족 → 대기 후 재스크리닝
        remaining = (
            datetime.strptime(SCAN_CLOSE_TIME, "%H%M%S").replace(
                year=datetime.now().year,
                month=datetime.now().month,
                day=datetime.now().day
            ) - datetime.now()
        ).seconds
        print(f"[{get_now()}] 후보 {len(collected)}/{SCAN_TARGET_COUNT}개 — "
              f"10:00까지 {remaining//60}분 남음. {sc.RESCREEN_WAIT}초 후 재스크리닝")
        time.sleep(sc.RESCREEN_WAIT)

    result = sorted(collected.values(), key=lambda x: x["돌파여유율"])
    print(f"\n[{get_now()}] 수집 종료 ({reason}) — 최종 후보 {len(result)}개")
    return result


def run_scheduler():
    """전체 스케줄러 메인 루프"""
    sc.print_config()

    use_telegram = _telegram_enabled()
    if use_telegram:
        print(f"  📱 텔레그램 연동: ON — 스크리닝 결과를 휴대폰으로 전송합니다.")
    else:
        print(f"  📵 텔레그램 연동: OFF — 자동으로 1순위 종목 선택합니다.")
    print(f"  수집 조건     : 후보 {SCAN_TARGET_COUNT}개 OR 10:00 도달 시 전송")

    # 장 시작 대기
    wait_until_market_open()

    trade_count  = 0
    daily_log    = []
    cooldown_map = {}

    while True:
        if trade_count >= sc.MAX_TRADES_PER_DAY:
            print(f"\n[{get_now()}] 최대 매매 횟수({sc.MAX_TRADES_PER_DAY}회) 도달 — 종료")
            break
        if is_force_sell_time():
            print(f"\n[{get_now()}] 강제 청산 시간 이후 — 신규 진입 없이 종료")
            break

        # ── 후보 수집 (5개 OR 10:00) ──
        available = _collect_candidates(cooldown_map)

        if not available:
            print(f"[{get_now()}] 조건 충족 종목 없음 — 오늘 매매 종료")
            break

        # ── 종목 선택 ──
        if use_telegram:
            from telegram_bot import send_and_wait, notify
            top5 = available[:5]
            print(f"\n[{get_now()}] 📱 텔레그램으로 결과 전송 중... ({len(top5)}개)")
            selected = send_and_wait(top5, timeout=300)

            if selected is None:
                print(f"[{get_now()}] ⏰ 5분 타임아웃 — 오늘 매매 없이 종료")
                break
            if selected == "PASS":
                print(f"[{get_now()}] ⏭ 패스 선택 — 오늘 매매 없이 종료")
                break

            target = next((s for s in available if s["code"] == selected["code"]), selected)
        else:
            target = available[0]

        trade_count += 1
        result = run_single_stock(target["code"], target["name"], trade_count)

        # 매매 결과 텔레그램 알림
        if use_telegram:
            from telegram_bot import notify
            emoji = "✅" if result in ("익절", "트레일링스탑") else "🔻" if result == "손절" else "⏰"
            notify(f"{emoji} *{target['name']}* 매매 완료\n결과: {result}")

        # 청산 시각 기록 (쿨다운용)
        cooldown_map[target["code"]] = time.time()

        daily_log.append({
            "종목": target["name"],
            "결과": result
        })

        # 장 종료/강제청산이면 루프 탈출
        if result in ("장종료", "강제청산"):
            break

        print(f"\n[{get_now()}] 청산 완료 — 다음 기회 탐색 중... (5초 대기)")
        time.sleep(5)

    # 당일 결과 요약
    print(f"\n{'='*40}")
    print(f"  당일 매매 결과 요약")
    print(f"{'='*40}")
    if daily_log:
        for i, log in enumerate(daily_log):
            print(f"  {i+1}. {log['종목']} → {log['결과']}")
    else:
        print("  매매 없음")
    print(f"{'='*40}\n")