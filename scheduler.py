import time
from datetime import datetime
import strategy_config as sc
from strategy import (
    calc_target_price,
    calc_quantity,
    get_current_price,
    is_force_sell_time,
    check_profit_loss,
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

    bought    = False  # 매수 여부
    buy_price = 0      # 매수가
    quantity  = 0      # 보유 수량
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
                        buy_price = current_price
                        bought    = True
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


def run_scheduler():
    """전체 스케줄러 메인 루프 (청산 후 재스크리닝 방식)"""
    sc.print_config()

    # 장 시작 대기
    wait_until_market_open()

    trade_count   = 0
    daily_log     = []
    cooldown_map  = {}  # {종목코드: 마지막 청산 시각} — 쿨다운 관리

    while True:
        # 종료 조건 1: 최대 매매 횟수 도달
        if trade_count >= sc.MAX_TRADES_PER_DAY:
            print(f"\n[{get_now()}] 오늘 최대 매매 횟수({sc.MAX_TRADES_PER_DAY}회) 도달 — 종료")
            break

        # 종료 조건 2: 강제 청산 시간 이후 (신규 진입 안 함)
        if is_force_sell_time():
            print(f"\n[{get_now()}] 강제 청산 시간 이후 — 신규 진입 없이 종료")
            break

        # 재스크리닝
        print(f"\n[{get_now()}] 종목 스크리닝 중...")
        screened = run_screening()

        # 쿨다운 중인 종목 제외
        now_ts = time.time()
        available = []
        for s in screened:
            last_sold = cooldown_map.get(s["code"])
            if last_sold and (now_ts - last_sold) < sc.SAME_STOCK_COOLDOWN:
                remain = int(sc.SAME_STOCK_COOLDOWN - (now_ts - last_sold))
                print(f"  ⏳ {s['name']} 쿨다운 중 (남은 {remain}초) — 이번엔 제외")
                continue
            available.append(s)

        # 후보가 없으면 잠시 대기 후 다시 스크리닝
        if not available:
            if is_force_sell_time():
                print(f"\n[{get_now()}] 강제 청산 시간 도달 — 종료")
                break
            print(f"[{get_now()}] 조건 충족 종목 없음 — {sc.RESCREEN_WAIT}초 후 재스크리닝")
            time.sleep(sc.RESCREEN_WAIT)
            continue

        # 1순위 종목 매매
        target = available[0]
        trade_count += 1
        result = run_single_stock(target["code"], target["name"], trade_count)

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