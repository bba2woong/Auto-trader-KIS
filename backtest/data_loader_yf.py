"""
yfinance 기반 분봉 데이터 수집
- 1분봉: 최근 7일 이내
- 5분봉: 최근 60일 이내

한국 종목 티커: 종목코드 + ".KS"  (예: 005930 → 005930.KS)
"""
import time
from datetime import datetime, timedelta

try:
    import yfinance as yf
except ImportError:
    raise ImportError("yfinance 미설치. 다음 명령 실행: pip install yfinance")


def fetch_minute_bars_yf(stock_code, date, interval="1m"):
    """
    yfinance로 특정 날짜의 분봉 수집
    stock_code : KIS 종목코드 (예: "005930")
    date       : "YYYYMMDD"
    interval   : "1m"(7일 이내) / "5m"(60일 이내)
    반환       : (actual_date, [{"time","open","high","low","close","volume"}, ...])
                 time 형식 = "HHMMSS"
    """
    ticker = yf.Ticker(f"{stock_code}.KS")

    # 하루치 = start ~ start+1일
    start = datetime.strptime(date, "%Y%m%d")
    end   = start + timedelta(days=1)

    df = ticker.history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval=interval,
        auto_adjust=True,
    )

    if df.empty:
        return date, []

    bars = []
    actual_date = None

    for ts, row in df.iterrows():
        # timezone-aware → KST
        local_ts = ts.tz_convert("Asia/Seoul") if ts.tzinfo else ts
        bar_date = local_ts.strftime("%Y%m%d")
        bar_time = local_ts.strftime("%H%M%S")

        if actual_date is None:
            actual_date = bar_date

        bars.append({
            "time":   bar_time,
            "open":   int(row["Open"]),
            "high":   int(row["High"]),
            "low":    int(row["Low"]),
            "close":  int(row["Close"]),
            "volume": int(row["Volume"]),
        })

    return actual_date or date, bars


def fetch_multi_minute_bars_yf(stock_list, date, interval="1m", progress_cb=None):
    """
    다종목 분봉 수집 (yfinance)
    progress_cb : (current, total, name) → None
    반환: (actual_date, {code: [bars]})
    """
    result      = {}
    total       = len(stock_list)
    success     = 0
    actual_date = date

    target = datetime.strptime(date, "%Y%m%d")
    days_ago = (datetime.now() - target).days
    if interval == "1m" and days_ago > 7:
        print(f"  ※ {date}는 7일 초과({days_ago}일 전) → 5분봉(1m 불가)으로 전환")
        interval = "5m"
    elif days_ago > 60:
        print(f"  ※ {date}는 60일 초과 → yfinance 분봉 지원 범위 초과")
        return date, {}

    print(f"\n  분봉 데이터 수집 [yfinance / {interval}]: {total}개 종목  날짜: {date}")

    for i, stock in enumerate(stock_list):
        code = stock["code"]
        name = stock["name"]
        print(f"  [{i+1:>3}/{total}] {name} ({code}) ...", end="\r")
        if progress_cb:
            progress_cb(i + 1, total, name)
        try:
            ret_date, bars = fetch_minute_bars_yf(code, date, interval)
            if bars:
                result[code] = bars
                success += 1
                if success == 1:
                    actual_date = ret_date
                    if actual_date != date:
                        print(f"\n  ※ {date} → 실제 거래일 {actual_date}로 보정")
        except Exception as e:
            if i == 0:
                print(f"\n  [오류] {name}: {e}")
        time.sleep(0.1)

    print(f"\n  수집 완료: {success}/{total}개 성공  (간격: {interval})")
    return actual_date, result
