import requests
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

# 토큰 캐시를 .cache/ 디렉터리에 저장 (git 추적 제외)
_CACHE_DIR       = Path(__file__).parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
TOKEN_CACHE_FILE = str(_CACHE_DIR / "token_cache.json")

_token_lock       = threading.Lock()   # 멀티스레드 동시 접근 방지
_query_token_lock = threading.Lock()   # 가격 조회 전용 토큰 락

QUERY_TOKEN_CACHE_FILE = str(_CACHE_DIR / "token_cache_query.json")


def get_access_token():
    import config

    with _token_lock:
        return _get_token(config)


def get_query_token():
    """가격 조회 전용 토큰 (항상 실전 앱키 사용)"""
    import config
    with _query_token_lock:
        return _get_token_from_file(
            config, QUERY_TOKEN_CACHE_FILE,
            config.QUERY_APP_KEY, config.QUERY_APP_SECRET,
            config.QUERY_URL, label="Query"
        )


def _get_token_from_file(config, cache_file, app_key, app_secret, base_url, label=""):
    """지정된 캐시 파일 + 앱키로 토큰 관리"""
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
            if cache.get("access_token") and cache.get("expires_at"):
                expires_at = datetime.fromisoformat(cache["expires_at"])
                if datetime.now() < expires_at:
                    print(f"[Auth] 캐시된 토큰 사용 ({label})")
                    return cache["access_token"]
        except Exception:
            pass

    url     = f"{base_url}/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    body    = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}

    res = requests.post(url, headers=headers, json=body, verify=False)
    res.raise_for_status()
    data = res.json()

    token      = data["access_token"]
    expires_at = datetime.now() + timedelta(hours=23)

    with open(cache_file, "w") as f:
        json.dump({"access_token": token, "expires_at": expires_at.isoformat()}, f)

    print(f"[Auth] 새 토큰 발급 완료 ({label})")
    return token


def invalidate_token():
    """서버가 EGW00123(토큰 만료)을 반환했을 때 캐시를 무효화 → 다음 호출 시 재발급"""
    try:
        with open(TOKEN_CACHE_FILE, "w") as f:
            json.dump({}, f)
        print("[Auth] 토큰 캐시 초기화 (EGW00123 감지)")
    except Exception:
        pass


def _get_token(config):
    return _get_token_from_file(
        config, TOKEN_CACHE_FILE,
        config.APP_KEY, config.APP_SECRET,
        config.BASE_URL, label="Main"
    )
