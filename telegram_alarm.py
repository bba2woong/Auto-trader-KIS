"""
kis_trader_alarmbot — 단방향 알림 전용 봇

환경변수:
  TELEGRAM_ALARM_BOT_TOKEN : 알람봇 토큰 (BotFather에서 별도 발급)
  TELEGRAM_ALARM_CHAT_ID   : 수신 채팅방 ID

담당 알림:
  ⓐ 보유 종목 수익률 정기 알림 (30분 주기)
  ⓑ 매수 체결 완료 알림
  ⓒ 매도 조건 충족 + 체결 완료 알림 (조건 정보 포함)
  ⓓ 종목 이름으로 표시 (코드 아님)
"""
import os
import asyncio

ALARM_TOKEN   = os.environ.get("TELEGRAM_ALARM_BOT_TOKEN")
ALARM_CHAT_ID = os.environ.get("TELEGRAM_ALARM_CHAT_ID")

_REASON_LABEL = {
    "트레일링스탑": "📉 트레일링 스탑 발동",
    "손절":        "🔻 하드 손절",
    "강제청산":    "⏰ 강제 청산 (15시)",
    "오류청산":    "⚠️ API 오류 후 청산",
    "전량매도":    "📤 수동 전량 매도",
    "장종료":      "🔔 장 종료 청산",
}


def _enabled():
    return bool(ALARM_TOKEN and ALARM_CHAT_ID)


def notify_alarm(message: str):
    """알람봇으로 단방향 메시지 전송"""
    if not _enabled():
        return
    try:
        asyncio.run(_send(message))
    except Exception:
        pass


async def _send(message: str):
    from telegram import Bot
    bot = Bot(token=ALARM_TOKEN)
    async with bot:
        await bot.send_message(chat_id=ALARM_CHAT_ID, text=message)


# ──────────────────────────────────────────
# 매수 체결 알림 ⓑ
# ──────────────────────────────────────────

def notify_buy_filled(name: str, buy_price: int, quantity: int):
    """매수 전체 체결 시 알림"""
    amount = buy_price * quantity
    notify_alarm(
        f"💰 매수 체결\n"
        f"종목: {name}\n"
        f"체결가: {buy_price:,}원 × {quantity}주\n"
        f"투자금: {amount:,}원"
    )


# ──────────────────────────────────────────
# 매도 체결 알림 ⓒ ⓓ
# ──────────────────────────────────────────

def notify_sell_filled(name: str, buy_price: int, sell_price: int,
                       quantity: int, reason: str):
    """매도 전체 체결 시 알림 (조건 + 종목명으로 표시)"""
    pnl      = (sell_price - buy_price) * quantity
    pnl_rate = (sell_price - buy_price) / buy_price * 100
    emoji    = "✅" if pnl >= 0 else "🔴"
    label    = _REASON_LABEL.get(reason, f"📌 {reason}")

    notify_alarm(
        f"{emoji} 매도 체결 [{label}]\n"
        f"종목: {name}\n"
        f"매수 {buy_price:,}원 → 매도 {sell_price:,}원\n"
        f"수익: {pnl:+,}원  ({pnl_rate:+.2f}%)"
    )


# ──────────────────────────────────────────
# 보유 종목 수익률 정기 알림 ⓐ
# ──────────────────────────────────────────

def notify_screening_result(round_no: int, candidates: list):
    """스크리닝 결과를 알람봇으로 전송"""
    if not _enabled():
        return
    from datetime import datetime
    now = datetime.now().strftime("%H:%M")

    try:
        from watchlist import WATCHLIST_CODES as _WL
    except Exception:
        _WL = set()

    route_emoji = {
        "auto_buy": "🤖",
        "confirm":  "📱",
        "skip":     "⏭",
    }

    if not candidates:
        notify_alarm(f"🔍 스크리닝 #{round_no}  {now}\n\n조건 충족 종목 없음")
        return

    lines = [f"🔍 스크리닝 #{round_no}  {now}\n"]
    for cand in candidates:
        d        = cand.get("score_detail") or {}
        tech     = d.get("tech",  0)
        llm      = d.get("llm",   0)
        dart     = d.get("dart",  0)
        bull     = d.get("strong_bull", 0) or (15 if cand.get("시간봉패턴") == "strong_bull" else 0)
        wl_score = 5 if cand.get("code") in _WL else 0
        total    = cand.get("score", 0)
        grade    = cand.get("grade", "B")
        gap      = cand.get("돌파여유율", 0)
        route    = cand.get("route", "")
        emoji    = route_emoji.get(route, "🔍")

        lines.append(
            f"{emoji} {cand['name']} ({cand['code']})\n"
            f"   총점: {total}점 (기술:{tech} LLM:{llm} DART:{dart} 강세봉:{bull} WL:{wl_score})\n"
            f"   여유율: {gap:+.2f}%  등급: {grade}"
        )
        lines.append("")

    notify_alarm("\n".join(lines).rstrip())


def notify_position_status(positions: list):
    """
    positions: [{"name","buy_price","current_price","quantity"}, ...]
    """
    if not _enabled():
        return
    from datetime import datetime
    now = datetime.now().strftime("%H:%M")

    if not positions:
        notify_alarm(f"📊 [{now}] 현재 보유 종목 없음")
        return

    lines = [f"📊 보유 현황  {now} ({len(positions)}개)\n"]
    total_pnl = 0
    for p in positions:
        bp   = p["buy_price"]
        cp   = p["current_price"]
        qty  = p["quantity"]
        rate = (cp - bp) / bp * 100
        pnl  = (cp - bp) * qty
        total_pnl += pnl
        em = "📈" if pnl >= 0 else "📉"
        lines.append(
            f"{em} {p['name']}\n"
            f"   {bp:,} → {cp:,}  ({rate:+.2f}%)\n"
            f"   평가손익: {pnl:+,}원"
        )
    lines.append(f"\n총 평가손익: {total_pnl:+,}원")
    notify_alarm("\n".join(lines))
