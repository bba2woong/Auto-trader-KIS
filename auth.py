import requests
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# 토큰 캐시를 .cache/ 디렉터리에 저장 (git 추적 제외)
_CACHE_DIR       = Path(__file__).parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
TOKEN_CACHE_FILE = str(_CACHE_DIR / "token_cache.json")

def get_access_token():
    import config

    # 캐시된 토큰이 있으면 재사용
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r") as f:
            cache = json.load(f)
            expires_at = datetime.fromisoformat(cache["expires_at"])
            if datetime.now() < expires_at:
                print("[Auth] 캐시된 토큰 사용")
                return cache["access_token"]

    # 새 토큰 발급
    url = f"{config.BASE_URL}/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET
    }

    res = requests.post(url, headers=headers, json=body, verify=False)
    res.raise_for_status()
    data = res.json()

    token      = data["access_token"]
    expires_at = datetime.now() + timedelta(hours=23)

    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({
            "access_token": token,
            "expires_at": expires_at.isoformat()
        }, f)

    print("[Auth] 새 토큰 발급 완료")
    return token
