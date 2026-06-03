"""
Perplexity API 기반 종목 분석 (sonar 모델 — 웹 검색 내장)
최근 3일 뉴스 + 시장 동향을 분석해서 상승 의견 여부와 점수를 반환한다.

환경변수:
  PERPLEXITY_API_KEY : Perplexity API 키
"""
import os
import json
import time
import requests

API_KEY  = os.environ.get("PERPLEXITY_API_KEY", "")
API_URL  = "https://api.perplexity.ai/chat/completions"
MODEL    = "sonar"          # 웹 검색 내장 모델
BATCH_SZ = 5                # 한 번에 분석할 종목 수 (토큰 절약)
TIMEOUT  = 30               # API 요청 타임아웃 (초)


def analyze_stocks(stock_list: list) -> dict:
    """
    종목 리스트에 대해 Perplexity 분석 수행
    stock_list : [{"code": "005930", "name": "삼성전자"}, ...]
    반환       : {code: {"score": 0~20, "opinion": "bullish|neutral|bearish", "reason": str}}
    """
    if not API_KEY:
        print("  [LLM] PERPLEXITY_API_KEY 미설정 — 분석 건너뜀")
        return {s["code"]: _neutral(s["code"]) for s in stock_list}

    results = {}
    total   = len(stock_list)

    for i in range(0, total, BATCH_SZ):
        batch = stock_list[i: i + BATCH_SZ]
        print(f"  [LLM] 분석 중 ({i+1}~{min(i+BATCH_SZ, total)}/{total})...", end="\r")
        batch_result = _analyze_batch(batch)
        results.update(batch_result)
        time.sleep(1)  # Rate limit 방지

    print(f"\n  [LLM] 분석 완료: {len(results)}개")
    return results


def _analyze_batch(batch: list) -> dict:
    names = ", ".join(f"{s['name']}({s['code']})" for s in batch)

    prompt = f"""다음 한국 코스피 상장 주식들의 최근 3일간 뉴스, 공시, 시장 동향을 검색하고
각 종목의 단기(당일~1일) 주가 상승 가능성을 평가해주세요.

분석 대상: {names}

반드시 아래 JSON 형식으로만 답변하세요 (다른 텍스트 없이):
{{
  "종목코드": {{
    "opinion": "bullish 또는 neutral 또는 bearish",
    "score": 정수(bullish=20, neutral=10, bearish=0),
    "reason": "한 줄 근거 (한국어, 30자 이내)"
  }}
}}"""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type":  "application/json",
    }
    body = {
        "model":    MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens":  800,
    }

    try:
        res = requests.post(API_URL, headers=headers, json=body, timeout=TIMEOUT)
        res.raise_for_status()
        raw = res.json()["choices"][0]["message"]["content"].strip()

        # 마크다운 코드블록 제거
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw.strip())

        # 응답 정규화
        result = {}
        for s in batch:
            code = s["code"]
            item = data.get(code, {})
            result[code] = {
                "score":   int(item.get("score",   10)),
                "opinion": item.get("opinion", "neutral"),
                "reason":  item.get("reason",  "분석 없음"),
            }
        return result

    except Exception as e:
        print(f"\n  [LLM] 배치 오류: {e}")
        return {s["code"]: _neutral(s["code"]) for s in batch}


def _neutral(code):
    return {"score": 10, "opinion": "neutral", "reason": "분석 실패"}
