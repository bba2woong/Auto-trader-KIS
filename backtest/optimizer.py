"""
백테스트 베이지안 최적화 (optuna)

샤프 비율 최대화를 목표로 트레이딩 + Scorer 파라미터를 자동 탐색.
전역 strategy_config/scorer 수정 없음 — params dict로 완전 격리.

설치: pip install optuna
"""
try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import strategy_config as sc
from backtest.report import calc_sharpe


# ── 퍼블릭 API ──────────────────────────────────────────────────

def run_bayesian_optimization(
    minute_data, daily_data, stock_list, date,
    initial_capital, param_bounds, n_trials=50,
    progress_cb=None,
):
    """
    분봉 기반 단타 백테스트에 베이지안 최적화 적용.

    minute_data  : {code: {date: [minute_bars]}}
    daily_data   : {code: {date: ohlcv_row}}
    stock_list   : [{"code","name"}, ...]
    date         : "YYYYMMDD" (단일 날짜 또는 기간 → engine_intraday 형식에 맞춤)
    param_bounds : {param_name: (min, max), ...}
    progress_cb  : 선택적 콜백 f(trial_no, n_trials, sharpe) — 진행상황 UI 업데이트용
    반환         : {"study", "best_params", "best_sharpe", "best_trial",
                    "n_trials", "all_trials"}
    """
    _require_optuna()
    from backtest.engine_intraday import run_intraday_backtest

    def objective(trial):
        params = _suggest_params(trial, param_bounds)
        result = run_intraday_backtest(
            minute_data, daily_data, stock_list, date, initial_capital, params=params
        )
        sharpe = calc_sharpe(result)
        if progress_cb:
            progress_cb(trial.number + 1, n_trials, sharpe)
        return sharpe

    study = _new_study()
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return _study_to_result(study)


def run_bayesian_optimization_multi(
    minute_data_by_date, daily_data, stock_list,
    initial_capital, param_bounds, n_trials=50,
    progress_cb=None,
):
    """
    분봉 기반 다중 날짜 단타 백테스트에 베이지안 최적화 적용.

    minute_data_by_date : {date: {code: [bars]}}
    daily_data          : {code: {date: ohlcv_row}}
    param_bounds        : {param_name: (min, max), ...}
    반환                : {"study","best_params","best_sharpe","best_trial",
                           "n_trials","all_trials"}
    """
    _require_optuna()
    from backtest.engine_multi_intraday import run_multi_intraday_backtest

    def objective(trial):
        params = _suggest_params(trial, param_bounds)
        result = run_multi_intraday_backtest(
            minute_data_by_date, daily_data, stock_list, initial_capital, params
        )
        sharpe = calc_sharpe(result)
        if progress_cb:
            progress_cb(trial.number + 1, n_trials, sharpe)
        return sharpe

    study = _new_study()
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return _study_to_result(study)


def run_bayesian_optimization_daily(
    all_data, stock_list, start_date, end_date,
    initial_capital, param_bounds, n_trials=50,
    progress_cb=None,
):
    """
    일봉 기반 백테스트에 베이지안 최적화 적용.

    all_data     : {code: {date: ohlcv_row}}
    param_bounds : {param_name: (min, max), ...}
    progress_cb  : 선택적 콜백 f(trial_no, n_trials, sharpe)
    반환         : {"study", "best_params", "best_sharpe", "best_trial",
                    "n_trials", "all_trials"}
    """
    _require_optuna()
    from backtest.engine import run_backtest

    def objective(trial):
        params = _suggest_params(trial, param_bounds)
        result = run_backtest(all_data, stock_list, start_date, end_date, initial_capital, params)
        sharpe = calc_sharpe(result)
        if progress_cb:
            progress_cb(trial.number + 1, n_trials, sharpe)
        return sharpe

    study = _new_study()
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return _study_to_result(study)


# ── 내부 함수 ───────────────────────────────────────────────────

_INT_PARAMS = frozenset({
    "SCORE_BREAKOUT_MAX", "SCORE_AD_LINE", "SCORE_CANDLE",
    "SCORE_STRONG_BULL", "SCORE_WATCHLIST",
    "LLM_FIXED", "DART_FIXED", "MIN_SCORE",
    "MAX_TRADES_PER_DAY",
})


def _suggest_params(trial, param_bounds: dict) -> dict:
    """optuna trial에서 param_bounds 기반 파라미터 샘플링."""
    params = {}
    for name, (lo, hi) in param_bounds.items():
        if name in _INT_PARAMS:
            params[name] = trial.suggest_int(name, int(lo), int(hi))
        else:
            params[name] = trial.suggest_float(name, float(lo), float(hi))

    # sc 기본값으로 누락 파라미터 보충 (bounds에 없으면 고정값 사용)
    defaults = {
        "K":                           sc.K,
        "LOSS_RATE":                   sc.LOSS_RATE,
        "TRAILING_STOP_RATE":          sc.TRAILING_STOP_RATE,
        "TRAILING_STOP_ACTIVATE_RATE": sc.TRAILING_STOP_ACTIVATE_RATE,
        "USE_TRAILING_STOP":           sc.USE_TRAILING_STOP,
        "PROFIT_RATE":                 sc.PROFIT_RATE,
        "INVEST_RATIO":                sc.INVEST_RATIO,
        "MAX_TRADES_PER_DAY":          sc.MAX_TRADES_PER_DAY,
        "budget_per_position":         None,
        "SCORE_BREAKOUT_MAX":          40,
        "SCORE_AD_LINE":               15,
        "SCORE_CANDLE":                10,
        "SCORE_STRONG_BULL":           15,
        "SCORE_WATCHLIST":             10,
        "LLM_FIXED":                    5,
        "DART_FIXED":                   0,
        "MIN_SCORE":                   sc.CONFIRM_SCORE_MIN,
    }
    for k, v in defaults.items():
        if k not in params:
            params[k] = v
    return params


def _new_study():
    return optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )


def _study_to_result(study) -> dict:
    return {
        "study":       study,
        "best_params": study.best_params,
        "best_sharpe": study.best_value,
        "best_trial":  study.best_trial.number,
        "n_trials":    len(study.trials),
        "all_trials":  _trials_to_records(study),
    }


def _trials_to_records(study) -> list:
    rows = []
    for t in study.trials:
        row = {
            "trial":  t.number,
            "sharpe": round(t.value, 4) if t.value is not None else None,
        }
        row.update(t.params)
        rows.append(row)
    return rows


def _require_optuna():
    if not OPTUNA_AVAILABLE:
        raise ImportError(
            "optuna가 설치되지 않았습니다. "
            "터미널에서 `pip install optuna`를 실행하세요."
        )
