<div align="center">

# 📈 KIS Auto Trader

**한국투자증권 Open API 기반 주식 자동매매 시스템**

변동성 돌파 전략 · AI 점수 기반 종목 선별 · 멀티포지션 실시간 모니터링

[![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.x-red?style=flat-square&logo=streamlit)](https://streamlit.io)
[![Electron](https://img.shields.io/badge/Electron-28-47848F?style=flat-square&logo=electron)](https://electronjs.org)
[![Version](https://img.shields.io/badge/Version-1.2-brightgreen?style=flat-square)]()
[![License](https://img.shields.io/badge/License-Personal-lightgrey?style=flat-square)]()

</div>

---

### 🚀 **KIS Auto Trader**
한국투자증권 Open API 기반 주식 자동매매 시스템 개발

**/with Claude Code & Perplexity & Open AI Codex**

개발 기간: 2026.04 ~ 현재  
기술 스택: Python · Streamlit · Electron · Telegram API · Perplexity AI · DART API · KIS API

핵심 성과:

✅ 래리 윌리엄스 변동성 돌파 전략 기반 자동매매 구현

✅ LLM AI + Dart 공시 + 차트 분석 점수 시스템으로 종목 선별 자동화

✅ 멀티쓰레드로 최대 N개 종목 동시 포지셔닝&모니터링

✅ Electron 데스크탑 앱 + WatchDog 자동 복구

✅ Telegram Bot 이용한 원격 트레이딩 지원, 원격 매수/매도 지시 및 자동 매매

✅ Setup.bat 패키징 + Git Clone 이용한 배포 서비스 탑재

✅ **v1.1** 베이지안 최적화 기반 백테스팅 시스템 — 1분봉 로컬 캐시 + optuna TPE 파라미터 자동 탐색

✅ **v1.2** LangGraph 파이프라인 모니터 — 조기종료(Early Exit) 게이트 + 트레이딩 탭 통합

🏆 실전/모의투자 실제 운용 경험 - 작성 시점까지 수익률 **xxx%**

---

## 📋 릴리즈 노트

### v1.2 — LangGraph 파이프라인 모니터 (2026-06-14)

> 스크리닝 250개 종목 전체를 7개 분석 노드로 처리할 때 API 호출 비용과 소요 시간이 과다했습니다.  
> LangGraph 조건부 엣지를 이용한 **조기종료(Early Exit)** 구조로 API 비용을 최소화하고,  
> 트레이딩 탭에서 상위 종목의 노드별 분석 결과를 실시간으로 시각화합니다.

#### 🆕 신규 기능

| 기능 | 설명 |
|------|------|
| **LangGraph 파이프라인** | 7개 분석 노드를 그래프 구조로 연결. 각 노드의 실행 상태·점수·소요시간을 실시간 카드로 표시 |
| **3단계 조기종료 게이트** | 저점수 종목은 외부 API 호출 전에 자동 SKIP — LLM/DART 비용 절감 |
| **트레이딩 탭 통합** | 별도 앱 없이 트레이딩 탭 내 컴팩트 1행 8열 카드 UI로 즉시 분석 가능 |
| **배점 단일 출처 관리** | `langgraph_monitor/score_config.py` 한 곳에서 모든 배점·임계값 관리 |

#### 🔬 LangGraph 파이프라인 상세

##### 왜 LangGraph를 선택했나

일반적인 순차 함수 호출은 모든 노드를 무조건 실행합니다. 변동성 점수가 낮아 이미 스킵이 확실한 종목에도 LLM API(Perplexity) 와 DART API를 호출하면 **불필요한 비용과 지연**이 발생합니다.

LangGraph의 `add_conditional_edges`는 각 노드 완료 후 **다음 노드로 갈지, 바로 집계 노드로 점프할지** 런타임에 결정합니다. 이로써:
- 저점수 종목은 외부 API 호출 없이 즉시 SKIP
- 고점수 종목만 LLM·DART 분석 진행
- 향후 실제 API 연결 시 **노드 함수만 교체**하면 파이프라인 구조 변경 불필요

##### 파이프라인 구조

```
[입력] 종목 코드
    │
    ▼
① 변동성 돌파   (max 40점)  ─── Gate 1: 점수 < 10 → ─────────────────────┐
    │ 통과                                                                    │
    ▼                                                                         │
② AD Line       (max 15점)  ─── Gate 2: 합산 < 15 → ────────────────────┐  │
    │ 통과                                                                 │  │
    ▼                                                                      │  │
③ 캔들 패턴     (max 10점)  ─ (항상 실행)                                │  │
    │                                                                      │  │
    ▼                                                                      │  │
④ 60분봉 강봉   (max 15점)  ─── Gate 3: 합산 < 25 → ─────────────────┐  │  │
    │ 통과 (여기서부터 외부 API)                                        │  │  │
    ▼                                                                   │  │  │
⑤ 뉴스 감성 LLM (max 10점)                                            │  │  │
    │                                                                   │  │  │
    ▼                                                                   │  │  │
⑥ DART 공시     (max 10점)                                            │  │  │
    │                                                                   │  │  │
    ▼                                                                   │  │  │
⑦ 관심종목 보너스(max 10점)                                           │  │  │
    │                                                                   │  │  │
    ▼                                                                   │  │  │
⑧ 스코어 집계   (총 110점) ◄──────────────────────────────────────────┘  │  │
    │                       ◄─────────────────────────────────────────────┘  │
    │                       ◄────────────────────────────────────────────────┘
    ▼
[출력] BUY (≥60점) / SKIP
```

##### 조기종료 게이트 기준

| 게이트 | 위치 | 조건 | 효과 |
|--------|------|------|------|
| **Gate 1** | 변동성 돌파 후 | 변동성 점수 < 10점 | AD Line ~ 관심종목 전부 건너뜀 |
| **Gate 2** | AD Line 후 | 변동성 + AD 합산 < 15점 | 캔들 ~ 관심종목 전부 건너뜀 |
| **Gate 3** | 60분봉 강봉 후 | 기술 4개 합산 < 25점 | **LLM·DART·관심종목 API 호출 없음** |

> Gate 3가 핵심입니다. 기술적 점수가 낮은 대다수 종목이 여기서 걸러져 **외부 API 호출 비용이 대폭 절감**됩니다.

##### UI 사용법

**트레이딩 탭에서 사용:**
1. 🚀 트레이딩 탭으로 이동
2. **스크리닝 상위 종목** 셀렉트박스에서 분석할 종목 선택  
   (스크리닝을 먼저 실행하면 상위 5개가 자동으로 채워짐)
3. **▶ 분석** 버튼 클릭
4. 8개 노드 카드가 순서대로 업데이트됨:
   - **초록 테두리**: 점수 ≥ max/3 (양호)
   - **빨간 테두리**: 점수 < max/3 (저조)
   - **⏭ 건너뜀**: 게이트 미달로 조기종료
5. 하단 배너에서 최종 **BUY / SKIP** 판단과 근거 확인

**배점·게이트 임계값 변경:**  
`langgraph_monitor/score_config.py` 파일 한 곳만 수정하면 노드 카드 UI, scoring_node 집계, 게이트 조건이 모두 자동 반영됩니다.

```python
# score_config.py 예시
SCORE_VOLATILITY_MAX = 40   # 변동성 돌파 최대 점수
VOLATILITY_GATE      = 10   # Gate 1 임계값
BUY_THRESHOLD        = 60   # BUY 판정 기준 (strategy_config.CONFIRM_SCORE_MIN 연동)
```

#### 🔄 변경 사항

| 항목 | 이전 (v1.1) | 이후 (v1.2) |
|------|------------|------------|
| 파이프라인 모니터 | 독립 Streamlit 앱 (`monitor_app.py`) | 트레이딩 탭 내 컴팩트 통합 |
| 탭 구성 | 스크리닝·트레이딩·백테스팅·매매로그·파라미터·**파이프라인모니터** 6개 | 파이프라인모니터 탭 제거 → 트레이딩 탭에 내장, 총 5개 탭 |
| 배점 관리 | 각 노드 파일에 하드코딩 | `score_config.py` 단일 출처 |
| 조기종료 | 없음 (전 노드 순차 실행) | 3단계 게이트 조건부 엣지 |
| screener.py 출력 | 이모지 포함 (`✅ ❌ ⚠️`) | 텍스트 레이블 (`[매수 후보] [제외] [경고]`) |

---

### v1.1 — 백테스팅 전면 개편 (2026-06-13)

> 단타 백테스트를 KIS API 의존 없이 완전히 자립적으로 운용할 수 있도록 전면 재설계했습니다.

#### 🆕 신규 기능

| 기능 | 설명 |
|------|------|
| **1분봉 로컬 캐시** | yfinance로 최근 7일치 1분봉 수집 → `backtest/cache/1min/YYYYMMDD/종목코드.csv` 로컬 저장 |
| **다중 날짜 백테스트** | 날짜 범위 선택 또는 개별 날짜 체크박스로 여러 날을 한 번에 백테스트 |
| **베이지안 최적화** | optuna TPE 샘플러로 샤프비율 최대화 파라미터를 자동 탐색 (n_trials 설정 가능) |
| **빠른 날짜 선택** | 최근 5일 / 10일 / 20일 / 전체 버튼으로 날짜 범위 즉시 설정 |
| **파라미터 프리셋** | 자주 쓰는 파라미터 조합을 이름으로 저장/불러오기/삭제 (`backtest_presets.json`) |
| **Scorer 배점 파라미터화** | 변동성돌파·AD·캔들·강봉·관심종목 배점을 UI에서 직접 조정 + 최적화 범위 설정 가능 |

#### 🔄 변경 사항

| 항목 | 이전 (v1.0) | 이후 (v1.1) |
|------|------------|------------|
| 백테스트 날짜 입력 | 단일 날짜 picker | 캐시 기반 다중 날짜 범위/개별 선택 |
| 일봉 데이터 수집 | KIS Open API | yfinance (KIS API 불필요) |
| 최적화 방식 | 그리드 서치만 지원 | 단일 실행 / 그리드 서치 / **베이지안 최적화** 3가지 |
| 백테스트 유형 | 일봉(daily) + 단타(intraday) | 단타 캐시 기반 단일 유형으로 통합 |
| 분봉 엔진 | 단일 날짜 `engine_intraday.py` | 다중 날짜 `engine_multi_intraday.py` (15:20 강제청산 · 일봉 근사 지원) |

#### 🐛 버그 수정

- 베이지안 최적화 결과 테이블 `ValueError` (샤프비율 컬럼 subset 중복) 수정
- `round(None)` 오류 수정 (파라미터 range 체크 시 단일값이 None인 케이스)
- KIS API `fetch_multi_ohlcv` 호출이 캐시 경로에도 남아있던 잔재 제거

---

### v1.0 — 초기 릴리즈 (2026-06-10)

- 변동성 돌파 전략 기반 자동매매 핵심 기능 구현
- AI 점수 시스템 (LLM + DART + 기술 점수 합산 최대 110점)
- 멀티포지션 독립 스레드 운용
- Telegram 선택봇 + 알람봇 연동
- WatchDog 2단계 자동 복구
- Electron 데스크탑 앱 패키징
- 일봉 + 분봉 단타 백테스팅 기초 구현

---

## 🛠 기술 스택

| 분류 | 기술 |
|------|------|
| **Backend** | Python 3.11 · Threading · KIS REST API |
| **Frontend** | Streamlit · Plotly · Electron |
| **AI / 데이터** | Perplexity sonar · DART Open API · yfinance |
| **최적화** | optuna (TPE 샘플러 · 베이지안 최적화) |
| **파이프라인** | LangGraph (StateGraph · 조건부 엣지 · 조기종료) |
| **알림** | Telegram Bot API (선택봇 + 알람봇 2개) |
| **인프라** | Windows Task Scheduler · WatchDog |
| **버전관리** | Git / GitHub |

---

## 🏗 시스템 아키텍처

![Architecture](assets/architecture.svg)

---

## 💹 매매 흐름도

![Trading Flow](assets/trading_flow.svg)

---

## 🤖 AI 점수 시스템

![Score System](assets/score_system.svg)

종목별 최대 110점 산출 후 점수 구간에 따라 자동 매수 / 텔레그램 확인 / 스킵으로 라우팅합니다.
해당 점수는 고정값이 아니며, Bayesian Optimization을 통해 Sharp Ratio 최고값에 해당하는 파라미터로 변경 필요
`scorer.py` 에서 Score 파라미터 변경 가능

| 구간 | 동작 |
|------|------|
| 90점 이상 | 🤖 텔레그램 확인 없이 자동 매수 |
| 60~89점 | 📱 텔레그램으로 선택 요청 (5분 타임아웃) |
| 60점 미만 | ⏭ 스킵 |

매수 방법 별 점수 구간 파라미터는 `strategy_config.py`에서 변경 가능

---

## ⚙️ 주요 기능

### 1. 자동 스크리닝
- KOSPI200 + KOSDAQ150 + 관심종목 대상 10분 주기 스크리닝
- 변동성 돌파 + AD Line + 캔들 패턴 + 60분봉 강세봉 조건 필터링
- AI 점수 산출 후 텔레그램으로 후보 목록 전송

### 2. 멀티포지션 모니터링
- 최대 5개 종목 동시 보유, 포지션별 독립 스레드 운용
- 매 20초마다 현재가 조회 → 트레일링 스탑 / 하드 손절 자동 실행
- HTS 수동 매수 종목도 잔고 감지 후 자동 모니터링 편입

### 3. WatchDog 자동 복구
```
[레벨 1] watchdog.bat    → Electron 앱 크래시 시 재시작
[레벨 2] Electron main.js → Streamlit 프로세스 크래시 시 재시작
[레벨 3] trading_state.json → 비정상 종료 감지 후 텔레그램으로 모드 선택 요청
```

### 4. 텔레그램 연동
- **선택봇**: 스크리닝 결과 인라인 버튼 전송 / 종목 멀티 선택 / 매도 종목 선택
- **알람봇**: 매수·매도 체결 알림 / 수익률 20분 주기 알림 / 스크리닝 결과 로그

### 5. 백테스팅 (v1.1 개편)

#### 워크플로우

```
[1단계] 1분봉 데이터 수집
  → '🔄 데이터 수집' 버튼 클릭
  → yfinance로 최근 7일치 1분봉 수집
  → backtest/cache/1min/YYYYMMDD/*.csv 저장
  → manifest.json으로 수집 이력 관리

[2단계] 백테스트 날짜 선택
  → 범위 선택: 시작일 ~ 종료일 + 빠른 선택 버튼 (최근 5/10/20일/전체)
  → 개별 선택: 날짜별 체크박스

[3단계] 파라미터 설정 및 최적화 방식 선택
  → 단일 실행: 지정 파라미터로 1회 실행
  → 그리드 서치: 파라미터 범위 설정 후 전 조합 탐색
  → 베이지안 최적화: optuna TPE로 샤프비율 최대화 파라미터 자동 탐색

[4단계] 결과 분석
  → 수익률 · 거래수 · 승률 · MDD · 샤프비율 요약
  → 날짜별 손익 차트 + 종목별 거래 상세 내역
```

#### 백테스트 엔진 시뮬레이션 로직

```
10:00 일괄 스크리닝 (변동성 돌파 + AD Line 상승 필터)
  → Scorer 점수 상위 N개 종목 동시 매수
  → 포지션별 독립 청산 조건 체크:
     - 하드 손절: 매수가 × (1 - LOSS_RATE)
     - 트레일링 스탑: 고점 × (1 - TRAILING_STOP_RATE) [고점 수익률 ≥ ACTIVATE_RATE 시 활성화]
     - 고정 익절: 매수가 × (1 + PROFIT_RATE)
     - 강제 청산: 15:20 종가
  → 분봉 데이터 없는 날짜: 일봉 고/저/종가로 근사 처리 (일봉근사 표기)
```

#### 파라미터 최적화 대상

| 카테고리 | 파라미터 | 범위 예시 |
|----------|----------|-----------|
| 트레이딩 | K값 (변동성 계수) | 0.3 ~ 0.7 |
| 트레이딩 | 손절률 (%) | 1.0 ~ 4.0 |
| 트레이딩 | 트레일링 스탑률 (%) | 1.0 ~ 4.0 |
| Scorer 배점 | 변동성돌파 최대점 | 20 ~ 60 |
| Scorer 배점 | AD Line 점수 | 5 ~ 25 |
| Scorer 배점 | 캔들패턴 점수 | 0 ~ 20 |
| Scorer 배점 | 강봉(60분) 점수 | 5 ~ 25 |
| Scorer 배점 | 관심종목 보너스 | 0 ~ 20 |

> 베이지안 최적화는 범위 체크된 파라미터만 탐색하고, 나머지는 UI 단일값으로 고정됩니다.  
> 모든 파라미터는 `params` 딕셔너리로 격리되어 실시간 트레이딩의 전역 설정(`strategy_config`)을 오염시키지 않습니다.

---

## 📂 프로젝트 구조

```
kis_trader/
├── app.py                        # Streamlit GUI (주 실행 파일)
├── main.py                       # CLI 진입점
├── config.py                     # API 키/URL 설정 (환경변수 기반)
├── auth.py                       # 토큰 발급 및 캐시
├── api.py                        # 잔고 조회
├── order.py                      # 매수/매도 주문
├── strategy.py                   # 목표가 계산, 손절/트레일링 로직
├── strategy_config.py            # 전략 파라미터 설정
├── screener.py                   # 실시간 종목 스크리닝
├── scheduler.py                  # 장중 매매 루프 (멀티포지션 스레드)
├── telegram_bot.py               # 텔레그램 알림 및 종목 선택 UI
├── trading_logger.py             # 매매 이벤트 JSONL 로그
├── watchlist.py                  # 관심종목 코드 목록
├── backtest_presets.json         # 백테스트 파라미터 프리셋 저장소 (v1.1)
│
├── scoring/
│   ├── scorer.py                 # 총점 계산 + 일별 캐시 관리 (최대 110점)
│   ├── llm_client.py             # Perplexity API 뉴스 분석
│   └── dart_client.py            # DART 공시 분석
│
├── langgraph_monitor/            # LangGraph 파이프라인 모니터 (v1.2 신규)
│   ├── score_config.py           # 배점 상수 단일 출처 (SSOT) — 변경 시 이 파일만 수정
│   ├── state.py                  # TradeState TypedDict (7개 노드 점수 + 실행시간 필드)
│   ├── nodes.py                  # 분석 노드 7개 + scoring_node (현재 Mock, 실제 API 교체 예정)
│   ├── graph.py                  # StateGraph 빌드 + 3단계 조건부 엣지 (조기종료)
│   ├── pipeline_monitor_tab.py   # app.py 탭용 render 함수 (전체·컴팩트 2종)
│   └── monitor_app.py            # 독립 실행용 Streamlit 앱 (참고용)
│
├── backtest/
│   ├── engine_multi_intraday.py  # 다중 날짜 단타 백테스트 엔진 (v1.1 신규)
│   │                             #   10:00 스크리닝 → 동시 매수 → 15:20 강제청산
│   ├── data_cache.py             # 1분봉 로컬 캐시 수집/관리 (v1.1 신규)
│   │                             #   yfinance → CSV → manifest.json
│   ├── optimizer.py              # 베이지안 최적화 (optuna TPE · 샤프비율 최대화) (v1.1)
│   ├── engine_intraday.py        # 단일 날짜 단타 엔진 (레거시)
│   ├── engine.py                 # 일봉 백테스트 엔진 (레거시)
│   ├── screener_sim.py           # 과거 데이터 스크리닝 시뮬레이션
│   ├── data_loader.py            # KIS API 일봉/분봉 수집 (실시간 트레이딩용)
│   ├── data_loader_yf.py         # yfinance 분봉/일봉 수집 (백테스팅 전용) (v1.1 확장)
│   ├── report.py                 # 백테스트 결과 계산 (샤프비율 등)
│   └── cache/                    # 1분봉 CSV 캐시 (git 제외)
│       └── 1min/
│           ├── manifest.json
│           └── YYYYMMDD/
│               └── 005930.csv
│
├── trading_logs/                 # 매매 로그 (YYYYMMDD.jsonl, git 제외)
├── scoring/cache/                # AI 점수 일별 캐시 (git 제외)
├── .cache/                       # 토큰 캐시 (git 제외)
└── .gitignore
```

---

## 🔧 기술적 도전과 해결

### 1. 멀티포지션 동시 모니터링
**문제:** 여러 종목을 동시에 실시간 감시하면서 서로 간섭하지 않아야 함

**해결:** `threading.Thread` 기반 포지션별 독립 스레드 설계. 각 스레드는 자체 `stop_event`로 제어되며 `threading.Lock()`으로 토큰 캐시 동시 접근 방지

### 2. 모의/실전 API 키 완전 분리
**문제:** 런타임에 모드를 전환할 때 잘못된 API 키가 사용될 위험

**해결:** `config.reload(mode)` 함수로 `sys.modules` 내 모듈 속성을 동적으로 교체. `st.session_state`로 Streamlit 세션별 격리

### 3. 백테스트 그리드 서치 중 전역 파라미터 오염
**문제:** 그리드 서치 시 `strategy_config` 전역 모듈을 수정하면 실시간 트레이딩에도 영향

**해결:** `params` 딕셔너리를 함수 인자로 전달하는 방식으로 전역 참조 제거. 백테스트와 실시간 트레이딩이 완전히 독립적으로 동작

### 4. 비정상 종료 자동 복구
**문제:** 장 중 크래시 시 포지션 모니터링이 중단되어 손절 타이밍을 놓칠 수 있음

**해결:** `trading_state.json`으로 실행 상태 영속화. WatchDog 2단계 구조로 10초 내 자동 재시작 + 텔레그램으로 재시작 모드 선택

### 5. 백테스팅 KIS API 의존 제거 (v1.1)
**문제:** yfinance로 1분봉을 수집했음에도 AD Line 계산용 일봉 데이터를 KIS API로 재수집하는 잔재 코드가 남아 있었음. API 인증 없이 백테스트를 독립적으로 실행할 수 없었음

**해결:** `fetch_multi_ohlcv_yf()` 함수 추가로 일봉 데이터도 yfinance에서 수집. 백테스팅 경로에서 `data_loader.fetch_multi_ohlcv`(KIS API) 호출을 완전히 제거

### 6. 베이지안 최적화 vs 그리드 서치 (v1.1)
**문제:** 파라미터가 8개 이상(K·손절·트레일링·Scorer 배점 5종)으로 늘어나면서 전수 그리드 서치가 수천 ~ 수만 조합으로 폭증

**해결:** optuna TPE(Tree-structured Parzen Estimator) 샘플러 도입. n_trials=50~200회 탐색으로 그리드 서치 대비 수십 배 빠르게 최적 파라미터를 수렴. 목적함수는 샤프비율(수익/변동성)로 과적합 방지

### 7. 스크리닝 250종목 전체 API 호출 비용 문제 (v1.2)
**문제:** LLM·DART API를 250개 종목 전부에 호출하면 비용 과다. 변동성 점수가 낮아 어차피 SKIP될 종목에도 외부 API가 낭비됨

**해결:** LangGraph `add_conditional_edges`로 3단계 게이트 구현. 기술적 점수(변동성·AD·캔들·강봉)가 임계값 미달이면 LLM·DART 호출 없이 즉시 scoring 노드로 점프. 실제 API 연결 시 노드 함수(`nodes.py`)만 교체하면 파이프라인 구조 변경 불필요

### 8. 배점 상수 분산 관리 문제 (v1.2)
**문제:** 노드 파일(`nodes.py`)과 UI 파일(`pipeline_monitor_tab.py`)에 max 점수·임계값이 각각 하드코딩되어 배점 변경 시 여러 파일을 동시에 수정해야 했음

**해결:** `langgraph_monitor/score_config.py`를 단일 출처(SSOT)로 분리. `BUY_THRESHOLD`는 `strategy_config.CONFIRM_SCORE_MIN`을 동적으로 읽어 전략 설정과 자동 연동됨

---

## 🖥 스크린샷

### 트레이딩 앱 화면

![Trading App Screen](assets/trading_app_screen.png)

### 텔레그램 봇 사용 예시

| 스크리닝 결과 | 매수 선택 | 매도 / 수익 알림 |
|:---:|:---:|:---:|
| ![Telegram Usecase 1](assets/telegram_app_usecase1.png) | ![Telegram Usecase 2](assets/telegram_app_usecase2.png) | ![Telegram Usecase 3](assets/telegram_app_usecase3.png) |

---

## 🚀 빠른 시작

### 요구사항
- Python 3.11.x
- Node.js 18+
- Git
- 한국투자증권 Open API 계정

### 사전 설치

#### 1. Python 3.11.9

> ⚠️ Python 3.12 이상은 일부 패키지와 호환되지 않을 수 있습니다. **반드시 3.11.x 버전을 설치하세요.**

[Python 3.11.9 다운로드 (Windows 64bit)](https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe)

설치 시 **"Add Python to PATH"** 옵션을 반드시 체크하세요.

설치 확인:
```bash
python --version
# Python 3.11.9
```

#### 2. Node.js

[Node.js LTS 다운로드](https://nodejs.org)

LTS 버전을 설치하세요. 설치 확인:
```bash
node --version
# v18.x.x 이상
```

#### 3. Git

[Git 다운로드](https://git-scm.com/download/win)

기본값으로 설치하세요. 설치 확인:
```bash
git --version
```

---

### 설치

```bash
git clone https://github.com/bba2woong/Auto-trader-KIS.git
cd Auto-trader-KIS
```

> ⚠️ **`setup.bat`은 반드시 관리자 권한으로 실행해야 합니다.**  
> 작업 스케줄러(WatchDog) 등록에 관리자 권한이 필요합니다.  
> `Win + R` → `cmd` 입력 → `Ctrl + Shift + Enter` (관리자 실행) → 아래 명령 실행

```bash
# 자동 설치 (venv 생성 + 패키지 설치 + Electron 의존성 + 작업 스케줄러 등록)
setup.bat
```

### 추가 패키지

```bash
pip install optuna        # v1.1 베이지안 최적화
pip install langgraph     # v1.2 파이프라인 모니터
```

### 환경변수 등록 (`sysdm.cpl` → 환경변수)

```
KIS_REAL_APP_KEY / KIS_REAL_APP_SECRET / KIS_REAL_ACCOUNT
KIS_MOCK_APP_KEY / KIS_MOCK_APP_SECRET / KIS_MOCK_ACCOUNT
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
TELEGRAM_ALARM_BOT_TOKEN / TELEGRAM_ALARM_CHAT_ID
PERPLEXITY_API_KEY (선택)
DART_API_KEY (선택)
```

> 백테스팅은 KIS API 인증 없이 yfinance만으로 동작합니다.

## 실행

### 방법 1 — Electron 앱 실행 (권장)
`KIS Auto Trader.exe` 더블클릭

부팅 시 자동 시작 등록:
Windows 작업 스케줄러에 등록되어 있어 PC 시작 후 30초 내 자동 실행됩니다.

### 방법 2 — WatchDog 포함 실행 (장 중 안정성 강화)
watchdog.bat 더블클릭
(Electron/Streamlit 크래시 시 10초 내 자동 재시작)

---

## 📋 전략 파라미터

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `K` | 0.4 | 변동성 계수 (권장: 0.3~0.7) |
| `LOSS_RATE` | 2.3% | 하드 손절 기준 |
| `TRAILING_STOP_RATE` | 3.0% | 고점 대비 트레일링 스탑 |
| `TRAILING_STOP_ACTIVATE_RATE` | 4.0% | 트레일링 스탑 활성화 최소 수익률 |
| `MAX_POSITIONS` | 5 | 동시 보유 최대 포지션 수 |
| `AUTO_BUY_SCORE` | 90 | 자동 매수 기준 점수 |

---

## ⚠️ 주의사항

- 이 소프트웨어는 개인 학습 목적으로 제작되었습니다
- 실전 투자 손실에 대한 책임은 사용자 본인에게 있습니다
- 백테스팅 결과는 미래 수익을 보장하지 않습니다
- KIS Open API 이용약관을 준수하여 사용하세요
- yfinance 1분봉은 최근 7일 이내 데이터만 제공됩니다. 캐시 수집 후 7일이 지난 날짜는 신규 수집이 불가합니다

---

## 📝 회고

### 아쉬운 점 / 개선 목표

**전역 모듈 리팩토링**  
현재 전역 모듈 의존 구조는 테스트와 확장에 한계가 있습니다. 별도 개발 버전을 구성해 의존성 주입 방식으로 단계적 리팩토링 후 버전업 릴리즈할 계획입니다.

**백테스트 통계 유의성 부족**  
아직 실전 거래 횟수가 충분하지 않아 백테스트 결과의 통계적 신뢰도가 낮습니다. 데이터가 누적되는 시점에 전략 파라미터 전면 재검토를 진행할 예정입니다.

**LangGraph 실제 API 연결 (v1.3 목표)**  
v1.2의 파이프라인 노드는 Mock 데이터 기반입니다. `langgraph_monitor/nodes.py`의 각 노드 함수에서 `time.sleep + random` 부분을 실제 screener·scorer 함수로 교체하면 파이프라인 구조 변경 없이 실 데이터 분석이 가능합니다. 조기종료 게이트 임계값은 실전 운용 데이터를 쌓은 후 정밀 튜닝할 예정입니다.

**AI 기반 파라미터 자동 최적화 (v1.3 목표)**  
v1.1에서 베이지안 최적화를 도입했지만, 아직은 User-Driven(사람이 범위 설정)입니다. 추후 당일 거래 데이터를 기반으로 AI가 최적 파라미터를 자동 도출하고 백테스트까지 실행하는 AI-Driven Optimization 구조로 발전시키는 것이 목표입니다.

---

<div align="center">
<sub>Made with Python · Streamlit · Electron · optuna · LangGraph</sub>
</div>
