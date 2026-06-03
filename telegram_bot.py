"""
텔레그램 봇 모듈
스크리닝 결과를 휴대폰으로 전송하고, 버튼 탭으로 종목 선택을 받는다.

환경변수 (Windows 환경변수로 관리):
  TELEGRAM_BOT_TOKEN  : BotFather에서 발급받은 토큰
  TELEGRAM_CHAT_ID    : 메시지 수신할 채팅방 ID (개인 chat_id)

사용법:
  selected = send_and_wait(candidates, timeout=300)
  # 반환값: {"code": "005930", "name": "삼성전자"}
  #       | "PASS"  (패스 버튼)
  #       | None    (타임아웃)
"""
import os
import asyncio
import threading

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

_state = {
    "result": None,
    "event":  threading.Event(),
}


def send_and_wait(candidates, timeout=300):
    """
    스크리닝 결과를 텔레그램으로 전송하고 휴대폰 선택 대기.
    candidates : screener.py 반환값 리스트 (최대 5개 권장)
    timeout    : 응답 대기 초 (기본 5분)
    반환       : {"code", "name"} | "PASS" | None(타임아웃)
    """
    if not BOT_TOKEN or not CHAT_ID:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.\n"
            "sysdm.cpl → 환경 변수에서 두 값을 등록하세요."
        )

    _state["result"] = None
    _state["event"].clear()

    # 별도 스레드 + 별도 이벤트 루프로 봇 실행
    t = threading.Thread(target=_run_bot_thread, args=(candidates,), daemon=True)
    t.start()

    responded = _state["event"].wait(timeout=timeout)

    # 타임아웃이든 선택이든 봇 루프 종료 신호
    _state["event"].set()
    t.join(timeout=5)

    if not responded:
        _notify_timeout()
        return None

    return _state["result"]


def notify(message):
    """매수/매도 결과 등 단방향 알림 전송"""
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        asyncio.run(_send_text(message))
    except Exception:
        pass


# ──────────────────────────────────────────
# 내부 구현
# ──────────────────────────────────────────

def _run_bot_thread(candidates):
    """별도 스레드에서 새 이벤트 루프로 봇 실행"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async_main(candidates))
    finally:
        loop.close()


async def _async_main(candidates):
    from telegram.ext import Application, CallbackQueryHandler

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(_handle_button))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    await _send_screening_message(app.bot, candidates)

    # 선택 이벤트 또는 타임아웃까지 대기
    while not _state["event"].is_set():
        await asyncio.sleep(0.3)

    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _send_screening_message(bot, candidates):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    grade_emoji = {"A": "🥇", "B": "🥈", "C": "🥉"}
    pat_emoji   = {"hammer": " 🔨", "hanging_man": " ⚠️"}

    lines = ["🔍 스크리닝 완료! 매수할 종목을 선택하세요:\n"]
    for i, s in enumerate(candidates):
        g   = s.get("grade", "B")
        pat = pat_emoji.get(s.get("패턴"), "")
        lines.append(f"{grade_emoji.get(g, '')} {i+1}위  {s['name']} ({s['code']}){pat}")
        lines.append(f"    목표가: {s.get('목표가', 0):,}원  /  여유율: {s.get('돌파여유율', 0):+.2f}%\n")

    keyboard = []
    for i, s in enumerate(candidates):
        g      = s.get("grade", "B")
        pat    = pat_emoji.get(s.get("패턴"), "")
        keyboard.append([InlineKeyboardButton(
            f"{grade_emoji.get(g,'')} {i+1}위  {s['name']}{pat}  ({s.get('돌파여유율', 0):+.2f}%)",
            callback_data=f"BUY:{s['code']}:{s['name']}"
        )])
    keyboard.append([InlineKeyboardButton("⏭  오늘 패스", callback_data="PASS")])

    await bot.send_message(
        chat_id=CHAT_ID,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _handle_button(update, context):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "PASS":
        await query.edit_message_text("⏭ 오늘 매매 패스했습니다.")
        _state["result"] = "PASS"
    else:
        _, code, name = data.split(":", 2)
        await query.edit_message_text(f"✅ {name} 선택 완료!\n매수 진행합니다.")
        _state["result"] = {"code": code, "name": name}

    _state["event"].set()


def _notify_timeout():
    try:
        asyncio.run(_send_text("⏰ 5분 내 응답 없음 — 오늘 매매를 건너뜁니다."))
    except Exception:
        pass


async def _send_text(message):
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=message)
