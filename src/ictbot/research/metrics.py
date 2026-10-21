"""Performance statistics on daily net return series.

"Average monthly return" is reported as the GEOMETRIC mean of calendar-month
returns (what actually compounds), alongside the arithmetic mean.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

TRADING_DAYS = 252


def equity_curve(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod()


def max_drawdown(returns: pd.Series) -> float:
    eq = equity_curve(returns)
    if eq.empty:
        return 0.0
    return float((1.0 - eq / eq.cummax()).max())


def monthly_returns(returns: pd.Series) -> pd.Series:
    if returns.empty:
        return returns
    return (1.0 + returns.fillna(0.0)).resample("ME").prod() - 1.0


def sharpe(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def sortino(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    downside = np.sqrt(np.mean(np.minimum(r.to_numpy(), 0.0) ** 2))
    return float(r.mean() / downside * math.sqrt(periods)) if downside > 0 else 0.0


def probabilistic_sharpe(returns: pd.Series, sr_benchmark: float = 0.0) -> float:
    """PSR (Bailey & Lopez de Prado): P(true per-period SR > benchmark)."""
    r = returns.dropna()
    n = len(r)
    if n < 10 or r.std(ddof=1) == 0:
        return 0.5
    sr = r.mean() / r.std(ddof=1)
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return float(stats.norm.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom))


def periods_per_year(returns: pd.Series) -> float:
    """Observed sampling frequency (252 for stocks, ~365 for crypto)."""
    r = returns.dropna()
    if len(r) < 3:
        return float(TRADING_DAYS)
    span = (r.index[-1] - r.index[0]).days / 365.25
    return float(len(r) / span) if span > 0 else float(TRADING_DAYS)


def summarize(returns: pd.Series, exposure: pd.Series | None = None, turnover: pd.Series | None = None, n_trades: int | None = None, costs: pd.Series | None = None) -> dict:
    r = returns.dropna()
    if r.empty:
        return {"days": 0}
    eq = equity_curve(r)
    ppy = periods_per_year(r)
    years = len(r) / ppy
    total = float(eq.iloc[-1] - 1.0)
    cagr = float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 and eq.iloc[-1] > 0 else -1.0
    m = monthly_returns(r)
    geo_m = float((1 + m).prod() ** (1 / len(m)) - 1) if len(m) and (1 + m).prod() > 0 else -1.0
    mdd = max_drawdown(r)
    out = {
        "days": int(len(r)),
        "start": str(r.index[0].date()),
        "end": str(r.index[-1].date()),
        "total_return": total,
        "cagr": cagr,
        "monthly_geo_mean": geo_m,
        "monthly_arith_mean": float(m.mean()) if len(m) else 0.0,
        "pct_positive_months": float((m > 0).mean()) if len(m) else 0.0,
        "best_month": float(m.max()) if len(m) else 0.0,
        "worst_month": float(m.min()) if len(m) else 0.0,
        "ann_vol": float(r.std(ddof=1) * math.sqrt(ppy)),
        "sharpe": sharpe(r, int(round(ppy))),
        "sortino": sortino(r, int(round(ppy))),
        "max_drawdown": mdd,
        "calmar": float(cagr / mdd) if mdd > 0 else 0.0,
        "psr_0": probabilistic_sharpe(r),
        "t_stat_mean": float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))) if r.std(ddof=1) > 0 else 0.0,
        "skew": float(stats.skew(r)),
        "excess_kurtosis": float(stats.kurtosis(r)),
        "hit_rate_days": float((r[r != 0] > 0).mean()) if (r != 0).any() else 0.0,
    }
    if exposure is not None and len(exposure):
        e = exposure.reindex(r.index).fillna(0)
        out["avg_gross_exposure"] = float(e.mean())
        out["time_in_market"] = float((e > 1e-9).mean())
    if turnover is not None and len(turnover):
        out["annual_turnover"] = float(turnover.reindex(r.index).fillna(0).sum() / years) if years else 0.0
    if costs is not None and len(costs):
        out["annual_cost_drag"] = float(costs.reindex(r.index).fillna(0).sum() / years) if years else 0.0
    if n_trades is not None:
        out["n_trades"] = int(n_trades)
    return out
