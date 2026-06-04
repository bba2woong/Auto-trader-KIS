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

**종목 선별 기준 (3단계)**

| 단계 | 조건 | 점수 |
|------|------|------|
| 기술적 | 변동성 돌파 여부 + 돌파 여유율 | 최대 30점 |
| 기술적 | AD Line 상승 여부 | 30점 |
| 기술적 | 캔들 패턴 (해머 +10 / 행잉맨 -10) | ±10점 |
| AI | Perplexity LLM 뉴스 분석 | 최대 20점 |
| AI | DART 공시 분석 | ±10점 |
| **합계** | | **최대 100점** |

**매수 라우팅**

- 85점 이상 → 자동 매수 (텔레그램 확인 없음)
- 60~84점 → 텔레그램으로 확인 요청
- 60점 미만 → 스킵

---

## 프로젝트 구조

```
kis_trader/
├── app.py                  # Streamlit GUI (주 실행 파일)
├── main.py                 # CLI 진입점
├── config.py               # API 키/URL 설정 (환경변수 기반)
├── auth.py                 # 토큰 발급 및 캐시 (.cache/)
├── api.py                  # 잔고 조회
├── order.py                # 매수/매도 주문
├── strategy.py             # 목표가 계산, 손절/트레일링 로직
├── strategy_config.py      # 전략 파라미터 설정
├── screener.py             # 실시간 종목 스크리닝 (KOSPI200 + 관심종목)
├── scheduler.py            # 장중 매매 루프 (멀티포지션 스레드)
├── telegram_bot.py         # 텔레그램 알림 및 종목 선택 UI
├── trading_logger.py       # 매매 이벤트 JSONL 로그
├── watchlist.py            # 관심종목 코드 목록
│
├── scoring/
│   ├── scorer.py           # 총점 계산 + 일별 캐시 관리
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

```
# 모의투자
KIS_MOCK_APP_KEY      = 발급받은 모의투자 AppKey
KIS_MOCK_APP_SECRET   = 발급받은 모의투자 AppSecret
KIS_MOCK_ACCOUNT      = 모의투자 계좌번호 (예: 12345678-01)

# 실전투자
KIS_REAL_APP_KEY      = 발급받은 실전투자 AppKey
KIS_REAL_APP_SECRET   = 발급받은 실전투자 AppSecret
KIS_REAL_ACCOUNT      = 실전투자 계좌번호

# 텔레그램 (선택)
TELEGRAM_BOT_TOKEN    = BotFather에서 발급받은 토큰
TELEGRAM_CHAT_ID      = 메시지 수신 채팅방 ID

# AI 점수 (선택)
PERPLEXITY_API_KEY    = Perplexity API 키
DART_API_KEY          = DART 오픈API 키
```

> **환경변수 설정 후 터미널(cmd)을 재시작해야 반영됩니다.**
> `sysdm.cpl` → 고급 → 환경변수에서 등록.

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
| `K` | 0.5 | 변동성 계수. 낮을수록 빠른 진입, 높을수록 보수적 (권장: 0.3~0.7) |
| `INVEST_RATIO` | 1.0 | 예수금 중 투자 비율 |
| `LOSS_RATE` | 0.023 | 하드 손절 기준 (-2.3%). 트레일링 스탑과 무관하게 항상 작동 |
| `TRAILING_STOP_RATE` | 0.04 | 고점 대비 하락률 (-4%) 시 청산 |
| `TRAILING_STOP_ACTIVATE_RATE` | 0.02 | 트레일링 스탑 활성화 최소 수익률 (+2%) |
| `MAX_POSITIONS` | 5 | 동시 보유 최대 포지션 수. 예산을 이 수로 나눔 |
| `MAX_TRADES_PER_DAY` | 10 | 하루 최대 매매 횟수 |
| `KOSPI_POOL_SIZE` | 150 | 코스피200에서 스크리닝할 종목 수 |
| `SCREENING_INTERVAL` | 20 | 스크리닝 주기 (분) |
| `MAX_BREAKOUT_GAP` | 1.0 | 돌파 직후 진입 허용 여유율 (%). 이 이상이면 고점 진입으로 보류 |
| `AUTO_BUY_SCORE` | 85 | 자동 매수 점수 기준 |
| `CONFIRM_SCORE_MIN` | 60 | 텔레그램 확인 요청 최소 점수 |

---

## AI 점수 시스템

### 캐시 갱신 시점

스케줄러 실행 중 아래 시각에 자동 갱신됩니다.

- 08:30 (장 전)
- 10:00
- 13:00

캐시 파일: `scoring/cache/daily_YYYYMMDD.json`

### 점수 구성 (총 100점)

```
기술점수 (최대 70점)
  ├── 변동성 돌파: 최대 30점 (돌파 여유율에 따라 선형 감소)
  ├── AD Line 상승: 30점
  └── 캔들 패턴: +10점(해머) / -10점(행잉맨)

AI 점수 (최대 30점)
  ├── LLM (Perplexity): bullish=20 / neutral=10 / bearish=0
  └── DART 공시: 긍정=+10 / 중립=0 / 부정=-10
```

`USE_AI_SCORING = False`로 설정하면 기술 점수(70점 만점)만 사용하며, Threshold도 자동으로 0.7배 스케일링됩니다.

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

### 파라미터 그리드 서치

Streamlit 백테스팅 탭에서 K / 손절 / 트레일링 범위를 설정하면 모든 조합을 한 번에 계산합니다. 데이터는 캐시되어 재수집 없이 반복 실행 가능합니다.

> 그리드 서치는 `params` 딕셔너리를 통해 전달되므로, 실시간 트레이딩 중에도 전역 파라미터(`strategy_config`)를 오염시키지 않습니다.

---

## 텔레그램 연동

### 설정 방법

1. BotFather에서 봇 생성 후 `TELEGRAM_BOT_TOKEN` 환경변수에 등록
2. `@userinfobot`으로 본인 Chat ID 확인 후 `TELEGRAM_CHAT_ID` 등록
3. 연동 테스트: `python test_telegram.py`

### 동작 방식

- 스크리닝 결과를 인라인 버튼으로 전송
- 버튼 탭으로 최대 N개 종목 멀티 선택 (N = 빈 슬롯 수)
- `TELEGRAM_CONFIRM_TIMEOUT`(기본 1800초) 내 무응답 시 자동 패스
- 청산 이벤트(익절/손절/강제청산)도 즉시 알림

---

## 주의사항

**실전투자 전 반드시 확인하세요.**

- 모의투자와 실전투자는 API Key와 Base URL이 다릅니다. 사이드바에서 모드를 바꾸면 즉시 전환되므로 실수에 주의하세요.
- Desktop이 절전 또는 화면 잠금 상태여도 서버(Streamlit)는 계속 실행됩니다. 단, 네트워크 단절 시 API 오류로 강제 청산 로직이 작동합니다 (연속 10회 오류 시 자동 청산).
- API Rate Limit: KIS API는 초당 호출 제한이 있습니다. `CHECK_INTERVAL`(기본 10초)을 너무 짧게 설정하지 마세요.
- 백테스팅 결과는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.

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
