"""Validation toolkit: everything needed to avoid fooling ourselves.

* chronological TRAIN / VALIDATION / TEST splits (test is locked by the runner)
* walk-forward: re-select parameters on a trailing window, evaluate the next block
* parameter sensitivity / neighbourhood robustness
* Deflated Sharpe Ratio (multiple-testing adjustment, Bailey & Lopez de Prado 2014)
* Probability of Backtest Overfitting via CSCV (Bailey et al. 2017)
* stationary block bootstrap of returns (drawdown / ruin distributions)
* position-shift null test (is timing better than random timing with the same exposure?)
* regime breakdown (trend x volatility of SPY, lagged) and per-year results
* leverage analysis: what it would take to reach a monthly return target
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

from .metrics import TRADING_DAYS, max_drawdown, monthly_returns, sharpe

EULER_GAMMA = 0.5772156649


@dataclass(frozen=True)
class Splits:
    train: tuple[dt.date, dt.date]
    validation: tuple[dt.date, dt.date]
    test: tuple[dt.date, dt.date]

    @classmethod
    def default(cls, data_end: dt.date) -> "Splits":
        return cls(
            train=(dt.date(2016, 1, 1), dt.date(2021, 12, 31)),
            validation=(dt.date(2022, 1, 1), dt.date(2023, 12, 31)),
            test=(dt.date(2024, 1, 1), data_end),
        )

    @classmethod
    def adaptive(cls, first: dt.date, data_end: dt.date, train: float = 0.55, val: float = 0.20) -> "Splits":
        """Pre-registered rule for instruments with short histories (crypto):
        first 55% train, next 20% validation, last 25% test."""
        span = (data_end - first).days
        t_end = first + dt.timedelta(days=int(span * train))
        v_end = first + dt.timedelta(days=int(span * (train + val)))
        return cls(train=(first, t_end), validation=(t_end + dt.timedelta(days=1), v_end), test=(v_end + dt.timedelta(days=1), data_end))

    def as_dict(self) -> dict:
        return {k: [str(a), str(b)] for k, (a, b) in {"train": self.train, "validation": self.validation, "test": self.test}.items()}


def cut(series: pd.Series, start: dt.date, end: dt.date) -> pd.Series:
    return series[(series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))]


# --------------------------------------------------------------------------- #
# Multiple testing
# --------------------------------------------------------------------------- #


def deflated_sharpe(best_returns: pd.Series, trial_sharpes: list[float], n_trials: int | None = None,
                    periods: int = TRADING_DAYS) -> dict:
    """DSR = P(true SR > SR0) where SR0 is the expected max SR of ``n_trials``
    skill-less strategies. All Sharpes here are PER-PERIOD (daily), not annualized;
    ``periods`` (observations per year: 252 stocks, ~365 crypto) only scales sr0_annualized."""
    r = best_returns.dropna()
    n_obs = len(r)
    n = n_trials or len(trial_sharpes)
    if n_obs < 30 or r.std(ddof=1) == 0:
        return {"dsr": 0.0, "sr0_daily": None, "n_trials": n}
    sr = r.mean() / r.std(ddof=1)
    var_sr = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
    if n <= 1 or var_sr <= 0:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n)
        z2 = stats.norm.ppf(1 - 1.0 / (n * math.e))
        sr0 = math.sqrt(var_sr) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    dsr = float(stats.norm.cdf((sr - sr0) * math.sqrt(n_obs - 1) / denom))
    return {"dsr": dsr, "sr0_daily": sr0, "sr_daily": float(sr), "n_trials": n, "sr0_annualized": sr0 * math.sqrt(periods)}


def pbo_cscv(returns_matrix: pd.DataFrame, n_blocks: int = 16, max_combos: int = 4000, seed: int = 0) -> dict:
    """Probability of Backtest Overfitting via Combinatorially Symmetric CV.
    ``returns_matrix``: T x N daily returns, one column per parameter trial."""
    m = returns_matrix.dropna(how="all").fillna(0.0).to_numpy(float)
    t, n = m.shape
    if n < 2 or t < n_blocks * 5:
        return {"pbo": None, "reason": "too few trials or observations"}
    blocks = np.array_split(np.arange(t), n_blocks)
    s1 = np.array([m[b].sum(axis=0) for b in blocks])
    s2 = np.array([(m[b] ** 2).sum(axis=0) for b in blocks])
    cnt = np.array([len(b) for b in blocks], dtype=float)
    combos = list(itertools.combinations(range(n_blocks), n_blocks // 2))
    rng = np.random.default_rng(seed)
    if len(combos) > max_combos:
        combos = [combos[i] for i in rng.choice(len(combos), max_combos, replace=False)]
    logits = []
    for is_idx in combos:
        mask = np.zeros(n_blocks, dtype=bool)
        mask[list(is_idx)] = True

        def sr(sel):
            nn = cnt[sel].sum()
            mu = s1[sel].sum(axis=0) / nn
            var = s2[sel].sum(axis=0) / nn - mu ** 2
            return mu / np.sqrt(np.maximum(var, 1e-18))

        is_sr, oos_sr = sr(mask), sr(~mask)
        best = int(np.argmax(is_sr))
        rank = stats.rankdata(oos_sr)[best] / (n + 1)
        logits.append(math.log(rank / (1 - rank)))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "median_logit": float(np.median(logits)), "n_combos": len(logits), "n_trials": n}


# --------------------------------------------------------------------------- #
# Walk-forward
# --------------------------------------------------------------------------- #


def walk_forward(
    trial_returns: dict[str, pd.Series],
    start: dt.date,
    end: dt.date,
    train_years: int = 3,
    step_months: int = 6,
    objective: Callable[[pd.Series], float] = sharpe,
) -> dict:
    """Trials must be pre-computed causal return series (one per parameter set).
    At each step choose the best trial on the trailing ``train_years`` window and
    take ITS returns for the next ``step_months``. Returns the stitched OOS series."""
    keys = list(trial_returns)
    frame = pd.DataFrame(trial_returns)
    cursor = pd.Timestamp(start) + pd.DateOffset(years=train_years)
    stop = pd.Timestamp(end)
    pieces, choices = [], []
    while cursor < stop:
        nxt = min(cursor + pd.DateOffset(months=step_months), stop + pd.Timedelta(days=1))
        win = frame[(frame.index >= cursor - pd.DateOffset(years=train_years)) & (frame.index < cursor)]
        scores = {k: objective(win[k]) for k in keys}
        best = max(scores, key=scores.get)
        oos = frame[(frame.index >= cursor) & (frame.index < nxt)][best]
        pieces.append(oos)
        choices.append({"from": str(cursor.date()), "to": str((nxt - pd.Timedelta(days=1)).date()), "chosen": best, "is_score": scores[best]})
        cursor = nxt
    oos = pd.concat(pieces) if pieces else pd.Series(dtype=float)
    stability = pd.Series([c["chosen"] for c in choices]).value_counts(normalize=True).iloc[0] if choices else 0.0
    return {"oos_returns": oos, "choices": choices, "most_common_choice_share": float(stability)}


# --------------------------------------------------------------------------- #
# Sensitivity
# --------------------------------------------------------------------------- #


def sensitivity(trials: list[dict], scores: list[float], param_grid: dict[str, list]) -> dict:
    """Marginal mean score per parameter value + neighbourhood robustness of the best trial:
    median score of trials differing from the best in exactly one parameter by one grid step."""
    df = pd.DataFrame(trials)
    df["score"] = scores
    marginal = {p: df.groupby(p)["score"].mean().round(4).to_dict() for p in param_grid if len(param_grid[p]) > 1}
    best_i = int(np.nanargmax(scores))
    best = trials[best_i]
    neigh = []
    for i, tr in enumerate(trials):
        diffs = [p for p in param_grid if tr[p] != best[p]]
        if len(diffs) != 1:
            continue
        p = diffs[0]
        vals = param_grid[p]
        if abs(vals.index(tr[p]) - vals.index(best[p])) == 1:
            neigh.append(scores[i])
    best_score = scores[best_i]
    ratio = float(np.median(neigh) / best_score) if neigh and best_score > 0 else None
    return {"best_params": best, "best_score": best_score, "neighbour_median": float(np.median(neigh)) if neigh else None,
            "neighbour_ratio": ratio, "marginal": {p: {str(k): v for k, v in d.items()} for p, d in marginal.items()},
            "share_of_trials_positive": float(np.mean(np.array(scores) > 0))}


# --------------------------------------------------------------------------- #
# Bootstrap / null tests
# --------------------------------------------------------------------------- #


def stationary_bootstrap(returns: pd.Series, n_sims: int = 2000, mean_block: int = 20, horizon: int | None = None, seed: int = 0) -> np.ndarray:
    """Politis-Romano stationary bootstrap. Returns array (n_sims, horizon) of resampled daily returns."""
    r = returns.dropna().to_numpy(float)
    n = len(r)
    h = horizon or n
    rng = np.random.default_rng(seed)
    out = np.empty((n_sims, h))
    p = 1.0 / mean_block
    for s in range(n_sims):
        idx = np.empty(h, dtype=int)
        j = rng.integers(n)
        for t in range(h):
            if t > 0 and rng.random() < p:
                j = rng.integers(n)
            idx[t] = j
            j = (j + 1) % n
        out[s] = r[idx]
    return out


def bootstrap_summary(returns: pd.Series, n_sims: int = 1000, seed: int = 0, horizon_days: int = TRADING_DAYS) -> dict:
    sims = stationary_bootstrap(returns, n_sims=n_sims, horizon=horizon_days, seed=seed)
    eq = np.cumprod(1 + sims, axis=1)
    annual = eq[:, -1] - 1
    dd = 1 - eq / np.maximum.accumulate(eq, axis=1)
    mdd = dd.max(axis=1)
    return {
        "horizon_days": horizon_days,
        "annual_return_p05": float(np.percentile(annual, 5)),
        "annual_return_p50": float(np.percentile(annual, 50)),
        "annual_return_p95": float(np.percentile(annual, 95)),
        "prob_loss_year": float((annual < 0).mean()),
        "max_dd_p50": float(np.percentile(mdd, 50)),
        "max_dd_p95": float(np.percentile(mdd, 95)),
        "prob_dd_over_30": float((mdd > 0.30).mean()),
        "prob_dd_over_50": float((mdd > 0.50).mean()),
    }


def position_shift_null(weights: pd.DataFrame, run_fn: Callable[[pd.DataFrame], pd.Series], actual_sharpe: float,
                        n_shifts: int = 200, min_shift: int = 21, seed: int = 0, periods: int = TRADING_DAYS) -> dict:
    """Circularly shift the decision-weight history in time (keeps exposure, turnover
    and autocorrelation of positions, destroys timing). p = share of shifted
    versions with Sharpe >= actual.

    All-NaN rows are HOLD rows (engine.run_weights: keep the drifted book, no trade). They
    move with their decision rows, so every shifted run trades on as many rows as the
    strategy did; a shift that puts a hold row first gets the decision in force there (the
    last decision row circularly before it), so it does not start in cash. The caller must
    seed row 0 the same way (the decision in force at the window start). ``periods`` only
    annualizes the reported null Sharpes and must match ``actual_sharpe`` (p is scale-free)."""
    rng = np.random.default_rng(seed)
    n = len(weights)
    if n < 3 * min_shift:
        return {"p_value": None}
    vals = weights.to_numpy()
    hold = np.isnan(vals.astype(float)).all(axis=1)
    if hold.any():
        last = np.maximum.accumulate(np.where(hold, -1, np.arange(n)))
        in_force = np.where((last >= 0)[:, None], np.nan_to_num(vals[np.maximum(last, 0)].astype(float)), 0.0)
    null = []
    for _ in range(n_shifts):
        k = int(rng.integers(min_shift, n - min_shift))
        rolled = np.roll(vals, k, axis=0)
        if hold[-k]:  # rolled row 0 = original row n-k
            rolled[0] = in_force[-k]
        shifted = pd.DataFrame(rolled, index=weights.index, columns=weights.columns)
        null.append(sharpe(run_fn(shifted), periods))
    null = np.array(null)
    return {"p_value": float((null >= actual_sharpe).mean()), "null_sharpe_p50": float(np.median(null)), "null_sharpe_p95": float(np.percentile(null, 95)), "n": int(n_shifts)}


def mean_return_test(returns: pd.Series, n_boot: int = 2000, seed: int = 0) -> dict:
    """Block-bootstrap test of H0: mean daily return <= 0 (for trade-based strategies)."""
    r = returns.dropna()
    if len(r) < 30:
        return {"p_value": None}
    centered = r - r.mean()
    sims = stationary_bootstrap(centered, n_sims=n_boot, seed=seed)
    null_means = sims.mean(axis=1)
    return {"p_value": float((null_means >= r.mean()).mean())}


# --------------------------------------------------------------------------- #
# Regimes
# --------------------------------------------------------------------------- #


def regime_labels(spy_close: pd.Series) -> pd.Series:
    """Lagged one day so a label never uses the day it describes."""
    sma = spy_close.rolling(200, min_periods=150).mean()
    vol = spy_close.pct_change().rolling(20).std()
    vol_med = vol.rolling(252, min_periods=120).median()
    trend = np.where(spy_close > sma, "up", "down")
    v = np.where(vol > vol_med, "highvol", "lowvol")
    lab = pd.Series([f"{a}_{b}" for a, b in zip(trend, v)], index=spy_close.index)
    lab[sma.isna() | vol_med.isna()] = "warmup"
    return lab.shift(1).fillna("warmup")


def regime_breakdown(returns: pd.Series, labels: pd.Series, periods: int = TRADING_DAYS) -> dict:
    lab = labels.reindex(returns.index).fillna("warmup")
    out = {}
    for name, grp in returns.groupby(lab):
        out[name] = {"days": int(len(grp)), "ann_return": float(grp.mean() * periods), "sharpe": sharpe(grp, periods)}
    yearly = (1 + returns).groupby(returns.index.year).prod() - 1
    out["by_year"] = {str(k): float(v) for k, v in yearly.items()}
    return out


# --------------------------------------------------------------------------- #
# Leverage analysis
# --------------------------------------------------------------------------- #


def lever(returns: pd.Series, leverage: float, margin_rate: float = 0.07, base_exposure: pd.Series | None = None,
          periods: int = TRADING_DAYS) -> pd.Series:
    """Scale an unlevered strategy. Borrowing cost applies to exposure above 1x of equity
    (``margin_rate`` per year spread over ``periods`` rows per year)."""
    expo = base_exposure.reindex(returns.index).fillna(0.0) if base_exposure is not None else pd.Series(1.0, returns.index)
    borrowed = np.maximum(0.0, leverage * expo - 1.0)
    return leverage * returns - borrowed * margin_rate / periods


def leverage_analysis(returns: pd.Series, targets: tuple[float, ...] = (0.05, 0.08), margin_rate: float = 0.07,
                      exposure: pd.Series | None = None, max_leverage: float = 20.0, n_boot: int = 500, seed: int = 0,
                      periods: int = TRADING_DAYS) -> dict:
    """``periods`` = rows per year (252 stocks, ~365 crypto): daily financing and the 1-year bootstrap horizon."""
    r = returns.dropna()
    if len(r) < 60:
        return {"note": "too short"}
    grid_l = np.round(np.arange(0.5, max_leverage + 1e-9, 0.25), 2)
    rows = []
    for L in grid_l:
        rl = lever(r, L, margin_rate, exposure, periods)
        m = monthly_returns(rl)
        geo = float((1 + m).prod() ** (1 / len(m)) - 1) if (1 + m).prod() > 0 else -1.0
        rows.append({"leverage": float(L), "monthly_geo": geo, "max_dd": max_drawdown(rl), "ruined": bool((1 + rl).cumprod().min() < 0.05)})
    table = pd.DataFrame(rows)
    mu, var = r.mean(), r.var(ddof=1)
    avg_expo = float(exposure.reindex(r.index).fillna(0).mean()) if exposure is not None else 1.0
    mu_fin = mu - avg_expo * margin_rate / periods  # each extra 1x of exposure is financed
    kelly = float(mu_fin / var) if var > 0 else 0.0
    best_geo = table.loc[table["monthly_geo"].idxmax()]
    out = {"kelly_leverage": kelly, "growth_optimal_leverage_hist": float(best_geo["leverage"]), "max_monthly_geo_any_leverage": float(best_geo["monthly_geo"]), "targets": {}}
    for tgt in targets:
        hit = table[table["monthly_geo"] >= tgt]
        if hit.empty:
            out["targets"][f"{tgt:.0%}"] = {"reachable_historically": False, "note": "no leverage up to %.0fx reaches this in-sample (volatility drag dominates)" % max_leverage}
            continue
        L = float(hit["leverage"].iloc[0])
        rl = lever(r, L, margin_rate, exposure, periods)
        boot = bootstrap_summary(rl, n_sims=n_boot, seed=seed, horizon_days=periods)
        out["targets"][f"{tgt:.0%}"] = {"reachable_historically": True, "leverage_needed": L, "hist_max_dd": float(hit["max_dd"].iloc[0]),
                                        "vs_kelly": L / kelly if kelly > 0 else None, "bootstrap_1y": boot,
                                        "max_gross_exposure_needed": float(L * (exposure.max() if exposure is not None else 1.0)),
                                        "broker_feasible_overnight_2x": L * float(exposure.max() if exposure is not None else 1.0) <= 2.0}
    out["table"] = table[table["leverage"].isin([1, 2, 3, 4, 5, 8, 10, 15, 20])].to_dict("records")
    return out
