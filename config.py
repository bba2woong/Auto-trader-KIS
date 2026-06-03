import os

# 실제 값은 Windows 환경변수로 관리 (load_dotenv 미사용)

MODE = os.environ.get("TRADING_MODE", "mock")

if MODE == "real":
    APP_KEY    = os.environ["KIS_REAL_APP_KEY"]
    APP_SECRET = os.environ["KIS_REAL_APP_SECRET"]
    ACCOUNT    = os.environ["KIS_REAL_ACCOUNT"]
    BASE_URL   = "https://openapi.koreainvestment.com:9443"
    TRD_URL    = "https://openapi.koreainvestment.com:9443"
else:
    APP_KEY    = os.environ["KIS_MOCK_APP_KEY"]
    APP_SECRET = os.environ["KIS_MOCK_APP_SECRET"]
    ACCOUNT    = os.environ["KIS_MOCK_ACCOUNT"]
    BASE_URL   = "https://openapivts.koreainvestment.com:9443"
    TRD_URL    = "https://openapivts.koreainvestment.com:29443"

print(f"[Config] 모드: {MODE.upper()} / Base URL: {BASE_URL}")