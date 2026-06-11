"""
텔레그램 봇 모듈
스크리닝 결과를 휴대폰으로 전송하고, 버튼 탭으로 종목 선택을 받는다.

환경변수:
  TELEGRAM_BOT_TOKEN  : BotFather에서 발급받은 토큰
  TELEGRAM_CHAT_ID    : 메시지 수신할 채팅방 ID

사용법:
  # 단일 선택
  selected = send_and_wait(candidates, timeout=300)

  # 멀티 선택 (빈 슬롯 수만큼)
  selected_list = send_and_wait_multi(candidates, max_select=3, timeout=300)
  # 반환: [{"code","name"}, ...] | "PASS" | "RESTART" | []

메시지 형식 (멀티 선택):
  🥇 1위  삼성전자 ⭐관심 (005930) 🔨
      목표가: 82,000원  여유율: +0.31%
      📊 돌파:38점 AD:15점 캔들:10점 양봉:15점 LLM:5점 DART:10점 ⭐+10점 → 합계:93점

  - watchlist.py 등록 종목은 종목명 옆 ⭐관심 배지 + 점수줄 ⭐+10점 표시
  - score_detail 없는 경우(AI 스코어링 비활성) watchlist 배지는 직접 조회로 보정

전량매도 문의: MASS_SELL_QUERY_TIMES (기본 13:30 / 14:00 / 14:30)
재시작 충돌 방지: 봇 시작 전 deleteWebhook 호출로 이전 폴링 세션 초기화
Conflict 방지: _bot_running Event로 중복 호출 차단, Conflict 감지 시 최대 2회 재시도
"""
import os
import asyncio
import threading
import time
import requests as _req

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# 중복 실행 방지 — 동일 프로세스 내 재진입 차단
_bot_running = threading.Event()

# 마지막 정상 polling 시각 (워치독용)
_last_poll_success = time.time()


def _notify_alarm_safe(message: str):
    """
    봇 오류 상황에서도 알람봇으로 단방향 알림 전송.
    선택봇과 알람봇은 별도 토큰이므로 선택봇 오류와 무관하게 동작.
    """
    try:
        from telegram_alarm import notify_alarm
        notify_alarm(message)
    except Exception:
        pass


def _reset_polling():
    """
    이전 polling 세션 강제 종료 — Conflict 방지
    새 Application.start_polling() 전에 호출
    """
    if not BOT_TOKEN:
        return
    try:
        _req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=5,
        )
    except Exception:
        pass

# ──────────────────────────────────────────
# 단일 선택 상태
# ──────────────────────────────────────────
_state = {
    "result":     None,
    "event":      threading.Event(),
    "msg_id":     None,
    "candidates": [],
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
    if _bot_running.is_set():
        print("[TelegramBot] 이미 실행 중 — 중복 호출 차단")
        return None
    _check_env()
    _state["result"]     = None
    _state["msg_id"]     = None
    _state["candidates"] = list(candidates)
    _state["event"].clear()

    _bot_running.set()
    t = threading.Thread(target=_run_single_bot, args=(candidates,), daemon=True)
    t.start()

    # 30초 단위로 봇 스레드 생존 확인
    elapsed = 0
    while elapsed < timeout:
        chunk = min(30, timeout - elapsed)
        if _state["event"].wait(timeout=chunk):
            break
        elapsed += chunk
        if not t.is_alive():
            print("[TelegramBot] 봇 스레드 비정상 종료 감지")
            _notify_alarm_safe("⚠️ 텔레그램 봇 오류 감지 — 워치독이 처리합니다.")
            _bot_running.clear()
            return None

    responded = _state["event"].is_set()
    _state["event"].set()
    t.join(timeout=5)
    _bot_running.clear()

    if not responded:
        _notify_timeout(mode="single")
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
    - "재시작" 버튼 탭 → "RESTART" 반환
    반환: [{"code","name"}, ...] | "PASS" | "RESTART" | []
    """
    if max_select <= 0:
        return []
    if _bot_running.is_set():
        print("[TelegramBot] 이미 실행 중 — 중복 호출 차단")
        return []
    _check_env()

    _multi_state["selections"]        = []
    _multi_state["max_select"]        = max_select
    _multi_state["candidates"]        = list(candidates)
    _multi_state["msg_id"]            = None
    _multi_state["restart_requested"] = False
    _multi_state["event"].clear()

    _bot_running.set()
    t = threading.Thread(target=_run_multi_bot, args=(candidates, max_select), daemon=True)
    t.start()

    # 30초 단위로 봇 스레드 생존 확인
    elapsed = 0
    while elapsed < timeout:
        chunk = min(30, timeout - elapsed)
        if _multi_state["event"].wait(timeout=chunk):
            break
        elapsed += chunk
        if not t.is_alive():
            print("[TelegramBot] 봇 스레드 비정상 종료 감지")
            _notify_alarm_safe("⚠️ 텔레그램 봇 오류 감지 — 워치독이 처리합니다.")
            _bot_running.clear()
            return []

    responded = _multi_state["event"].is_set()
    _multi_state["event"].set()
    t.join(timeout=5)
    _bot_running.clear()

    if not responded:
        _notify_timeout(mode="multi")
        return []

    if _multi_state.get("restart_requested"):
        return "RESTART"

    result = _multi_state["selections"]
    return "PASS" if result == "PASS" else result


# ──────────────────────────────────────────
# 비정상 종료 복구 — 모드 선택 요청
# ──────────────────────────────────────────

def send_recovery_query(last_mode: str, timeout: int = 180) -> str:
    """
    비정상 종료 감지 후 재시작 모드를 텔레그램으로 문의.
    반환: "mock" | "real" | None (무응답 또는 skip)
    send_and_wait 패턴과 동일하게 Application polling을 사용.
    """
    if not BOT_TOKEN or not CHAT_ID:
        return None
    if _bot_running.is_set():
        print("[TelegramBot] 이미 실행 중 — recovery query 중복 호출 차단")
        return None

    _state["result"] = None
    _state["event"].clear()

    _bot_running.set()
    t = threading.Thread(target=_run_recovery_bot, args=(last_mode, timeout), daemon=True)
    t.start()

    elapsed = 0
    while elapsed < timeout:
        chunk = min(30, timeout - elapsed)
        if _state["event"].wait(timeout=chunk):
            break
        elapsed += chunk
        if not t.is_alive():
            print("[TelegramBot] recovery 봇 스레드 비정상 종료")
            _bot_running.clear()
            return None

    _state["event"].set()
    t.join(timeout=5)
    _bot_running.clear()
    return _state["result"]


def _run_recovery_bot(last_mode: str, timeout: int):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    MAX_RETRY = 2
    for attempt in range(MAX_RETRY):
        try:
            loop.run_until_complete(_recovery_main(last_mode, timeout))
            break
        except Exception as e:
            if "Conflict" in str(e) and attempt < MAX_RETRY - 1:
                time.sleep(10)
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            else:
                _state["event"].set()
                break
    loop.close()


async def _recovery_main(last_mode: str, timeout: int):
    from telegram.ext import Application, CallbackQueryHandler
    _reset_polling()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(10)
        .build()
    )
    app.add_handler(CallbackQueryHandler(_single_button_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await _send_recovery_message(last_mode, timeout, bot=app.bot)
    while not _state["event"].is_set():
        await asyncio.sleep(0.3)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _send_recovery_message(last_mode: str, timeout: int, bot=None):
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    last_label = "🟡 모의투자" if last_mode == "mock" else "🔴 실전투자"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟡 모의투자로 재시작", callback_data="RECOVER:mock"),
            InlineKeyboardButton("🔴 실전투자로 재시작", callback_data="RECOVER:real"),
        ],
        [
            InlineKeyboardButton("⏸ 재시작 안 함", callback_data="RECOVER:skip"),
        ],
    ])
    async def _do_send(b):
        msg = await b.send_message(
            chat_id=CHAT_ID,
            text=(
                f"🚨 KIS Auto Trader 비정상 종료 감지\n\n"
                f"마지막 실행 모드: {last_label}\n"
                f"재시작할 모드를 선택하세요.\n\n"
                f"⏰ {timeout // 60}분 내 응답 없으면 모의투자로 자동 진입합니다."
            ),
            reply_markup=keyboard,
        )
        _state["msg_id"] = msg.message_id

    if bot is None:
        # 단독 호출 시 Bot context manager 사용
        _bot = Bot(token=BOT_TOKEN)
        async with _bot:
            await _do_send(_bot)
    else:
        # Application.bot 전달 시 context manager 없이 직접 사용
        await _do_send(bot)


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
    MAX_RETRY = 2
    for attempt in range(MAX_RETRY):
        try:
            loop.run_until_complete(_single_main(candidates))
            break
        except Exception as e:
            if "Conflict" in str(e) and attempt < MAX_RETRY - 1:
                print(f"[TelegramBot] Conflict 감지 ({attempt+1}/{MAX_RETRY}) — 10초 대기 후 재시도")
                _notify_alarm_safe(
                    f"⚠️ 텔레그램 봇 충돌 감지\n10초 후 재시도 ({attempt+1}/{MAX_RETRY})"
                )
                time.sleep(10)
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            else:
                if "Conflict" in str(e):
                    print("[TelegramBot] Conflict 재시도 실패 — 이번 라운드 패스")
                    _notify_alarm_safe("🚨 텔레그램 봇 복구 실패 — 이번 라운드 패스")
                    _state["event"].set()
                break
    loop.close()


async def _single_main(candidates):
    from telegram.ext import Application, CallbackQueryHandler
    _reset_polling()   # 이전 polling 세션 강제 종료
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(10)
        .build()
    )
    app.add_handler(CallbackQueryHandler(_single_button_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    msg = await _send_screening_message(app.bot, candidates, multi=False)
    if msg:
        _state["msg_id"] = msg.message_id
    while not _state["event"].is_set():
        await asyncio.sleep(0.3)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _single_button_handler(update, context):
    global _last_poll_success
    _last_poll_success = time.time()
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data.startswith("RECOVER:"):
        mode = data.split(":")[1]
        if mode == "mock":
            await query.edit_message_text("🟡 모의투자로 재시작합니다.")
            _state["result"] = "mock"
        elif mode == "real":
            await query.edit_message_text("🔴 실전투자로 재시작합니다.")
            _state["result"] = "real"
        else:  # skip
            await query.edit_message_text("⏸ 재시작을 취소했습니다.")
            _state["result"] = None
        _state["event"].set()
        return

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
    MAX_RETRY = 2
    for attempt in range(MAX_RETRY):
        try:
            loop.run_until_complete(_multi_main(candidates, max_select))
            break
        except Exception as e:
            if "Conflict" in str(e) and attempt < MAX_RETRY - 1:
                print(f"[TelegramBot] Conflict 감지 ({attempt+1}/{MAX_RETRY}) — 10초 대기 후 재시도")
                _notify_alarm_safe(
                    f"⚠️ 텔레그램 봇 충돌 감지\n10초 후 재시도 ({attempt+1}/{MAX_RETRY})"
                )
                time.sleep(10)
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            else:
                if "Conflict" in str(e):
                    print("[TelegramBot] Conflict 재시도 실패 — 이번 라운드 패스")
                    _notify_alarm_safe("🚨 텔레그램 봇 복구 실패 — 이번 라운드 패스")
                    _multi_state["event"].set()
                break
    loop.close()


async def _multi_main(candidates, max_select):
    from telegram.ext import Application, CallbackQueryHandler
    _reset_polling()   # 이전 polling 세션 강제 종료
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(10)
        .build()
    )
    app.add_handler(CallbackQueryHandler(_multi_button_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    msg = await _send_screening_message(app.bot, candidates, multi=True, max_select=max_select)
    if msg:
        _multi_state["msg_id"] = msg.message_id
    while not _multi_state["event"].is_set():
        await asyncio.sleep(0.3)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _multi_button_handler(update, context):
    global _last_poll_success
    _last_poll_success = time.time()
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "RESTART":
        await query.edit_message_text(
            "🔄 재시작 요청이 전송되었습니다.\n잠시 후 새 스크리닝 메시지가 도착합니다."
        )
        _multi_state["restart_requested"] = True
        _multi_state["selections"] = []
        _multi_state["event"].set()
        return

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
        InlineKeyboardButton("🔄 재시작", callback_data="RESTART"),
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
        total_score = s.get("score", 0)
        score_line  = ""
        d           = s.get("score_detail") or {}
        watch_s     = d.get("watchlist", 0)
        # 관심종목 여부를 score_detail 없는 경우에도 watchlist 직접 조회로 보정
        if not watch_s:
            try:
                from watchlist import WATCHLIST_CODES as _WL
                watch_s = 10 if s.get("code") in _WL else 0
            except Exception:
                pass
        watch_badge = " ⭐관심" if watch_s else ""   # 종목명 줄에 표시할 배지
        if total_score:
            tech = d.get("tech", 0)
            llm  = d.get("llm",  0)
            dart = d.get("dart", 0)
            # tech 세부 분해: 돌파/AD/캔들/양봉
            import strategy_config as _sc
            gap        = s.get("돌파여유율", 0)
            brk_score  = int(40 * max(0.0, 1.0 - gap / max(_sc.MAX_BREAKOUT_GAP, 0.01))) if s.get("변동성돌파") else 0
            ad_score   = 15 if s.get("AD상승") else 0
            candle_s   = 10 if s.get("패턴") == "hammer" else 0
            bull_s     = 15 if s.get("시간봉패턴") == "strong_bull" else 0
            watch_str  = f" ⭐+{watch_s}점" if watch_s else ""
            score_line = (
                f"    📊 돌파:{brk_score}점 AD:{ad_score}점 캔들:{candle_s}점 "
                f"양봉:{bull_s}점 LLM:{llm}점 DART:{dart}점{watch_str} → 합계:{total_score}점"
            )
        lines.append(f"{grade_emoji.get(g,'')} {i+1}위  {s['name']}{watch_badge} ({s['code']}){pat}")
        lines.append(f"    목표가: {s.get('목표가',0):,}원  여유율: {s.get('돌파여유율',0):+.2f}%")
        if score_line:
            lines.append(score_line)
        lines.append("")

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

    msg = await bot.send_message(
        chat_id=CHAT_ID,
        text="\n".join(lines),
        reply_markup=keyboard,
    )
    return msg


def _notify_timeout(mode: str = "multi"):
    """타임아웃 시 버튼 제거 후 텍스트 교체."""
    timeout_text = "⏰ 응답 시간 초과 — 이번 라운드를 건너뜁니다."

    state  = _state if mode == "single" else _multi_state
    msg_id = state.get("msg_id")

    async def _edit_and_notify():
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        async with bot:
            if msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=CHAT_ID,
                        message_id=msg_id,
                        text=timeout_text,
                        reply_markup=None,
                    )
                    return
                except Exception:
                    pass
            # 버튼 제거 실패 시 새 메시지로 폴백
            await bot.send_message(chat_id=CHAT_ID, text=timeout_text)

    try:
        asyncio.run(_edit_and_notify())
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
    _reset_polling()   # 이전 polling 세션 강제 종료
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(10)
        .build()
    )
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


# ──────────────────────────────────────────
# 텔레그램 수동 매수 모니터
# 6자리 종목코드 텍스트 메시지 수신 → 즉시 매수
# send_and_wait()와 충돌 없이 raw HTTP polling 사용
# ──────────────────────────────────────────

_manual_buy_counter = 0   # 수동 슬롯 번호용


def start_manual_buy_monitor(pm, budget_per_slot, stop_event=None):
    """
    백그라운드 스레드로 텔레그램 메시지 폴링.
    6자리 숫자 코드 수신 시 해당 종목 즉시 매수.
    stop_event: scheduler의 정지 이벤트
    """
    if not BOT_TOKEN or not CHAT_ID:
        return

    def _loop():
        import re, requests, time as _time
        global _manual_buy_counter
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        offset  = 0

        print("[텔레그램] 수동매수 모니터 시작 — 6자리 종목코드를 메시지로 보내면 즉시 매수")

        while True:
            if stop_event and stop_event.is_set():
                break

            # Application 폴링 세션(스크리닝 확인, 복구 등) 실행 중엔
            # getUpdates 중단 — 두 폴링이 충돌하면 버튼 클릭이 유실됨
            if _bot_running.is_set():
                _time.sleep(1)
                continue

            try:
                res = requests.get(
                    f"{api_url}/getUpdates",
                    params={
                        "offset":           offset,
                        "timeout":          5,
                        "allowed_updates":  ["message"],
                    },
                    timeout=8,
                )
                if res.status_code != 200:
                    _time.sleep(2)
                    continue

                for u in res.json().get("result", []):
                    offset   = u["update_id"] + 1
                    msg      = u.get("message", {})
                    text     = msg.get("text", "").strip()
                    chat_id  = str(msg.get("chat", {}).get("id", ""))

                    # 본인 채팅방 메시지만 처리
                    if chat_id != str(CHAT_ID):
                        continue

                    # 6자리 숫자 = 종목코드
                    if re.match(r'^\d{6}$', text):
                        _handle_manual_buy(text, pm, budget_per_slot)

            except Exception:
                pass
            _time.sleep(2)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


def _handle_manual_buy(stock_code: str, pm, budget_per_slot: float):
    """텔레그램으로 요청받은 종목 즉시 매수"""
    import time as _time
    global _manual_buy_counter

    # 종목명 찾기
    try:
        from screener import KOSPI_200
        name_map = {s["code"]: s["name"] for s in KOSPI_200}
    except Exception:
        name_map = {}

    try:
        from watchlist import WATCHLIST_CODES
    except Exception:
        pass

    name = name_map.get(stock_code, stock_code)

    # 슬롯 확인
    if pm.free_slots <= 0:
        notify(f"⚠️ 수동매수 불가: {name}({stock_code})\n빈 슬롯 없음 (포지션 풀 가득)")
        return

    if pm.in_cooldown(stock_code):
        notify(f"⚠️ 수동매수 불가: {name}({stock_code})\n쿨다운 중")
        return

    if stock_code in pm.active:
        notify(f"⚠️ 수동매수 불가: {name}({stock_code})\n이미 보유 중")
        return

    _manual_buy_counter += 1
    slot_no = 800 + _manual_buy_counter   # 수동 슬롯은 800번대로 구분

    notify(
        f"📱 수동매수 요청 접수\n"
        f"종목: {name} ({stock_code})\n"
        f"예산: {budget_per_slot:,.0f}원\n"
        f"슬롯: #{slot_no} | 트레일링 스탑 적용"
    )

    pm.open(
        {"code": stock_code, "name": f"[수동]{name}"},
        slot_no,
        jitter=False,
    )
