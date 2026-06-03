"""
AI 점수 시스템 전체 디버그 테스트
실행: python test_scoring.py
"""
import sys, os, json
os.environ.setdefault("TRADING_MODE", "mock")
sys.path.insert(0, ".")

TEST_STOCKS = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "035420", "name": "NAVER"},
]

SEP = "=" * 50

def check_env():
    print(SEP)
    print("  [0] 환경변수 확인")
    print(SEP)
    perp = os.environ.get("PERPLEXITY_API_KEY", "")
    dart = os.environ.get("DART_API_KEY", "")
    print(f"  PERPLEXITY_API_KEY : {'✅ ' + perp[:8] + '...' if perp else '❌ 없음'}")
    print(f"  DART_API_KEY       : {'✅ ' + dart[:8] + '...' if dart else '❌ 없음'}")
    import strategy_config as sc
    print(f"  USE_AI_SCORING     : {sc.USE_AI_SCORING}")
    print(f"  USE_DART_SCORING   : {sc.USE_DART_SCORING}")
    print(f"  AUTO_BUY_SCORE     : {sc.AUTO_BUY_SCORE}")
    print(f"  CONFIRM_SCORE_MIN  : {sc.CONFIRM_SCORE_MIN}")
    return bool(perp), bool(dart)


def test_llm_only():
    """LLM 단독 호출 — 캐시 미사용"""
    print(f"\n{SEP}")
    print("  [1] LLM 단독 호출 (캐시 미사용)")
    print(SEP)
    from scoring.llm_client import analyze_stocks
    results = analyze_stocks(TEST_STOCKS)
    print("\n  ── 원본 응답 ──")
    for code, data in results.items():
        name = next((s["name"] for s in TEST_STOCKS if s["code"] == code), code)
        print(f"  {name} ({code})")
        print(f"    opinion : {data['opinion']}")
        print(f"    score   : {data['score']}점")
        print(f"    reason  : {data['reason']}")
    return results


def test_dart_only():
    """DART 단독 호출"""
    print(f"\n{SEP}")
    print("  [2] DART 공시 분석 (단독)")
    print(SEP)
    import strategy_config as sc
    if not sc.USE_DART_SCORING:
        print("  USE_DART_SCORING=False — 건너뜀")
        return
    from scoring.dart_client import score_stocks
    results = score_stocks(TEST_STOCKS)
    for code, data in results.items():
        name = next((s["name"] for s in TEST_STOCKS if s["code"] == code), code)
        print(f"  {name} ({code}): {data['score']:+d}점  {data['reason']}")


def test_cache_refresh():
    """캐시 갱신 → 저장 내용 검증"""
    print(f"\n{SEP}")
    print("  [3] 캐시 갱신 + 저장 내용 검증")
    print(SEP)
    from scoring.scorer import refresh_cache, _cache_path
    refresh_cache(TEST_STOCKS, "디버그테스트")

    # 저장된 캐시 파일 직접 읽기
    path = _cache_path()
    cache = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n  ── 캐시 파일: {path.name} ──")
    print(f"  갱신 시각: {cache.get('last_run')}")
    for code in [s["code"] for s in TEST_STOCKS]:
        name = next((s["name"] for s in TEST_STOCKS if s["code"] == code), code)
        d = cache.get("stocks", {}).get(code, {})
        print(f"\n  {name} ({code})")
        print(f"    llm_score   : {d.get('llm_score')}점")
        print(f"    llm_opinion : {d.get('llm_opinion')}")
        print(f"    llm_reason  : {d.get('llm_reason')}")
        print(f"    dart_score  : {d.get('dart_score')}점")
        print(f"    dart_reason : {d.get('dart_reason')}")
        print(f"    updated_at  : {d.get('updated_at')}")
    return cache


def test_total_score():
    """총점 계산 체인 전체 추적"""
    print(f"\n{SEP}")
    print("  [4] 총점 계산 체인 추적")
    print(SEP)
    from scoring.scorer import technical_score, total_score, routing
    import strategy_config as sc

    # 더미 스크리닝 결과 (다양한 케이스)
    cases = [
        {"label": "최고점 케이스 (돌파+AD+해머)",
         "data": {"code":"005930","name":"삼성전자","변동성돌파":True,"AD상승":True,"돌파여유율":0.1,"패턴":"hammer"}},
        {"label": "중간 케이스 (돌파+AD, 패턴없음)",
         "data": {"code":"000660","name":"SK하이닉스","변동성돌파":True,"AD상승":True,"돌파여유율":0.8,"패턴":None}},
        {"label": "최저 케이스 (돌파실패+행잉맨)",
         "data": {"code":"035420","name":"NAVER","변동성돌파":False,"AD상승":False,"돌파여유율":0.0,"패턴":"hanging_man"}},
    ]

    for case in cases:
        d    = case["data"]
        code = d["code"]
        name = d["name"]

        tech = technical_score(d)
        full = total_score(d)
        route = routing(full["total"])

        print(f"\n  ── {case['label']} ──")
        print(f"  종목: {name} ({code})")
        print(f"  기술적 점수 계산:")
        print(f"    변동성돌파={d['변동성돌파']}  여유율={d['돌파여유율']}%  → {30 if d['변동성돌파'] else 0}→보정후 {tech - (30 if d['AD상승'] else 0) - (10 if d['패턴']=='hammer' else -10 if d['패턴']=='hanging_man' else 0)}pt")
        print(f"    AD상승={d['AD상승']}  → {30 if d['AD상승'] else 0}pt")
        print(f"    패턴={d['패턴']}  → {10 if d['패턴']=='hammer' else -10 if d['패턴']=='hanging_man' else 0}pt")
        print(f"    기술적 합계: {tech}pt")
        print(f"  캐시 LLM  : {full['llm']}pt ({full['llm_opinion']})")
        print(f"  캐시 DART : {full['dart']}pt")
        print(f"  ▶ 총점    : {full['total']}pt  → 라우팅: {route}")
        print(f"    (기준: auto_buy≥{sc.AUTO_BUY_SCORE} / confirm≥{sc.CONFIRM_SCORE_MIN})")


if __name__ == "__main__":
    has_perp, has_dart = check_env()

    print(f"\n{SEP}")
    print("  실행할 테스트:")
    print("  [1] LLM 단독")
    print("  [2] DART 단독")
    print("  [3] 캐시 갱신 + 저장 내용 검증")
    print("  [4] 총점 계산 체인 추적")
    print("  [all] 전체")
    choice = input(f"\n  선택 >> ").strip().lower()

    if choice in ("1", "all") and has_perp:
        test_llm_only()
    if choice in ("2", "all"):
        test_dart_only()
    if choice in ("3", "all"):
        test_cache_refresh()
    if choice in ("4", "all"):
        # [4]는 [3] 이후에 실행해야 캐시가 있음
        if choice == "4":
            print("  ※ 캐시가 없으면 LLM 점수가 기본값(10)으로 나옵니다. [3] 먼저 실행 권장")
        test_total_score()

    print(f"\n{SEP}")
    print("  테스트 완료")
    print(SEP)
