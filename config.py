import os

# 실제 값은 Windows 환경변수로 관리 (load_dotenv 미사용)

def get_config(mode=None):
    """
    mode를 인자로 받아 동적으로 설정값 반환.
    None이면 TRADING_MODE 환경변수 사용.
    """
    m = mode or os.environ.get("TRADING_MODE", "mock")
    # 가격 조회(현재가·일봉·분봉)는 모의/실전 무관하게 항상 실서버+실전앱키 사용
    REAL_API        = "https://openapi.koreainvestment.com:9443"
    REAL_APP_KEY    = os.environ["KIS_REAL_APP_KEY"]
    REAL_APP_SECRET = os.environ["KIS_REAL_APP_SECRET"]

    if m == "real":
        return {
            "MODE":            "real",
            "APP_KEY":         REAL_APP_KEY,
            "APP_SECRET":      REAL_APP_SECRET,
            "ACCOUNT":         os.environ["KIS_REAL_ACCOUNT"],
            "BASE_URL":        REAL_API,
            "TRD_URL":         REAL_API,
            "QUERY_URL":       REAL_API,
            "QUERY_APP_KEY":   REAL_APP_KEY,
            "QUERY_APP_SECRET":REAL_APP_SECRET,
        }
    else:
        return {
            "MODE":            "mock",
            "APP_KEY":         os.environ["KIS_MOCK_APP_KEY"],
            "APP_SECRET":      os.environ["KIS_MOCK_APP_SECRET"],
            "ACCOUNT":         os.environ["KIS_MOCK_ACCOUNT"],
            "BASE_URL":        "https://openapivts.koreainvestment.com:9443",
            "TRD_URL":         "https://openapivts.koreainvestment.com:29443",
            "QUERY_URL":       REAL_API,       # 가격 조회는 실서버
            "QUERY_APP_KEY":   REAL_APP_KEY,   # 실전 앱키로 조회
            "QUERY_APP_SECRET":REAL_APP_SECRET,
        }


# 모듈 레벨 속성 — 기존 코드 호환성 유지 (import config; config.APP_KEY 형태)
_cfg = get_config()
MODE       = _cfg["MODE"]
APP_KEY    = _cfg["APP_KEY"]
APP_SECRET = _cfg["APP_SECRET"]
ACCOUNT    = _cfg["ACCOUNT"]
BASE_URL         = _cfg["BASE_URL"]
TRD_URL          = _cfg["TRD_URL"]
QUERY_URL        = _cfg["QUERY_URL"]
QUERY_APP_KEY    = _cfg["QUERY_APP_KEY"]
QUERY_APP_SECRET = _cfg["QUERY_APP_SECRET"]

print(f"[Config] 모드: {MODE.upper()} / Base URL: {BASE_URL}")


def reload(mode=None):
    """
    런타임에 모드 전환 시 호출.
    app.py 등에서 사이드바 모드 변경 후 reload('real') 형태로 사용.
    """
    import sys
    cfg = get_config(mode)
    module = sys.modules[__name__]
    for k, v in cfg.items():
        setattr(module, k, v)
    print(f"[Config] 모드 전환: {cfg['MODE'].upper()}")
