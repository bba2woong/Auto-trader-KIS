"""
DART(금융감독원 전자공시) API 기반 공시 점수 산출
최근 3일 공시 제목을 분석해서 긍정/부정 키워드로 점수를 반환한다.

환경변수:
  DART_API_KEY : DART 오픈API 키 (https://opendart.fss.or.kr 에서 발급)
"""
import os
import time
import requests
from datetime import datetime, timedelta

DART_KEY = os.environ.get("DART_API_KEY", "")
BASE_URL = "https://opendart.fss.or.kr/api"

# 긍정 키워드 → +10점 유발
POSITIVE = [
    "수주", "계약", "증설", "배당", "자사주취득", "자사주 취득",
    "흑자전환", "영업이익 증가", "매출 증가", "신제품", "특허",
    "투자유치", "MOU", "협약", "공급계약",
]
# 부정 키워드 → -10점 유발
NEGATIVE = [
    "적자전환", "영업손실", "횡령", "배임", "소송", "주가하락",
    "감자", "파산", "회생절차", "상장폐지", "유상증자",
]


def score_stock(stock_code: str, days: int = 3) -> tuple:
    """
    종목 공시 점수 산출
    반환: (score: int -10~10, reason: str)
    """
    if not DART_KEY:
        return 0, "DART_API_KEY 미설정"

    try:
        corp_code = _get_corp_code(stock_code)
        if not corp_code:
            return 0, "corp_code 조회 실패"

        disclosures = _get_disclosures(corp_code, days)
        return _evaluate(disclosures)

    except Exception as e:
        return 0, f"오류: {e}"


def score_stocks(stock_list: list, days: int = 3) -> dict:
    """
    다종목 공시 점수 일괄 산출
    반환: {code: {"score": int, "reason": str}}
    """
    results = {}
    total   = len(stock_list)

    for i, stock in enumerate(stock_list):
        code = stock["code"]
        print(f"  [DART] 공시 조회 중 ({i+1}/{total}) {stock['name']}...", end="\r")
        score, reason = score_stock(code, days)
        results[code] = {"score": score, "reason": reason}
        time.sleep(0.2)  # API 호출 간격

    print(f"\n  [DART] 공시 분석 완료: {len(results)}개")
    return results


def _get_corp_code(stock_code: str) -> str | None:
    """KIS 종목코드 → DART corp_code 변환"""
    params = {"crtfc_key": DART_KEY, "stock_code": stock_code}
    res = requests.get(f"{BASE_URL}/company.json", params=params, timeout=10)
    data = res.json()
    return data.get("corp_code") if data.get("status") == "000" else None


def _get_disclosures(corp_code: str, days: int) -> list:
    """최근 N일 공시 목록 조회"""
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    params = {
        "crtfc_key":  DART_KEY,
        "corp_code":  corp_code,
        "bgn_de":     bgn_de,
        "end_de":     end_de,
        "sort":       "date",
        "sort_mth":   "desc",
        "page_count": 10,
    }
    res  = requests.get(f"{BASE_URL}/list.json", params=params, timeout=10)
    data = res.json()
    return data.get("list", []) if data.get("status") == "000" else []


def _evaluate(disclosures: list) -> tuple:
    """공시 목록 → (점수, 이유)"""
    if not disclosures:
        return 0, "최근 공시 없음"

    score, reasons = 0, []

    for disc in disclosures:
        title = disc.get("report_nm", "")

        for kw in POSITIVE:
            if kw in title:
                score = 10
                reasons.append(f"✅ {kw}")
                break

        for kw in NEGATIVE:
            if kw in title:
                score = min(score, -10)   # 부정이 더 강하면 덮어씀
                reasons.append(f"⚠️ {kw}")
                break

    reason = ", ".join(reasons) if reasons else "일반 공시"
    return max(-10, min(10, score)), reason
