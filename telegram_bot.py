"""
텔레그램 봇 모듈
스크리닝 결과를 휴대폰으로 전송하고, 버튼 탭으로 종목 선택을 받는다.

환경변수:
  TELEGRAM_BOT_TOKEN  : BotFather에서 발급받은 토큰
  TELEGRAM_CHAT_ID    : 메시지 수신할 채팅방 ID

사용법:
  # 단일 선택 (기존)
  selected = send_and_wait(candidates, timeout=300)

  # 멀티 선택 (빈 슬롯 수만큼)
  selected_list = send_and_wait_multi(candidates, max_select=3, timeout=300)
  # 반환: [{"code","name"}, ...] | "PASS" | []
"""
import os
import asyncio
import threading

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# ──────────────────────────────────────────
# 단일 선택 상태
# ──────────────────────────────────────────
_state = {
    "result": None,
    "event":  threading.Event(),
}

# ──────────────────────────────────────────
# 멀티 선택 상태
# ──────────────────────────────────────────
_multi_state = {
    "selections": [],   # 선택된 종목 list
    "max_select": 1,
    "candidates": [],
    "event":      threading.Event(),
    "msg_id":     None, # 메시지 ID (키보드 업데이트용)
}


def _check_env():
    if not BOT_TOKEN or not CHAT_ID:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다."
        )


# ──────────────────────────────────────────
# 퍼블릭: 단일 선택
# ──────────────────────────────────────────

def send_and_wait(candidates, timeout=300):
    """
    단일 종목 선택 (기존 방식 유지)
    반환: {"code","name"} | "PASS" | None
    """
    _check_env()
    _state["result"]     = None
    _state["candidates"] = list(candidates)
    _state["event"].clear()

    t = threading.Thread(target=_run_single_bot, args=(candidates,), daemon=True)
    t.start()
    responded = _state["event"].wait(timeout=timeout)
    _state["event"].set()
    t.join(timeout=5)

    if not responded:
        _notify_timeout()
        return None
    return _state["result"]


# ──────────────────────────────────────────
# 퍼블릭: 멀티 선택
# ──────────────────────────────────────────

def send_and_wait_multi(candidates, max_select=1, timeout=300):
    """
    최대 max_select개 종목 동시 선택
    - 종목 버튼 탭 → ✅ 표시, 선택 목록에 추가
    - max_select 개 모두 선택되면 자동 완료
    - "선택 완료" 버튼 탭 → 현재 선택 확정
    - "패스" 버튼 탭 → "PASS" 반환
    반환: [{"code","name"}, ...] | "PASS" | []
    """
    if max_select <= 0:
        return []
    _check_env()

    _multi_state["selections"] = []
    _multi_state["max_select"] = max_select
    _multi_state["candidates"] = list(candidates)
    _multi_state["msg_id"]     = None
    _multi_state["event"].clear()

    t = threading.Thread(target=_run_multi_bot, args=(candidates, max_select), daemon=True)
    t.start()
    responded = _multi_state["event"].wait(timeout=timeout)
    _multi_state["event"].set()
    t.join(timeout=5)

    if not responded:
        _notify_timeout()
        return []

    result = _multi_state["selections"]
    return "PASS" if result == "PASS" else result


# ──────────────────────────────────────────
# 단방향 알림
# ──────────────────────────────────────────

def notify(message):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        asyncio.run(_send_text(message))
    except Exception:
        pass


# ──────────────────────────────────────────
# 단일 선택 봇
# ──────────────────────────────────────────

def _run_single_bot(candidates):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_single_main(candidates))
    finally:
        loop.close()


async def _single_main(candidates):
    from telegram.ext import Application, CallbackQueryHandler
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(_single_button_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await _send_screening_message(app.bot, candidates, multi=False)
    while not _state["event"].is_set():
        await asyncio.sleep(0.3)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _single_button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "PASS":
        await query.edit_message_text("⏭ 오늘 매매 패스했습니다.")
        _state["result"] = "PASS"
    elif data.startswith("BUY:"):
        _, code, name = data.split(":", 2)
        # 미선택 종목 목록도 표시
        cands     = _state.get("candidates", [])
        skipped   = [c["name"] for c in cands if c["code"] != code]
        skip_text = ""
        if skipped:
            skip_text = f"\n\n선택 포기 {len(skipped)}개:\n" + "\n".join(f"  - {n}" for n in skipped)
        await query.edit_message_text(f"✅ {name} 선택 완료!\n매수 진행합니다.{skip_text}")
        _state["result"] = {"code": code, "name": name}

    _state["event"].set()


# ──────────────────────────────────────────
# 멀티 선택 봇
# ──────────────────────────────────────────

def _run_multi_bot(candidates, max_select):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_multi_main(candidates, max_select))
    finally:
        loop.close()


async def _multi_main(candidates, max_select):
    from telegram.ext import Application, CallbackQueryHandler
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(_multi_button_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await _send_screening_message(app.bot, candidates, multi=True, max_select=max_select)
    while not _multi_state["event"].is_set():
        await asyncio.sleep(0.3)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _multi_button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "PASS":
        await query.edit_message_text("⏭ 오늘 매매 패스했습니다.")
        _multi_state["selections"] = "PASS"
        _multi_state["event"].set()
        return

    if data == "CONFIRM":
        sels = _multi_state["selections"]
        if not sels:
            await query.answer("선택된 종목이 없습니다.", show_alert=True)
            return
        sel_names  = ", ".join(s["name"] for s in sels)
        sel_codes  = {s["code"] for s in sels}
        cands      = _multi_state["candidates"]
        skipped    = [c["name"] for c in cands if c["code"] not in sel_codes]
        skip_text  = ""
        if skipped:
            skip_text = f"\n\n선택 포기 {len(skipped)}개:\n" + "\n".join(f"  - {n}" for n in skipped)
        await query.edit_message_text(
            f"✅ 선택 완료!\n{sel_names}\n총 {len(sels)}개 매수 진행합니다.{skip_text}"
        )
        _multi_state["event"].set()
        return

    if data.startswith("TOGGLE:"):
        _, code, name = data.split(":", 2)
        sels     = _multi_state["selections"]
        max_sel  = _multi_state["max_select"]
        cands    = _multi_state["candidates"]

        # 이미 선택됐으면 제거 (토글)
        already = next((s for s in sels if s["code"] == code), None)
        if already:
            sels.remove(already)
        elif len(sels) < max_sel:
            sels.append({"code": code, "name": name})
        else:
            await query.answer(f"최대 {max_sel}개까지 선택 가능합니다.", show_alert=True)
            return

        # 키보드 업데이트
        await query.edit_message_reply_markup(
            reply_markup=_build_multi_keyboard(cands, sels, max_sel)
        )

        # max_select 채워지면 자동 완료
        if len(sels) >= max_sel:
            names = ", ".join(s["name"] for s in sels)
            await query.edit_message_text(f"✅ {max_sel}개 선택 완료!\n{names}\n매수 진행합니다.")
            _multi_state["event"].set()


def _build_multi_keyboard(candidates, selections, max_select):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    grade_emoji = {"A": "🥇", "B": "🥈", "C": "🥉"}
    pat_emoji   = {"hammer": " 🔨", "hanging_man": " ⚠️"}
    sel_codes   = {s["code"] for s in selections}

    keyboard = []
    for s in candidates:
        g     = s.get("grade", "B")
        pat   = pat_emoji.get(s.get("패턴"), "")
        check = "✅ " if s["code"] in sel_codes else "⬜ "
        label = f"{check}{grade_emoji.get(g,'')} {s['name']}{pat}  ({s.get('돌파여유율',0):+.2f}%)"
        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"TOGGLE:{s['code']}:{s['name']}"
        )])

    n = len(selections)
    keyboard.append([
        InlineKeyboardButton(f"✅ 선택 완료 ({n}/{max_select})", callback_data="CONFIRM"),
        InlineKeyboardButton("⏭ 패스", callback_data="PASS"),
    ])
    return InlineKeyboardMarkup(keyboard)


# ──────────────────────────────────────────
# 공통 메시지 전송
# ──────────────────────────────────────────

async def _send_screening_message(bot, candidates, multi=False, max_select=1):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    grade_emoji = {"A": "🥇", "B": "🥈", "C": "🥉"}
    pat_emoji   = {"hammer": " 🔨", "hanging_man": " ⚠️"}

    if multi:
        header = f"🔍 스크리닝 완료! 최대 {max_select}개 선택 가능 (⬜ 탭 → ✅)\n"
    else:
        header = "🔍 스크리닝 완료! 매수할 종목을 선택하세요:\n"

    lines = [header]
    for i, s in enumerate(candidates):
        g   = s.get("grade", "B")
        pat = pat_emoji.get(s.get("패턴"), "")
        ai  = f"  AI {s.get('score', 0)}점" if s.get("score") else ""
        lines.append(f"{grade_emoji.get(g,'')} {i+1}위  {s['name']} ({s['code']}){pat}{ai}")
        lines.append(f"    목표가: {s.get('목표가',0):,}원  여유율: {s.get('돌파여유율',0):+.2f}%\n")

    if multi:
        keyboard = _build_multi_keyboard(candidates, [], max_select)
    else:
        rows = []
        for s in candidates:
            g   = s.get("grade", "B")
            pat = pat_emoji.get(s.get("패턴"), "")
            rows.append([InlineKeyboardButton(
                f"{grade_emoji.get(g,'')} {s['name']}{pat}  ({s.get('돌파여유율',0):+.2f}%)",
                callback_data=f"BUY:{s['code']}:{s['name']}"
            )])
        rows.append([InlineKeyboardButton("⏭  오늘 패스", callback_data="PASS")])
        keyboard = InlineKeyboardMarkup(rows)

    await bot.send_message(
        chat_id=CHAT_ID,
        text="\n".join(lines),
        reply_markup=keyboard,
    )


def _notify_timeout():
    try:
        asyncio.run(_send_text("⏰ 응답 없음 — 이번 라운드를 건너뜁니다."))
    except Exception:
        pass


# ──────────────────────────────────────────
# 개별 종목 선택 매도 문의 (14:00 / 14:30)
# ──────────────────────────────────────────
# 반환: list[code] (매도할 종목 코드 목록) | [] (유지 또는 타임아웃)

_partial_sell_state = {
    "selections": [],   # 선택된 code 리스트
    "positions":  [],   # 전달받은 positions
    "event":      threading.Event(),
}


def send_partial_sell_query(positions, timeout=300):
    """
    개별 종목 선택 매도 문의 (14:00 / 14:30)
    positions : [{"code","name","buy_price","current_price","quantity"}, ...]
    반환      : list[code] — 매도할 종목 코드 목록
                [] — 전체 유지 또는 타임아웃 (자동 유지)
    """
    _check_env()
    _partial_sell_state["selections"] = []
    _partial_sell_state["positions"]  = list(positions)
    _partial_sell_state["event"].clear()

    t = threading.Thread(target=_run_partial_sell_bot, args=(positions,), daemon=True)
    t.start()
    responded = _partial_sell_state["event"].wait(timeout=timeout)
    _partial_sell_state["event"].set()
    t.join(timeout=5)

    if not responded:
        try:
            asyncio.run(_send_text("⏰ 응답 없음 — 전체 유지합니다."))
        except Exception:
            pass
        return []

    return _partial_sell_state["selections"]


def _run_partial_sell_bot(positions):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_partial_sell_main(positions))
    finally:
        loop.close()


async def _partial_sell_main(positions):
    from telegram.ext import Application, CallbackQueryHandler
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(_partial_sell_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=_build_partial_sell_header(positions),
        reply_markup=_build_partial_sell_keyboard(positions, []),
    )
    while not _partial_sell_state["event"].is_set():
        await asyncio.sleep(0.3)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


def _build_partial_sell_header(positions):
    lines = ["📤 매도 종목 선택 (⬜ 탭 → ✅, 중복 선택 가능)\n"]
    total_pnl = 0
    for p in positions:
        rate = (p["current_price"] - p["buy_price"]) / p["buy_price"] * 100
        pnl  = (p["current_price"] - p["buy_price"]) * p["quantity"]
        total_pnl += pnl
        em = "📈" if pnl >= 0 else "📉"
        lines.append(f"{em} {p['name']}  ({rate:+.2f}%)  {pnl:+,}원")
    lines.append(f"\n합계: {total_pnl:+,}원")
    return "\n".join(lines)


def _build_partial_sell_keyboard(positions, selected_codes):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = []
    for p in positions:
        code  = p["code"]
        rate  = (p["current_price"] - p["buy_price"]) / p["buy_price"] * 100
        check = "✅" if code in selected_codes else "⬜"
        label = f"{check} {p['name']}  ({rate:+.2f}%)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"SELL_TOGGLE:{code}")])

    n = len(selected_codes)
    keyboard.append([
        InlineKeyboardButton(f"📤 선택 매도 ({n}개)", callback_data="SELL_CONFIRM"),
        InlineKeyboardButton("🔒 전체 유지",          callback_data="SELL_HOLD_ALL"),
    ])
    return InlineKeyboardMarkup(keyboard)


async def _partial_sell_handler(update, context):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "SELL_HOLD_ALL":
        await query.edit_message_text("🔒 전체 유지합니다.")
        _partial_sell_state["selections"] = []
        _partial_sell_state["event"].set()
        return

    if data == "SELL_CONFIRM":
        sels = _partial_sell_state["selections"]
        if not sels:
            await query.answer("선택된 종목이 없습니다.", show_alert=True)
            return
        positions = _partial_sell_state["positions"]
        names = ", ".join(
            p["name"] for p in positions if p["code"] in sels
        )
        await query.edit_message_text(f"📤 매도 진행: {names}")
        _partial_sell_state["event"].set()
        return

    if data.startswith("SELL_TOGGLE:"):
        code      = data.split(":", 1)[1]
        sels      = _partial_sell_state["selections"]
        positions = _partial_sell_state["positions"]
        if code in sels:
            sels.remove(code)
        else:
            sels.append(code)
        # 키보드 업데이트
        await query.edit_message_reply_markup(
            reply_markup=_build_partial_sell_keyboard(positions, sels)
        )


async def _send_text(message):
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=message)
