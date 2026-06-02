import os
from dotenv import load_dotenv

load_dotenv()

MODE = os.getenv("TRADING_MODE", "mock")

if MODE == "real":
    APP_KEY    = os.getenv("REAL_APP_KEY")
    APP_SECRET = os.getenv("REAL_APP_SECRET")
    ACCOUNT    = os.getenv("REAL_ACCOUNT")
    BASE_URL   = "https://openapi.koreainvestment.com:9443"
    TRD_URL    = "https://openapi.koreainvestment.com:9443"   # 실전 거래 URL
else:
    APP_KEY    = os.getenv("MOCK_APP_KEY")
    APP_SECRET = os.getenv("MOCK_APP_SECRET")
    ACCOUNT    = os.getenv("MOCK_ACCOUNT")
    BASE_URL   = "https://openapivts.koreainvestment.com:9443"
    TRD_URL    = "https://openapivts.koreainvestment.com:29443"  # 모의 거래 URL ← 포트 다름!

print(f"[Config] 모드: {MODE.upper()} / Base URL: {BASE_URL}")