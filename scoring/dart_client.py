"""
DART(금융감독원 전자공시) API 기반 공시 점수 산출
최근 3일 공시 제목을 분석해서 긍정/부정 키워드로 점수를 반환한다.

종목코드 → DART corp_code 매핑:
  DART API는 stock_code로 직접 조회 불가.
  전체 기업코드 목록(corpCode.xml ZIP)을 다운받아 로컬 캐시로 관리.
  캐시 파일: scoring/cache/corp_codes.json (분기별 수동 갱신 권장)

환경변수:
  DART_API_KEY : DART 오픈API 키 (https://opendart.fss.or.kr 에서 발급)
"""
import os
import io
import json
import time
import zipfile
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

DART_KEY  = os.environ.get("DART_API_KEY", "")
BASE_URL  = "https://opendart.fss.or.kr/api"
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
CORP_CODE_CACHE = CACHE_DIR / "corp_codes.json"

# 긍정 키워드 → +10점
POSITIVE = [
    "수주", "계약", "증설", "배당", "자사주취득", "자사주 취득",
    "흑자전환", "영업이익 증가", "매출 증가", "신제품", "특허",
    "투자유치", "MOU", "협약", "공급계약",
]
# 부정 키워드 → -10점
NEGATIVE = [
    "적자전환", "영업손실", "횡령", "배임", "소송",
    "감자", "파산", "회생절차", "상장폐지", "유상증자",
]

# 메모리 캐시 (프로세스 내 재사용)
_corp_map: dict | None = None


# ──────────────────────────────────────────
# 퍼블릭 함수
# ──────────────────────────────────────────

def score_stock(stock_code: str, days: int = 3) -> tuple:
    """종목 공시 점수 산출. 반환: (score: -10~10, reason: str)"""
    if not DART_KEY:
        return 0, "DART_API_KEY 미설정"
    try:
        corp_code = _get_corp_code(stock_code)
        if not corp_code:
            return 0, "상장 기업 코드 없음"
        disclosures = _get_disclosures(corp_code, days)
        return _evaluate(disclosures)
    except Exception as e:
        return 0, f"오류: {e}"


def score_stocks(stock_list: list, days: int = 3) -> dict:
    """다종목 공시 점수 일괄 산출. 반환: {code: {"score": int, "reason": str}}"""
    _ensure_corp_map()   # 캐시 준비
    results = {}
    total   = len(stock_list)
    for i, stock in enumerate(stock_list):
        code = stock["code"]
        print(f"  [DART] 공시 조회 중 ({i+1}/{total}) {stock['name']}...", end="\r")
        score, reason = score_stock(code, days)
        results[code] = {"score": score, "reason": reason}
        time.sleep(0.2)
    print(f"\n  [DART] 공시 분석 완료: {len(results)}개")
    return results


def download_corp_codes(force: bool = False) -> int:
    """
    DART 전체 기업코드 목록 다운로드 → 로컬 JSON 캐시 저장
    반환: 저장된 상장 기업 수
    """
    global _corp_map
    if CORP_CODE_CACHE.exists() and not force:
        print("  [DART] corp_codes.json 이미 존재 — 다운로드 스킵 (강제 갱신: force=True)")
        _corp_map = json.loads(CORP_CODE_CACHE.read_text(encoding="utf-8"))
        return len(_corp_map)

    print("  [DART] 전체 기업코드 다운로드 중...")
    res = requests.get(f"{BASE_URL}/corpCode.xml",
                       params={"crtfc_key": DART_KEY}, timeout=30)
    res.raise_for_status()

    # ZIP 압축 해제 → XML 파싱
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        xml_data = z.read("CORPCODE.xml")

    root    = ET.fromstring(xml_data)
    corp_map = {}
    for item in root.findall("list"):
        corp_code  = item.findtext("corp_code", "").strip()
        stock_code = item.findtext("stock_code", "").strip()
        if stock_code:   # 상장 기업만 (비상장은 stock_code 공백)
            corp_map[stock_code] = corp_code

    CORP_CODE_CACHE.write_text(
        json.dumps(corp_map, ensure_ascii=False), encoding="utf-8"
    )
    _corp_map = corp_map
    print(f"  [DART] 기업코드 저장 완료: {len(corp_map)}개 상장 기업")
    return len(corp_map)


# ──────────────────────────────────────────
# 내부 함수
# ──────────────────────────────────────────

def _ensure_corp_map():
    global _corp_map
    if _corp_map is not None:
        return
    if CORP_CODE_CACHE.exists():
        _corp_map = json.loads(CORP_CODE_CACHE.read_text(encoding="utf-8"))
    else:
        download_corp_codes()


def _get_corp_code(stock_code: str) -> str | None:
    _ensure_corp_map()
    return _corp_map.get(stock_code)


def _get_disclosures(corp_code: str, days: int) -> list:
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
                score = min(score, -10)
                reasons.append(f"⚠️ {kw}")
                break
    reason = ", ".join(reasons) if reasons else "일반 공시"
    return max(-10, min(10, score)), reason
