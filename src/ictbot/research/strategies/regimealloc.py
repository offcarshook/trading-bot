"""Unlevered multi-asset regime allocation.

Hypothesis: a simple causal macro regime classification (SPY trend, SPY
volatility state, bond trend) mapped to pre-registered allocations over
SPY/QQQ/TLT/IEF/GLD/SHY delivers better risk-adjusted returns than static
holdings, because equity drawdowns cluster in below-trend / high-vol regimes
in which duration (deflationary) or gold + cash (inflationary) outperform.

Regimes (all computed with data through the decision close; executed next open):
  0 risk_on      SPY > SMA(trend_sma) and (vol filter off or vol not high)
  1 caution      SPY > SMA(trend_sma) and vol high (20d RV > trailing 252d median of RV)
  2 off_deflat   SPY <= SMA and bond (TLT, fallback IEF) > SMA(bond_sma)
  3 off_inflat   SPY <= SMA and bond <= SMA
Regime switches are applied at most once per ``min_hold`` sessions (weekly);
weights drift between switches with a 5% no-trade band.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategySpec, register
from ..engine import run_weights
from .common import available

ASSETS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "SHY"]
CASH_PROXY = "SHY"

# Pre-registered regime -> allocation maps (each row sums to 1.0, unlevered).
ALLOC_MAPS: dict[str, dict[int, dict[str, float]]] = {
    # "balanced": diversified tilts
    "balanced": {
        0: {"SPY": 0.6, "QQQ": 0.4},
        1: {"SPY": 0.3, "QQQ": 0.2, "IEF": 0.3, "GLD": 0.2},
        2: {"TLT": 0.4, "IEF": 0.3, "GLD": 0.3},
        3: {"GLD": 0.5, "SHY": 0.5},
    },
    # "defensive": bond/cash heavy outside risk-on
    "defensive": {
        0: {"SPY": 0.7, "IEF": 0.3},
        1: {"SPY": 0.4, "IEF": 0.4, "SHY": 0.2},
        2: {"IEF": 0.6, "SHY": 0.4},
        3: {"SHY": 0.7, "GLD": 0.3},
    },
    # "aggressive": growth-heavy risk-on, long duration in deflationary risk-off
    "aggressive": {
        0: {"QQQ": 0.6, "SPY": 0.4},
        1: {"SPY": 0.5, "GLD": 0.25, "TLT": 0.25},
        2: {"TLT": 0.7, "GLD": 0.3},
        3: {"GLD": 0.6, "SHY": 0.4},
    },
}


def classify(spy: pd.Series, bond: pd.Series, trend_sma: int, bond_sma: int, vol_filter: bool) -> pd.Series:
    """Causal regime label per date (NaN during warm-up)."""
    s_sma = spy.rolling(trend_sma, min_periods=trend_sma).mean()
    b_sma = bond.rolling(bond_sma, min_periods=bond_sma).mean()
    eq_up = spy > s_sma
    bond_up = bond > b_sma
    reg = pd.Series(np.where(eq_up, 0.0, np.where(bond_up, 2.0, 3.0)), index=spy.index)
    valid = s_sma.notna() & b_sma.reindex(spy.index).notna()
    if vol_filter:
        rv = spy.pct_change().rolling(20, min_periods=20).std()
        med = rv.rolling(252, min_periods=252).median()
        high = rv > med
        reg = reg.where(~(eq_up & high), 1.0)
        valid &= med.notna()
    return reg.where(valid)


def apply_min_hold(reg: pd.Series, min_hold: int) -> pd.Series:
    """Switch to a new regime only if >= min_hold sessions since the last switch."""
    r = reg.to_numpy(float)
    out = np.full(len(r), np.nan)
    cur, last = np.nan, -10**9
    for i, x in enumerate(r):
        if np.isfinite(x) and x != cur and (not np.isfinite(cur) or i - last >= min_hold):
            cur, last = x, i
        out[i] = cur
    return pd.Series(out, index=reg.index)


def regime_weights(reg: pd.Series, alloc: dict[int, dict[str, float]], syms: list[str]) -> pd.DataFrame:
    rows = {}
    for k, a in alloc.items():
        row = dict.fromkeys(syms, 0.0)
        for s, w in a.items():
            tgt = s if s in syms else (CASH_PROXY if CASH_PROXY in syms else None)
            if tgt is not None:  # missing asset -> cash proxy, else uninvested cash
                row[tgt] += w
        rows[k] = row
    table = pd.DataFrame.from_dict(rows, orient="index")[syms]
    w = table.reindex(reg.to_numpy()).set_axis(reg.index)
    return w.fillna(0.0)


def run(data, p, costs):
    syms = available(data, ASSETS)
    if "SPY" not in syms:
        raise ValueError("regime_allocation needs SPY")
    close = data.panel("close", syms)
    bond_sym = "TLT" if "TLT" in syms else ("IEF" if "IEF" in syms else None)
    spy = close["SPY"].ffill()
    bond = close[bond_sym].ffill() if bond_sym else pd.Series(np.nan, index=close.index)
    reg = classify(spy, bond, int(p["trend_sma"]), int(p["bond_sma"]), bool(p["vol_filter"]))
    reg = apply_min_hold(reg, int(p["min_hold"]))
    w = regime_weights(reg, ALLOC_MAPS[p["alloc_map"]], syms)
    res = run_weights(data, w, costs, band=float(p["band"]))
    res.notes["regime_counts"] = reg.value_counts().to_dict()
    return res


SPEC = register(StrategySpec(
    name="regime_allocation",
    family="regime_allocation",
    hypothesis=("Allocating SPY/QQQ/TLT/IEF/GLD/SHY by a causal regime (SPY vs SMA, SPY vol vs 1y median, bond trend) "
                "yields a higher Sharpe and smaller max drawdown than a static 60/40 SPY/IEF mix."),
    param_grid={"trend_sma": [100, 200], "bond_sma": [50, 100, 200], "vol_filter": [False, True],
                "alloc_map": ["balanced", "defensive", "aggressive"], "min_hold": [5], "band": [0.05]},
    default_params={"trend_sma": 200, "bond_sma": 100, "vol_filter": True, "alloc_map": "balanced",
                    "min_hold": 5, "band": 0.05},
    run_fn=run,
    symbols=tuple(ASSETS),
))
