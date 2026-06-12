"""
1분봉 데이터 캐시 수집 및 누적 관리

저장 구조:
  backtest/cache/1min/YYYYMMDD/005930.csv   ← 종목별 분봉 CSV
  backtest/cache/1min/manifest.json         ← 수집 날짜 목록

사용법:
  from backtest.data_cache import collect_and_cache, load_minute_data_from_cache
"""
import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

CACHE_ROOT = Path(__file__).parent / "cache" / "1min"
MANIFEST   = CACHE_ROOT / "manifest.json"


# ── 퍼블릭 API ──────────────────────────────────────────────────

def collect_and_cache(stock_list, progress_cb=None) -> dict:
    """
    yfinance로 최근 7일치 1분봉 수집 → CSV 저장.
    이미 수집된 날짜는 스킵 (manifest 기준).

    stock_list : [{"code", "name"}, ...]
    progress_cb: (current, total, msg) → None
    반환       : {"new_dates": [...], "skipped_dates": [...], "error_codes": [...]}
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance 미설치: pip install yfinance")

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    manifest       = _load_manifest()
    existing_dates = {b["date"] for b in manifest.get("batches", [])}

    end_dt      = datetime.now()
    start_dt    = end_dt - timedelta(days=7)
    fetch_start = start_dt.strftime("%Y-%m-%d")
    fetch_end   = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    total  = len(stock_list)
    raw    = {}   # {date: {code: [bars]}}
    errors = []

    for i, stock in enumerate(stock_list):
        code = stock["code"]
        name = stock["name"]
        if progress_cb:
            progress_cb(i + 1, total, f"{name} ({code}) 수집 중…")

        bars_by_date = _fetch_bars(yf, code, fetch_start, fetch_end)
        if bars_by_date is None:
            errors.append(code)
        else:
            for d, bars in bars_by_date.items():
                raw.setdefault(d, {})[code] = bars

        time.sleep(0.05)

    if progress_cb:
        progress_cb(total, total, "CSV 저장 중…")

    new_dates     = []
    skipped_dates = []

    for date in sorted(raw.keys()):
        if date in existing_dates:
            skipped_dates.append(date)
            continue

        date_dir = CACHE_ROOT / date
        date_dir.mkdir(parents=True, exist_ok=True)

        saved = 0
        for code, bars in raw[date].items():
            bars.sort(key=lambda b: b["time"])
            with open(date_dir / f"{code}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time", "open", "high", "low", "close", "volume"])
                for b in bars:
                    w.writerow([b["time"], b["open"], b["high"],
                                b["low"],  b["close"], b["volume"]])
            saved += 1

        if saved > 0:
            new_dates.append(date)
            manifest.setdefault("batches", []).append({
                "date":         date,
                "stocks":       saved,
                "collected_at": datetime.now().isoformat(),
            })

    _save_manifest(manifest)
    return {"new_dates": new_dates, "skipped_dates": skipped_dates, "error_codes": errors}


def load_manifest() -> dict:
    """manifest.json 반환. 없으면 빈 구조."""
    return _load_manifest()


def load_cached_dates() -> list:
    """수집된 날짜 목록 반환 (오름차순)."""
    return sorted(b["date"] for b in _load_manifest().get("batches", []))


def load_minute_data_from_cache(dates: list, codes=None) -> dict:
    """
    캐시 CSV에서 분봉 데이터 로드.

    dates : ["YYYYMMDD", ...]  (없는 날짜는 자동 스킵)
    codes : None이면 전체 종목, list/set이면 해당 코드만
    반환  : {date: {code: [bars]}}  (engine_multi_intraday 형식)
    """
    code_filter = set(codes) if codes is not None else None
    result = {}

    for date in dates:
        date_dir = CACHE_ROOT / date
        if not date_dir.exists():
            continue

        code_bars = {}
        for csv_path in sorted(date_dir.glob("*.csv")):
            code = csv_path.stem
            if code_filter is not None and code not in code_filter:
                continue
            bars = []
            with open(csv_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    bars.append({
                        "time":   row["time"],
                        "open":   int(row["open"]),
                        "high":   int(row["high"]),
                        "low":    int(row["low"]),
                        "close":  int(row["close"]),
                        "volume": int(row["volume"]),
                    })
            if bars:
                code_bars[code] = bars

        if code_bars:
            result[date] = code_bars

    return result


def delete_cached_date(date: str) -> bool:
    """특정 날짜 캐시 삭제 (폴더 + manifest). 반환: 성공 여부."""
    import shutil
    date_dir = CACHE_ROOT / date
    if not date_dir.exists():
        return False
    shutil.rmtree(date_dir)
    manifest = _load_manifest()
    manifest["batches"] = [b for b in manifest.get("batches", []) if b["date"] != date]
    _save_manifest(manifest)
    return True


# ── 내부 함수 ───────────────────────────────────────────────────

def _fetch_bars(yf, code: str, fetch_start: str, fetch_end: str) -> dict | None:
    """
    단일 종목의 날짜별 1분봉 수집.
    .KS(코스피) 실패 시 .KQ(코스닥) 재시도.
    반환: {date: [bars]} 또는 None(두 suffix 모두 실패)
    """
    for suffix in (".KS", ".KQ"):
        try:
            df = yf.Ticker(f"{code}{suffix}").history(
                start=fetch_start, end=fetch_end,
                interval="1m", auto_adjust=True,
            )
            if df.empty:
                continue

            by_date = {}
            for ts, row in df.iterrows():
                lts = ts.tz_convert("Asia/Seoul") if ts.tzinfo else ts
                d   = lts.strftime("%Y%m%d")
                t   = lts.strftime("%H%M%S")
                by_date.setdefault(d, []).append({
                    "time":   t,
                    "open":   int(row["Open"]),
                    "high":   int(row["High"]),
                    "low":    int(row["Low"]),
                    "close":  int(row["Close"]),
                    "volume": int(row["Volume"]),
                })
            if by_date:
                return by_date
        except Exception:
            pass
    return None


def _load_manifest() -> dict:
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {"batches": []}


def _save_manifest(m: dict):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
