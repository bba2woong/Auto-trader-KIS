"""
텔레그램 연동 테스트
실행: python test_telegram.py
"""
import asyncio
import os
import sys

def check_env():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("❌ 환경변수 미설정")
        print(f"   TELEGRAM_BOT_TOKEN : {'✅ 설정됨' if token else '❌ 없음'}")
        print(f"   TELEGRAM_CHAT_ID   : {'✅ 설정됨' if chat_id else '❌ 없음'}")
        print("\n  sysdm.cpl → 환경변수에서 등록 후 터미널 재시작하세요.")
        sys.exit(1)
    print(f"✅ 환경변수 확인 완료")
    print(f"   TOKEN  : {token[:10]}...")
    print(f"   CHAT_ID: {chat_id}")


def test_simple_message():
    """테스트 1: 단순 텍스트 메시지 전송"""
    print("\n[테스트 1] 텍스트 메시지 전송...")
    from telegram_bot import notify
    notify("✅ KIS Trader 텔레그램 연동 테스트 성공!")
    print("  → 휴대폰 확인해보세요")


def test_screening_message():
    """테스트 2: 스크리닝 결과 버튼 메시지 전송 + 선택 대기"""
    print("\n[테스트 2] 스크리닝 결과 버튼 전송 + 선택 대기 (60초 타임아웃)...")

    # 더미 스크리닝 결과
    dummy_candidates = [
        {"code": "005930", "name": "삼성전자",  "목표가": 70000, "돌파여유율": 0.3},
        {"code": "000660", "name": "SK하이닉스", "목표가": 185000, "돌파여유율": 0.7},
        {"code": "035420", "name": "NAVER",      "목표가": 210000, "돌파여유율": 1.1},
    ]

    from telegram_bot import send_and_wait
    print("  → 휴대폰에서 버튼을 탭하세요 (60초 이내)")
    selected = send_and_wait(dummy_candidates, timeout=60)

    if selected is None:
        print("  ⏰ 타임아웃 — 응답 없음")
    elif selected == "PASS":
        print("  ⏭ 패스 선택 확인")
    else:
        print(f"  ✅ 종목 선택 확인: {selected['name']} ({selected['code']})")


if __name__ == "__main__":
    check_env()

    print("\n실행할 테스트를 선택하세요:")
    print("  [1] 텍스트 메시지만 전송")
    print("  [2] 스크리닝 버튼 전송 + 선택 대기")
    print("  [3] 둘 다")
    choice = input("\n선택 >> ").strip()

    if choice in ("1", "3"):
        test_simple_message()
    if choice in ("2", "3"):
        test_screening_message()

    print("\n테스트 완료")
