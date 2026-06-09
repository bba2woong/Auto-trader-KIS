# 📈 KIS Auto Trader

한국투자증권(KIS) Open API 기반 변동성 돌파 자동매매 시스템.
Streamlit GUI, AI 점수 기반 종목 선별, 텔레그램 알림, 백테스팅을 지원합니다.

---

## 목차

1. [전략 개요](#전략-개요)
2. [프로젝트 구조](#프로젝트-구조)
3. [환경 설정](#환경-설정)
4. [실행 방법](#실행-방법)
5. [파라미터 설명](#파라미터-설명)
6. [AI 점수 시스템](#ai-점수-시스템)
7. [백테스팅](#백테스팅)
8. [텔레그램 연동](#텔레그램-연동)
9. [주의사항](#주의사항)

---

## 전략 개요

**래리 윌리엄스 변동성 돌파 전략** 기반의 단타 자동매매입니다.

```
목표가 = 시가 + (전일 고가 - 전일 저가) × K
```

장 중 현재가가 목표가를 돌파하면 매수 진입하고, 트레일링 스탑 또는 하드 손절로 청산합니다.

**종목 선별 기준**

| 항목 | 조건 | 점수 |
|------|------|------|
| 기술 | 변동성 돌파 여부 + 돌파 여유율 | 최대 40점 |
| 기술 | AD Line 상승 여부 | +15점 |
| 기술 | 캔들 패턴 (해머) | +10점 |
| 기술 | 60분봉 강한 양봉 | +15점 |
| AI | Perplexity LLM 뉴스 분석 | 최대 10점 |
| AI | DART 공시 분석 | ±10점 |
| 가점 | 관심종목(watchlist.py) 등록 | +10점 |
| **합계** | | **최대 110점** |

**매수 라우팅**

- 85점 이상 → 자동 매수 (텔레그램 확인 없음)
- 55~84점 → 텔레그램으로 확인 요청
- 55점 미만 → 스킵

---

## 프로젝트 구조

```
kis_trader/
├── app.py                  # Streamlit GUI (주 실행 파일)
├── main.py                 # CLI 진입점
├── config.py               # API 키/URL 설정 (환경변수 기반)
│                           #   QUERY_URL/KEY/SECRET: 가격조회 전용 (항상 실전서버)
├── auth.py                 # 토큰 발급 및 캐시 (.cache/)
│                           #   get_access_token(): 매매용 / get_query_token(): 가격조회 전용
├── api.py                  # 잔고 조회 (Rate Limit 재시도 내장)
├── order.py                # 매수/매도 주문
├── strategy.py             # 목표가 계산, 손절/트레일링 로직
├── strategy_config.py      # 전략 파라미터 설정
├── screener.py             # 실시간 종목 스크리닝 (KOSPI200 + 관심종목)
│                           #   일봉 캐시(_daily_cache)로 동일 데이터 중복 조회 방지
├── scheduler.py            # 장중 매매 루프 (멀티포지션 스레드)
├── telegram_bot.py         # 텔레그램 알림 및 종목 선택 UI
│                           #   다중선택 메시지에 종목별 점수 세부내역 표시
├── trading_logger.py       # 매매 이벤트 JSONL 로그
├── watchlist.py            # 관심종목 코드 목록 (등록 시 +10점 가점)
│
├── scoring/
│   ├── scorer.py           # 총점 계산 + 일별 캐시 관리 (최대 110점)
│   ├── llm_client.py       # Perplexity API 뉴스 분석
│   └── dart_client.py      # DART 공시 분석
│
├── backtest/
│   ├── engine.py           # 일봉 백테스트 엔진
│   ├── engine_intraday.py  # 분봉 단타 백테스트 엔진
│   ├── screener_sim.py     # 과거 데이터 스크리닝 시뮬레이션
│   ├── data_loader.py      # KIS API 일봉/분봉 수집
│   ├── data_loader_yf.py   # yfinance 분봉 수집 (최근 60일)
│   ├── report.py           # 백테스트 결과 출력
│   └── backtest.py         # CLI 백테스트 메뉴
│
├── trading_logs/           # 매매 로그 (YYYYMMDD.jsonl)
├── .cache/                 # 토큰 캐시 (git 제외)
├── KIS_Trader_실행.bat     # Windows 실행 스크립트
└── .gitignore
```

---

## 환경 설정

### 1. 필수 환경변수 (Windows 시스템 환경변수)

> **API 키는 절대 파일에 저장하지 마세요.** `.env` 파일 사용 금지 — 보안을 위해 Windows 시스템 환경변수로만 관리합니다.  
> `sysdm.cpl` → 고급 → 환경변수에서 등록 후 터미널 재시작.

```
# 모의투자 (주문/잔고 전용)
KIS_MOCK_APP_KEY      = 발급받은 모의투자 AppKey
KIS_MOCK_APP_SECRET   = 발급받은 모의투자 AppSecret
KIS_MOCK_ACCOUNT      = 모의투자 계좌번호 (예: 12345678-01)

# 실전투자 (주문/잔고 + 가격조회 공용)
KIS_REAL_APP_KEY      = 발급받은 실전투자 AppKey
KIS_REAL_APP_SECRET   = 발급받은 실전투자 AppSecret
KIS_REAL_ACCOUNT      = 실전투자 계좌번호

# 텔레그램 선택봇 (매수 선택 / 전량매도 문의)
TELEGRAM_BOT_TOKEN       = BotFather에서 발급받은 토큰
TELEGRAM_CHAT_ID         = 메시지 수신 채팅방 ID

# 텔레그램 알람봇 (체결 알림 / 수익률 정기 알림)
TELEGRAM_ALARM_BOT_TOKEN = 알람봇 토큰
TELEGRAM_ALARM_CHAT_ID   = 알람봇 수신 채팅방 ID

# AI 점수 (선택)
PERPLEXITY_API_KEY    = Perplexity API 키
DART_API_KEY          = DART 오픈API 키
```

> **모의투자 모드에서도 가격조회는 실전 서버(`openapi.koreainvestment.com:9443`)를 사용합니다.**  
> 따라서 `KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET`은 모의투자 시에도 반드시 등록해야 합니다.

### 2. Python 가상환경 및 패키지 설치

```bash
python -m venv venv
venv\Scripts\activate
pip install streamlit pandas plotly requests python-telegram-bot yfinance
```

### 3. DART 기업코드 초기화 (DART 사용 시 1회)

```python
from scoring.dart_client import download_corp_codes
download_corp_codes()
```

---

## 실행 방법

### Streamlit GUI (권장)

```bash
# Windows
KIS_Trader_실행.bat 더블클릭

# 또는 직접 실행
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속.

### CLI

```bash
python main.py
# 1: 모의투자 / 2: 실전투자 / 3: 백테스팅 선택
```

---

## 파라미터 설명

`strategy_config.py` 또는 Streamlit 사이드바에서 조정합니다.
사이드바 변경은 런타임에만 반영되며, 영구 저장은 `strategy_config.py` 직접 수정이 필요합니다.

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `K` | 0.4 | 변동성 계수. 낮을수록 빠른 진입, 높을수록 보수적 (권장: 0.3~0.7) |
| `INVEST_RATIO` | 1.0 | 예수금 중 투자 비율 |
| `LOSS_RATE` | 0.023 | 하드 손절 기준 (-2.3%). 트레일링 스탑과 무관하게 항상 작동 |
| `TRAILING_STOP_RATE` | 0.03 | 고점 대비 하락률 (-3%) 시 청산 |
| `TRAILING_STOP_ACTIVATE_RATE` | 0.04 | 트레일링 스탑 활성화 최소 수익률 (+4%) |
| `MAX_POSITIONS` | 5 | 동시 보유 최대 포지션 수. 예산을 이 수로 나눔 |
| `MAX_TRADES_PER_DAY` | 10 | 하루 최대 매매 횟수 |
| `KOSPI_POOL_SIZE` | 150 | 코스피200에서 스크리닝할 종목 수 |
| `KOSDAQ_POOL_SIZE` | 10 | 코스닥150에서 스크리닝할 종목 수 (0이면 비활성화) |
| `SCREENING_INTERVAL` | 10 | 스크리닝 주기 (분) |
| `MAX_BREAKOUT_GAP` | 1.0 | 돌파 직후 진입 허용 여유율 (%). 이 이상이면 고점 진입으로 보류 |
| `AUTO_BUY_SCORE` | 85 | 자동 매수 점수 기준 (최대 110점) |
| `CONFIRM_SCORE_MIN` | 55 | 텔레그램 확인 요청 최소 점수 |
| `MASS_SELL_QUERY_TIMES` | `["13:30","14:00","14:30"]` | 전량 매도 문의 시각 |

---

## AI 점수 시스템

### 점수 구성 (총 110점)

```
기술점수 (최대 80점)
  ├── 변동성 돌파: 최대 40점 (돌파 여유율에 따라 선형 감소)
  ├── AD Line 상승: +15점
  ├── 캔들 패턴: +10점 (해머)
  └── 60분봉 강한 양봉: +15점

AI 점수 (최대 20점)
  ├── LLM (Perplexity): bullish=10 / neutral=5 / bearish=0
  └── DART 공시: 긍정=+10 / 중립=0 / 부정=-10

관심종목 가점
  └── watchlist.py 등록 종목: +10점
```

`USE_AI_SCORING = False`로 설정하면 기술 점수(80점 만점)만 사용하며,
Threshold도 자동으로 0.7배 스케일링됩니다.

### 캐시 갱신 시점

스케줄러 실행 중 아래 시각에 LLM + DART 분석이 자동 갱신됩니다.

- 08:30 (장 전)
- 10:00
- 12:00

캐시 파일: `scoring/cache/daily_YYYYMMDD.json`

### 관심종목 가점

`watchlist.py`에 등록된 종목 코드는 스크리닝 통과 시 자동으로 **+10점** 가산됩니다.
별도 설정 없이 `WATCHLIST_CODES` 리스트에 6자리 코드만 추가하면 됩니다.

---

## 백테스팅

### 유형

| 유형 | 데이터 | 적합 용도 |
|------|--------|-----------|
| 일봉 (daily) | KIS API 일봉 | 장기 전략 검증, K값 최적화 |
| 분봉 단타 (intraday) | yfinance 분봉 | 단타 전략 검증, 파라미터 그리드 서치 |

### 분봉 데이터 제한

- 1분봉: 최근 7일 이내
- 5분봉: 최근 60일 이내 (자동 전환)

### 분봉 단타 백테스팅 (매매 로그 기반)

실제 운영 후 `trading_logs/YYYYMMDD.jsonl`이 쌓이면, 당일 스크리닝 후보 종목을 로그에서 자동으로 불러와 정밀 백테스트가 가능합니다.

**특징**
- 스크리닝 시각의 분봉 종가에 즉시 매수 가정 (목표가 재돌파 대기 없음)
- 포지션당 예산 = 초기자금 ÷ 당일 포지션 수 (자동 입력, 수정 가능)
- 그리드 서치: 손절(%) × 트레일링(%) 조합으로 결과 테이블 표시
- 결과 테이블에 종목별 수익률 개별 표시 + 색상(양수=청색/음수=적색)
- 종목 선택 또는 파라미터 변경 시 이전 결과 자동 초기화

> 그리드 서치는 `params` 딕셔너리를 통해 전달되므로, 실시간 트레이딩 중에도 전역 파라미터(`strategy_config`)를 오염시키지 않습니다.

---

## 텔레그램 연동

### 봇 구성

| 봇 | 역할 | 환경변수 |
|---|---|---|
| `kis_trader_bot` | 매수 종목 선택, 전량매도 문의 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `kis_trader_alarmbot` | 매수/매도 체결 알림, 수익률 정기 알림 | `TELEGRAM_ALARM_BOT_TOKEN`, `TELEGRAM_ALARM_CHAT_ID` |

### 설정 방법

1. BotFather에서 봇 2개 생성 후 각각 토큰 환경변수에 등록
2. `@userinfobot`으로 본인 Chat ID 확인 후 등록
3. 연동 테스트: `python test_telegram.py`

### 매매 흐름

```
09:30~14:00  매 10분 스크리닝
  → kis_trader_bot: 후보 종목 버튼 전송 (최대 N개 멀티선택, N=빈 슬롯 수)
  → 종목별 점수 세부내역 표시 (돌파/AD/캔들/양봉/LLM/DART/관심종목)
  → 관심종목(watchlist)은 ⭐관심 배지로 강조 표시

13:30 / 14:00 / 14:30  전량 매도 문의
  → kis_trader_bot: 보유 종목별 수익률 + ⬜/✅ 토글 버튼
  → 선택 종목만 청산, 미응답 시 자동 유지

15:00  강제 전량 청산

매수 체결    → kis_trader_alarmbot 알림 (점수 세부내역 포함)
매도 체결    → kis_trader_alarmbot 알림 (청산 조건 포함)
20분 주기    → kis_trader_alarmbot 보유 수익률 알림 (09:30~15:00)
```

### 멀티 선택 UI

- 스크리닝 결과 전송 시 빈 슬롯 수만큼 동시 선택 가능
- 버튼 탭 → ✅ 토글, 재탭 → ⬜ 해제
- 선택 완료(N개) 버튼 또는 N개 채워지면 자동 확정
- 각 후보 종목 아래 점수 세부내역 표시:
  ```
  🥇 1위  삼성전자 ⭐관심 (005930) 🔨
      목표가: 82,000원  여유율: +0.31%
      📊 돌파:38점 AD:15점 캔들:10점 양봉:15점 LLM:5점 DART:10점 ⭐+10점 → 합계:93점
  ```

---

## API 서버 구조

KIS API는 **가격조회 서버**와 **주문/잔고 서버**가 분리되어 있습니다.

| 용도 | 서버 | 앱키 |
|------|------|------|
| 가격조회 (현재가·일봉·시간봉) | `openapi.koreainvestment.com:9443` (실전) | 실전 앱키 항상 사용 |
| 주문·잔고 (모의투자) | `openapivts.koreainvestment.com:9443` | 모의투자 앱키 |
| 주문·잔고 (실전투자) | `openapi.koreainvestment.com:9443` | 실전투자 앱키 |

> 모의투자 모드에서도 가격조회는 실전 서버·실전 앱키를 사용합니다.  
> 토큰도 별도로 발급·캐시됩니다 (`.cache/token_cache_query.json`).

---

## 매매 안전장치

| 기능 | 설명 |
|---|---|
| API 재시도 | 가격조회 500 에러 시 최대 6회 재시도 (점진적 대기) |
| 토큰 만료 자동 갱신 | HTTP 500 본문의 `EGW00123` 감지 → 즉시 재발급 후 재시도 |
| Rate Limit 재시도 | `EGW00201` 감지 → 대기 후 재시도 (잔고조회 최대 15회) |
| 09:00 부하 분산 | 장 시작 후 잔고 조회 전 5초 대기 |
| 연속 오류 청산 | 10회 연속 API 실패 시 자동 청산 후 슬롯 반환 |
| Thread Jitter | 멀티 포지션 시작 시 0~3초 랜덤 지연으로 동시 API 호출 분산 |
| 토큰 Thread Lock | 멀티 스레드 토큰 캐시 동시 접근 충돌 방지 |
| 포지션 복구 | 재시작 시 KIS 잔고 조회로 기존 보유 포지션 자동 복구 |
| HTS 수동매도 감지 | 5루프(약 100초)마다 잔고 확인, 외부 매도 감지 시 슬롯 자동 반환 |
| 텔레그램 충돌 방지 | 봇 시작 전 `deleteWebhook` 호출로 이전 폴링 세션 초기화 |
| 수동매수 폴백 | 목표가 조회 실패 시 시장가 즉시 매수로 폴백 |
| 일봉 캐시 | `_daily_cache`로 스크리닝 중 동일 종목 중복 API 호출 방지 |

---

## 주의사항

**실전투자 전 반드시 확인하세요.**

- 모의투자와 실전투자는 주문 API Key와 Base URL이 다릅니다. 사이드바에서 모드를 바꾸면 즉시 전환됩니다.
- **가격조회는 항상 실전 앱키**를 사용합니다. `KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET` 미설정 시 스크리닝이 동작하지 않습니다.
- Desktop이 절전 또는 화면 잠금 상태여도 서버(Streamlit)는 계속 실행됩니다. 단, 네트워크 단절 시 API 오류로 강제 청산 로직이 작동합니다.
- API Rate Limit: KIS 모의투자 서버는 실전 서버보다 Rate Limit이 낮습니다. `CHECK_INTERVAL`을 20초 이상 권장합니다.
- 백테스팅 결과는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
- `SCREENING_END_TIME`(기본 14:00) 이후로는 신규 포지션 진입이 중단됩니다.

### .gitignore 필수 항목

```
.cache/
trading_logs/
scoring/cache/
token_cache.json
*.env
```

---

## 테스트

```bash
# API 연결 및 매수/매도 테스트 (모의투자)
python test_trade.py

# 텔레그램 연동 테스트
python test_telegram.py

# AI 점수 시스템 테스트
python test_scoring.py
```

---

## 라이선스

개인 사용 목적으로 제작된 프로젝트입니다.
한국투자증권 Open API 이용약관을 준수하여 사용하세요.
