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


def fetch_multi_minute_bars_range_yf(stock_list, start_date, end_date,
                                      interval=None, progress_cb=None):
    """
    날짜 범위의 다종목 분봉 수집 (yfinance).
    interval 미지정 시 날짜 범위에 따라 자동 선택:
      - 7일 이내 → 1m, 60일 이내 → 5m, 초과 → ValueError

    반환: {date: {code: [bars]}}   (date = "YYYYMMDD", time = "HHMMSS")
    """
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt   = datetime.strptime(end_date,   "%Y%m%d")
    days_ago = (datetime.now() - start_dt).days

    if interval is None:
        if days_ago <= 7:
            interval = "1m"
        elif days_ago <= 60:
            interval = "5m"
        else:
            raise ValueError(
                f"{start_date}는 60일 초과({days_ago}일 전) — yfinance 분봉 범위 초과"
            )

    total  = len(stock_list)
    result = {}   # {date: {code: [bars]}}

    print(f"\n  분봉 범위 수집 [yfinance / {interval}]: {total}개 종목  "
          f"{start_date}~{end_date}")

    # yfinance end는 exclusive이므로 +1일
    fetch_end = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    fetch_start = start_dt.strftime("%Y-%m-%d")

    for i, stock in enumerate(stock_list):
        code = stock["code"]
        name = stock["name"]
        print(f"  [{i+1:>3}/{total}] {name} ({code}) ...", end="\r")
        if progress_cb:
            progress_cb(i + 1, total, name)
        try:
            ticker = yf.Ticker(f"{code}.KS")
            df = ticker.history(
                start=fetch_start,
                end=fetch_end,
                interval=interval,
                auto_adjust=True,
            )
            if df.empty:
                time.sleep(0.1)
                continue
            for ts, row in df.iterrows():
                local_ts = ts.tz_convert("Asia/Seoul") if ts.tzinfo else ts
                bar_date = local_ts.strftime("%Y%m%d")
                bar_time = local_ts.strftime("%H%M%S")
                if bar_date not in result:
                    result[bar_date] = {}
                if code not in result[bar_date]:
                    result[bar_date][code] = []
                result[bar_date][code].append({
                    "time":   bar_time,
                    "open":   int(row["Open"]),
                    "high":   int(row["High"]),
                    "low":    int(row["Low"]),
                    "close":  int(row["Close"]),
                    "volume": int(row["Volume"]),
                })
        except Exception as e:
            if i == 0:
                print(f"\n  [오류] {name}: {e}")
        time.sleep(0.1)

    # 각 코드별 bars를 시간순 정렬
    for date_data in result.values():
        for bars in date_data.values():
            bars.sort(key=lambda b: b["time"])

    dates_found = sorted(result.keys())
    stocks_found = len({c for d in result.values() for c in d})
    print(f"\n  수집 완료: {len(dates_found)}일 / {stocks_found}개 종목  "
          f"(간격: {interval})  날짜: {dates_found}")
    return result


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


def fetch_multi_ohlcv_yf(stock_list, start_date, end_date, progress_cb=None) -> dict:
    """
    yfinance로 다종목 일봉 OHLCV 수집 (KIS API 불필요).
    data_loader.fetch_multi_ohlcv 와 동일한 반환 형식.

    stock_list : [{"code", "name"}, ...]
    start_date : "YYYYMMDD"
    end_date   : "YYYYMMDD"
    반환       : {code: {date: {"date","open","high","low","close","volume"}}}
    """
    start_dt  = datetime.strptime(start_date, "%Y%m%d")
    end_dt    = datetime.strptime(end_date,   "%Y%m%d")
    fetch_end = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")   # yfinance end는 exclusive

    total  = len(stock_list)
    result = {}

    print(f"\n  일봉 수집 [yfinance]: {total}개 종목  {start_date}~{end_date}")

    for i, stock in enumerate(stock_list):
        code = stock["code"]
        name = stock["name"]
        print(f"  [{i+1:>3}/{total}] {name} ({code}) ...", end="\r")
        if progress_cb:
            progress_cb(i + 1, total, name)

        for suffix in (".KS", ".KQ"):
            try:
                df = yf.Ticker(f"{code}{suffix}").history(
                    start=start_dt.strftime("%Y-%m-%d"),
                    end=fetch_end,
                    interval="1d",
                    auto_adjust=True,
                )
                if df.empty:
                    continue

                rows = {}
                for ts, row in df.iterrows():
                    lts = ts.tz_convert("Asia/Seoul") if ts.tzinfo else ts
                    d   = lts.strftime("%Y%m%d")
                    if d < start_date or d > end_date:
                        continue
                    rows[d] = {
                        "date":   d,
                        "open":   int(row["Open"]),
                        "high":   int(row["High"]),
                        "low":    int(row["Low"]),
                        "close":  int(row["Close"]),
                        "volume": int(row["Volume"]),
                    }
                if rows:
                    result[code] = rows
                    break
            except Exception:
                pass
        time.sleep(0.05)

    stocks_found = len(result)
    print(f"\n  일봉 수집 완료: {stocks_found}/{total}개 성공")
    return result
