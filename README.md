# 📈 KIS Auto Trader

한국투자증권(KIS) Open API 기반 변동성 돌파 자동매매 시스템.  
Streamlit GUI, AI 점수 기반 종목 선별, 텔레그램 알림, 백테스팅, Electron 데스크톱 앱, WatchDog 자동 재시작을 지원합니다.

---

## 빠른 시작 (새 PC 설치)

```
1. git clone https://github.com/bba2woong/Auto-trader-KIS.git
   cd Auto-trader-KIS

2. setup.bat 실행  ← 더블클릭 (Python·Node.js·Electron 자동 설치)

3. Windows 시스템 환경변수에 API 키 등록
   sysdm.cpl → 고급 → 환경변수 → 시스템 변수
   (setup.bat 실행 시 필요한 변수 목록이 출력됩니다)

4. PC 재시작 → WatchDog이 자동으로 앱을 시작합니다
```

> **사전 요구사항:** [Python 3.11+](https://python.org) · [Node.js LTS](https://nodejs.org)  
> 설치 시 **"Add Python to PATH"** 옵션 반드시 체크.

---

## 목차

1. [전략 개요](#전략-개요)
2. [프로젝트 구조](#프로젝트-구조)
3. [환경 설정](#환경-설정)
4. [실행 방법](#실행-방법)
5. [파라미터 설명](#파라미터-설명)
6. [AI 점수 시스템](#ai-점수-시스템)
7. [텔레그램 연동](#텔레그램-연동)
8. [백테스팅](#백테스팅)
9. [WatchDog 자동 재시작](#watchdog-자동-재시작)
10. [PC 이전 체크리스트](#pc-이전-체크리스트)
11. [주의사항](#주의사항)

---

## 전략 개요

**래리 윌리엄스 변동성 돌파 전략** 기반의 단타 자동매매입니다.

```
목표가 = 시가 + (전일 고가 - 전일 저가) × K
```

장 중 현재가가 목표가를 돌파하면 매수 진입하고, 트레일링 스탑 또는 하드 손절로 청산합니다.

### 종목 선별 기준 (최대 110점)

| 항목 | 점수 | 설명 |
|------|------|------|
| 변동성 돌파 | 최대 40점 | 돌파 여부 + 여유율 (낮을수록 고점수) |
| AD Line | +15점 | 최근 5일 AD Line 상승 여부 |
| 캔들 패턴 | +10점 | 해머 패턴 감지 시 |
| 60분봉 강봉 | +15점 | Strong Bull 캔들 감지 시 |
| LLM 분석 | 최대 10점 | bullish=10 / neutral=5 / bearish=0 |
| DART 공시 | +10점 | 긍정=10 / 중립=0 / 부정=-10 |
| 관심종목 | +10점 | watchlist.py 등록 종목 가점 |
| **합계** | **최대 110점** | |

### 매수 라우팅

- **90점 이상** → 자동 매수 (텔레그램 확인 없음)
- **60~89점** → 텔레그램으로 확인 요청
- **60점 미만** → 스킵

---

## 프로젝트 구조

```
C:\KIS_Trader\1. Practice\kis_trader\
│
├── app.py                  # Streamlit GUI (주 실행 파일)
├── main.py                 # CLI 진입점
├── config.py               # API 키/URL 설정 (환경변수 기반, 동적 모드 전환)
├── auth.py                 # 토큰 발급 + 메모리/파일 캐시 + threading.Lock
├── api.py                  # 잔고·최대주문수량 조회 (Rate Limit 자동 재시도)
├── order.py                # 매수/매도 주문
├── strategy.py             # 목표가 계산, 손절/트레일링 로직, 수량 계산
├── strategy_config.py      # 전략 파라미터 설정
├── screener.py             # 종목 스크리닝 (KOSPI200 + KOSDAQ150 + 관심종목)
├── scheduler.py            # 장중 매매 루프 (멀티포지션 스레드)
├── telegram_bot.py         # 텔레그램 선택봇 (종목 선택 UI, 매도 선택)
├── telegram_alarm.py       # 텔레그램 알람봇 (단방향 체결/수익률 알림)
├── trading_logger.py       # 매매 이벤트 JSONL 로그
├── trading_state.py        # 트레이딩 상태 영속화 (WatchDog 연동)
├── watchlist.py            # 관심종목 코드 목록
├── watchdog.py             # WatchDog 메인 로직 (pythonw로 창 없이 실행)
├── watchdog.bat            # WatchDog BAT (레거시 / 직접 실행용)
├── watchdog_hidden.vbs     # WatchDog VBS 래퍼 (숨김 실행)
│
├── electron/               # Electron 데스크톱 앱 래퍼
│   ├── main.js             # Electron 메인 프로세스
│   └── package.json        # Node.js 의존성
│
├── assets/
│   ├── icon.ico            # 앱 아이콘 (Windows 작업표시줄)
│   └── icon.png            # 트레이 아이콘
│
├── scoring/
│   ├── scorer.py           # 총점 계산 + 일별 캐시 관리
│   ├── llm_client.py       # Perplexity API 뉴스 분석
│   └── dart_client.py      # DART 공시 분석
│
├── backtest/
│   ├── engine.py           # 일봉 백테스트 엔진
│   ├── engine_intraday.py  # 분봉 단타 백테스트 엔진 (params 격리)
│   ├── screener_sim.py     # 과거 데이터 스크리닝 시뮬레이션
│   ├── data_loader.py      # KIS API 일봉/분봉 수집
│   ├── data_loader_yf.py   # yfinance 분봉 수집 (최근 60일)
│   ├── report.py           # 백테스트 결과 출력
│   └── backtest.py         # CLI 백테스트 메뉴
│
├── trading_logs/           # 매매 로그 (YYYYMMDD.jsonl)
├── .cache/                 # 토큰 캐시, 상태 파일 (git 제외)
│   ├── token_cache.json    # KIS API 액세스 토큰
│   ├── trader_state.json   # 트레이딩 실행 상태 (WatchDog용)
│   └── watchdog.log        # WatchDog 실행 로그
└── scoring/cache/          # AI 점수 일별 캐시 (git 제외)
    ├── daily_YYYYMMDD.json
    └── corp_codes.json     # DART 기업코드 맵
```

---

## 환경 설정

### 1. 필수 환경변수 (Windows 시스템 환경변수)

`sysdm.cpl` → 고급 → 환경변수에서 등록. **등록 후 터미널 재시작 필수.**

> **보안:** `.env` 파일 사용 금지. 모든 API 키는 Windows 시스템 환경변수로만 관리합니다.

```
# KIS API — 모의투자
KIS_MOCK_APP_KEY
KIS_MOCK_APP_SECRET
KIS_MOCK_ACCOUNT        # 예: 12345678-01

# KIS API — 실전투자
KIS_REAL_APP_KEY
KIS_REAL_APP_SECRET
KIS_REAL_ACCOUNT

# 텔레그램 선택봇 (종목 선택 UI)
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID

# 텔레그램 알람봇 (체결/수익률 알림)
TELEGRAM_ALARM_BOT_TOKEN
TELEGRAM_ALARM_CHAT_ID

# AI 점수 (선택)
PERPLEXITY_API_KEY
DART_API_KEY
```

> **중요:** 가격 조회(현재가·일봉·분봉)는 모의/실전 무관하게 항상 실서버 + 실전 앱키를 사용합니다.

### 2. Python 환경

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. DART 기업코드 초기화 (DART 사용 시 1회)

```python
from scoring.dart_client import download_corp_codes
download_corp_codes()
```

---

## 실행 방법

### Electron 데스크톱 앱 (권장)

```
assets/launch.vbs 더블클릭
```

Electron 앱이 실행되며, 내부적으로 Streamlit 서버를 자동 시작합니다. 브라우저 없이 독립 창으로 실행됩니다.

#### Electron 초기 설치 (최초 1회)

```bash
cd electron
npm install
```

### Streamlit 직접 실행

```bash
# 단순 실행
KIS_Trader_실행.bat 더블클릭
```

브라우저에서 `http://localhost:8501` 접속.

### CLI

```bash
python main.py
# 1: 모의투자 / 2: 실전투자 / 3: 백테스팅
```

### 동작 확인 테스트

```bash
python test_trade.py      # KIS API 연결 확인
python test_telegram.py   # 텔레그램 연결 확인
python test_scoring.py    # AI 점수 시스템 확인
```

---

## 파라미터 설명

`strategy_config.py` 또는 Streamlit 사이드바에서 조정합니다.  
사이드바 변경은 런타임에만 반영되며, 영구 저장은 `strategy_config.py` 직접 수정이 필요합니다.

### 핵심 파라미터

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `K` | 0.4 | 변동성 계수. 낮을수록 빠른 진입 (권장: 0.3~0.7) |
| `INVEST_RATIO` | 1.0 | 예수금 중 투자 비율 |
| `LOSS_RATE` | 0.023 | 하드 손절 (-2.3%). 트레일링 스탑과 무관하게 항상 작동 |
| `TRAILING_STOP_RATE` | 0.03 | 고점 대비 하락률 (-3%) 시 청산 |
| `TRAILING_STOP_ACTIVATE_RATE` | 0.04 | 트레일링 스탑 활성화 최소 수익률 (+4%) |

### 시간 설정

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `FORCE_SELL_TIME` | 15:00 | 강제 청산 시각 |
| `SCREENING_END_TIME` | 14:00 | 신규 진입 마감 시각 |
| `CHECK_INTERVAL` | 20초 | 시세 체크 주기 |
| `SCREENING_INTERVAL` | 10분 | 스크리닝 반복 주기 |
| `MASS_SELL_QUERY_TIMES` | 13:30, 14:00, 14:30 | 전량 매도 문의 시각 |

### 포지션 / 스크리닝

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `MAX_POSITIONS` | 5 | 동시 보유 최대 포지션 수 |
| `MAX_TRADES_PER_DAY` | 10 | 하루 최대 매매 횟수 |
| `KOSPI_POOL_SIZE` | 150 | 코스피200 스크리닝 종목 수 |
| `KOSDAQ_POOL_SIZE` | 10 | 코스닥150 스크리닝 종목 수 |
| `MAX_BREAKOUT_GAP` | 1.0% | 돌파 직후 진입 허용 여유율 상한 |
| `SAME_STOCK_COOLDOWN` | 100초 | 동일 종목 재매매 쿨다운 |
| `POSITION_ALERT_INTERVAL` | 20분 | 수익률 정기 알림 주기 |

### AI / 텔레그램

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `AUTO_BUY_SCORE` | 90 | 자동 매수 기준 점수 |
| `CONFIRM_SCORE_MIN` | 60 | 텔레그램 확인 요청 최소 점수 |
| `TELEGRAM_CONFIRM_TIMEOUT` | 300초 | 텔레그램 선택 대기 시간 |

---

## AI 점수 시스템

### 캐시 갱신 시점

스케줄러 실행 중 아래 시각에 자동 갱신:
- **08:30** (장 전)
- **10:00**
- **12:00**

캐시 파일: `scoring/cache/daily_YYYYMMDD.json`

### LLM 분석 (Perplexity sonar)

- 스크리닝 풀 전체 종목을 5개씩 묶어 Perplexity API에 전송
- 최근 3일 뉴스 + 시장 동향 기반 방향성 판단
- `bullish=10점 / neutral=5점 / bearish=0점`
- API 키 미설정 시 전체 neutral(5점) 처리

### DART 공시 분석

- 최근 3일 공시 제목을 긍정/부정 키워드로 분석
- 긍정(수주, 계약, 흑자전환 등): +10점
- 부정(적자전환, 횡령, 유상증자 등): -10점
- 최초 실행 시 `download_corp_codes()` 1회 필요

---

## 텔레그램 연동

### 봇 구조 (2개 봇 분리)

| 봇 | 환경변수 | 역할 |
|---|---|---|
| 선택봇 | `TELEGRAM_BOT_TOKEN` | 종목 선택 UI, 매도 종목 선택, 재시작 모드 선택 |
| 알람봇 | `TELEGRAM_ALARM_BOT_TOKEN` | 매수/매도 체결 알림, 수익률 정기 알림, 스크리닝 결과 로그 |

### 주요 알림 항목

- 스크리닝 결과 (라운드별 종목별 점수 현황)
- 매수 체결 (종목명, 체결가, 수량, 투자금)
- 매도 체결 (청산 사유, 수익률, 손익)
- 보유 종목 수익률 (20분 주기)
- 13:30 / 14:00 / 14:30 매도 종목 선택 문의
- 비정상 종료 감지 및 재시작 모드 선택
- 매수 대기 1시간 초과 시 슬롯 반환 알림
- 주문가능금액 부족 시 수량 재조정 알림
- HTS 수동 매수 종목 자동 모니터링 시작 알림

### 텔레그램 명령어

| 명령 | 동작 |
|------|------|
| `종목코드 6자리` (예: `005930`) | 해당 종목 즉시 수동 매수 |
| `sell` | 현재 보유 포지션 매도 선택 창 즉시 표시 |

### 설정 방법

1. BotFather에서 봇 2개 생성 → 각각 토큰 발급
2. `@userinfobot`으로 Chat ID 확인
3. 환경변수 등록 후 `python test_telegram.py`로 테스트

> **주의:** 같은 토큰으로 2개 프로세스가 polling하면 Conflict 오류 발생. 반드시 1개 프로세스만 실행.

---

## 백테스팅

### 유형

| 유형 | 데이터 | 용도 |
|------|--------|------|
| 일봉 (daily) | KIS API 일봉 | 장기 전략 검증, K값 최적화 |
| 분봉 단타 (intraday) | yfinance 분봉 | 단타 전략 검증, 파라미터 그리드 서치 |

### 분봉 데이터 제한

- 1분봉: 최근 7일 이내 (자동 감지)
- 5분봉: 최근 60일 이내 (자동 전환)

### 파라미터 그리드 서치

Streamlit 백테스팅 탭에서 K / 손절 / 트레일링 범위를 지정하면 모든 조합을 한 번에 계산합니다. 데이터는 캐시되어 재수집 없이 반복 실행 가능합니다.

> 그리드 서치는 `params` 딕셔너리로 격리되어 실시간 트레이딩 중에도 전역 파라미터를 오염시키지 않습니다.

---

## WatchDog 자동 재시작

### 구조 (3단계)

```
[레벨 1] watchdog.py (pythonw.exe — 창 없이 백그라운드 실행)
  또는   watchdog_hidden.vbs (wscript.exe — CMD 창 숨김)
  - Electron 앱이 종료되면 재시작
  - 장중(08:00~15:00): 10초 후 재시작
  - 장외 시간: 60초 대기 후 재시작
  - 로그: .cache/watchdog.log

[레벨 2] app.py 워치독 스레드
  - 트레이딩 스레드(scheduler)만 죽으면 재시작
  - Streamlit은 살아있지만 트레이딩이 멈춘 경우 처리

[레벨 3] trading_state.json (.cache/)
  - 비정상 종료 감지 플래그
  - F5 새로고침 / 정상 재부팅과 실제 비정상 종료 구분 (PID + 날짜 + tasklist 확인)
  - 재시작 시 텔레그램으로 모드 선택 요청
  - 3분 무응답 시 모의투자로 자동 진입
  - 2회 이상 복구 모드 진입 시 수동 진입 버튼 표시
```

### 정상 vs 비정상 종료

| 상황 | 종료 유형 | 재시작 알림 |
|------|-----------|-------------|
| 15:00 강제청산 후 자연 종료 | ✅ 정상 | ❌ |
| MAX_TRADES 도달 후 종료 | ✅ 정상 | ❌ |
| Streamlit 정지 버튼 | ✅ 정상 | ❌ |
| Ctrl+C | ✅ 정상 | ❌ |
| F5 새로고침 | ✅ 정상 (PID 동일 감지) | ❌ |
| 정상 재부팅 | ✅ 정상 (날짜 비교 감지) | ❌ |
| Python 프로세스 강제 Kill | 🚨 비정상 | ✅ |
| 처리 안 된 Exception | 🚨 비정상 | ✅ |
| PC 강제 재부팅 / 전원 차단 | 🚨 비정상 | ✅ |

### Windows 작업 스케줄러 등록 (자동화 권장)

**pythonw.exe 방식 (CMD 창 완전 숨김, 권장):**

```
프로그램: C:\KIS_Trader\1. Practice\kis_trader\venv\Scripts\pythonw.exe
인수:     "C:\KIS_Trader\1. Practice\kis_trader\watchdog.py"
시작위치: C:\KIS_Trader\1. Practice\kis_trader
트리거:   로그온 시, 지연 30초
```

PowerShell로 자동 등록:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\KIS_Trader\1. Practice\kis_trader\venv\Scripts\pythonw.exe" `
           -Argument """C:\KIS_Trader\1. Practice\kis_trader\watchdog.py""" `
           -WorkingDirectory "C:\KIS_Trader\1. Practice\kis_trader"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT30S"
Register-ScheduledTask -TaskName "KIS_AutoTrader_WatchDog" -Action $action -Trigger $trigger -Force
```

---

## 포지션 관리 고급 기능

### 매수 대기 슬롯 자동 교체

스크리닝 결과 새 후보의 점수가 현재 대기 중인 슬롯보다 **10점 이상** 높으면 자동 교체합니다.

- 대기 중(`bought=False`) 슬롯만 교체 대상
- 이미 매수된 포지션은 교체되지 않음
- 교체 시 텔레그램 알림 전송

### 매수 대기 1시간 타임아웃

목표가에 도달하지 못해 1시간 이상 대기 중인 슬롯은 자동 반환됩니다.

### HTS 수동 매수 자동 인식

스크리닝 주기마다 KIS 잔고를 조회하여, 트레이더가 모르는 보유 종목(HTS에서 직접 매수한 종목)을 감지하면 자동으로 모니터링 슬롯에 추가합니다. 손절/트레일링 스탑이 자동 적용됩니다.

### 최대주문가능수량 자동 보정

매수 진입 시 KIS API(`TTTC8908R`)로 실제 최대주문가능수량을 조회하여, 예산 기반 수량과 비교 후 작은 값으로 자동 보정합니다.  
`주문가능금액 초과` 오류 발생 시에도 재조회하여 수량을 줄여 재시도합니다.

---

## PC 이전 체크리스트

| 항목 | 방법 | 필수 |
|------|------|------|
| Python 3.11+ 설치 | python.org | ✅ |
| Node.js 설치 | nodejs.org | ✅ (Electron 사용 시) |
| 가상환경 + 패키지 | `pip install -r requirements.txt` | ✅ |
| Electron 패키지 | `cd electron && npm install` | ✅ (Electron 사용 시) |
| 환경변수 12개 | `sysdm.cpl` 등록 | ✅ |
| 코드 이전 | `git clone` 또는 폴더 복사 | ✅ |
| KIS API 등록 IP | Open API 포털에서 새 IP 추가 | ✅ |
| DART 기업코드 | `download_corp_codes()` 1회 실행 | DART 사용 시 |
| 작업 스케줄러 등록 | PowerShell 명령 또는 taskschd.msc | WatchDog 사용 시 |
| 텔레그램 봇 | 기존 PC 종료 후 시작 (중복 금지) | 텔레그램 사용 시 |

> **KIS API IP 등록:** 새 네트워크에서 실행하면 공인 IP가 달라져 API 호출이 막힙니다.  
> `https://www.whatismyip.com`에서 공인 IP 확인 후 KIS Open API 포털에서 추가하세요.

---

## 주의사항

- 모의투자와 실전투자는 API Key와 계좌번호가 다릅니다. 사이드바 모드 전환 시 즉시 키가 교체됩니다.
- Streamlit 브라우저 탭을 닫아도 서버(cmd)는 계속 실행됩니다. Electron 앱의 X 버튼으로 종료하세요.
- 같은 봇 토큰으로 2개 프로세스가 실행되면 Telegram Conflict 오류 발생 → 반드시 1개 프로세스만 실행.
- API Rate Limit: `CHECK_INTERVAL`(기본 20초)을 너무 짧게 설정하지 마세요.
- 백테스팅 결과는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
- Desktop 절전 모드 비활성화 필수 — 절전 시 API 호출 중단됩니다.
- API 키는 반드시 Windows 환경변수로만 관리하고 `.env` 파일에 저장하지 마세요.

### .gitignore 필수 항목

```
venv/
.cache/
scoring/cache/
trading_logs/
backtest/logs/
__pycache__/
*.pyc
token_cache.json
.env
```
