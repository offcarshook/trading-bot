"""Leveraged-ETF trend following and volatility-regime switching.

Hypothesis: the drawdowns that destroy daily-reset leveraged ETFs (TQQQ, UPRO,
QLD, SSO) cluster in downtrends and high-volatility regimes of the underlying,
where volatility decay is worst. Holding the REAL leveraged ETF only while the
underlying is above its long moving average (and, for the regime variant, while
its realized volatility is below its own trailing median) should keep most of
the leveraged upside and cut the decay/crash exposure (cf. Gayed & Bilello 2016
"Leverage for the Long Run"). Real ETF prices are used, so decay is included.

Decisions use closes through date t and are executed at the next open by
``run_weights``. "CASH" means all-zero weights (earns costs.cash_rate).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategySpec, register
from ..engine import run_weights

UNDERLYING = {"TQQQ": "QQQ", "QLD": "QQQ", "UPRO": "SPY", "SSO": "SPY"}
DEFENSIVE = ["SHY", "IEF", "TLT", "GLD"]


def _close(data, sym, index):
    if sym not in data.daily:
        return pd.Series(np.nan, index=index)
    return data.daily[sym]["close"].reindex(index)


def _hysteresis(enter: pd.Series, exit_: pd.Series) -> pd.Series:
    """1 after an enter signal, 0 after an exit signal, previous state otherwise (causal)."""
    state = pd.Series(np.nan, index=enter.index)
    state[exit_.to_numpy(bool)] = 0.0
    state[enter.to_numpy(bool)] = 1.0
    return state.ffill().fillna(0.0)


def trend_state(close: pd.Series, n: int, filt: str) -> pd.Series:
    """In-trend flag (1/0) of ``close`` vs SMA(n) with an optional whipsaw filter.
    filt: 'none' | 'band2' (enter >SMA*1.02, exit <SMA*0.98) | 'confirm3' (3 consecutive closes)."""
    sma = close.rolling(n, min_periods=n).mean()
    valid = sma.notna() & close.notna()
    above = (close > sma) & valid
    below = (close <= sma) & valid
    if filt == "none":
        return _hysteresis(above, below)
    if filt == "band2":
        return _hysteresis((close > sma * 1.02) & valid, (close < sma * 0.98) & valid)
    if filt == "confirm3":
        a = above.astype(float).rolling(3, min_periods=3).sum() == 3
        b = below.astype(float).rolling(3, min_periods=3).sum() == 3
        return _hysteresis(a, b)
    raise ValueError(f"unknown filter {filt}")


def _weights(index, cols, alloc: pd.Series, data) -> pd.DataFrame:
    """alloc: per-date symbol name (or 'CASH'). Symbols with no close on the decision date -> cash."""
    w = pd.DataFrame(0.0, index=index, columns=cols)
    for s in cols:
        ok = _close(data, s, index).notna()
        w.loc[(alloc == s) & ok, s] = 1.0
    return w


def _notes(alloc: pd.Series, lev: str, und: str, defensive: str, live: pd.Series) -> dict:
    a = alloc[live]
    n = max(len(a), 1)
    return {"time_in_leveraged": float((a == lev).sum() / n), "time_in_underlying": float((a == und).sum() / n),
            "time_in_defensive": float((a == defensive).sum() / n) if defensive != "CASH" else 0.0,
            "time_in_cash": float((a == "CASH").sum() / n),
            "time_in_market_risk": float(a.isin([lev, und]).sum() / n), "switches": int((a != a.shift()).sum() - 1)}


def run_trend(data, p, costs):
    lev, defensive = p["lev"], p["defensive"]
    und = UNDERLYING[lev]
    index = data.dates()
    uc = _close(data, und, index)
    state = trend_state(uc, int(p["sma"]), p["filter"]).astype(bool)
    alloc = pd.Series(np.where(state, lev, defensive), index=index)
    cols = [s for s in dict.fromkeys([lev, und] + DEFENSIVE) if s in data.daily]
    if lev not in cols:
        raise ValueError(f"{lev} not in data")
    w = _weights(index, cols, alloc, data)
    res = run_weights(data, w, costs, band=0.01)
    live = uc.rolling(int(p["sma"]), min_periods=int(p["sma"])).mean().notna()
    res.notes.update(_notes(alloc, lev, und, defensive, live))
    return res


MAPPINGS = {
    # (up & low vol, up & high vol, down & low vol, down & high vol)
    "lev_unlev_def": ("lev", "und", "def", "def"),
    "lev_def_def": ("lev", "def", "def", "def"),
    "lev_unlev_unlev": ("lev", "und", "und", "def"),
}


def regime_labels(uc: pd.Series, sma_n: int = 200, vol_n: int = 20, med_n: int = 252) -> pd.Series:
    """0..3 = up/low, up/high, down/low, down/high; NaN until all inputs exist. All trailing windows."""
    sma = uc.rolling(sma_n, min_periods=sma_n).mean()
    vol = np.log(uc).diff().rolling(vol_n, min_periods=vol_n).std() * np.sqrt(252)
    med = vol.rolling(med_n, min_periods=med_n).median()
    up = uc > sma
    high = vol > med
    lab = np.where(up, 0, 2) + np.where(high, 1, 0)
    valid = sma.notna() & med.notna() & vol.notna()
    return pd.Series(np.where(valid, lab, np.nan), index=uc.index)


def run_regime(data, p, costs):
    lev, defensive = p["lev"], p["defensive"]
    und = UNDERLYING[lev]
    index = data.dates()
    uc = _close(data, und, index)
    lab = regime_labels(uc)
    sym = {"lev": lev, "und": und, "def": defensive}
    table = np.array([sym[x] for x in MAPPINGS[p["mapping"]]], dtype=object)
    alloc = pd.Series(np.where(lab.notna(), table[lab.fillna(0).astype(int).to_numpy()], "CASH"), index=index)
    cols = [s for s in dict.fromkeys([lev, und] + DEFENSIVE) if s in data.daily]
    if lev not in cols:
        raise ValueError(f"{lev} not in data")
    w = _weights(index, cols, alloc, data)
    res = run_weights(data, w, costs, band=0.01)
    res.notes.update(_notes(alloc, lev, und, defensive, lab.notna()))
    return res


register(StrategySpec(
    name="leveraged_trend",
    family="leveraged_trend",
    hypothesis="Holding a real daily-reset leveraged ETF only while its underlying closes above SMA(n) "
               "(else a defensive asset) beats buy-and-hold of the leveraged ETF on risk-adjusted return and drawdown.",
    param_grid={"lev": ["TQQQ", "UPRO", "QLD", "SSO"], "sma": [150, 200], "filter": ["none", "band2", "confirm3"],
                "defensive": ["CASH", "SHY", "IEF"]},
    default_params={"lev": "TQQQ", "sma": 200, "filter": "band2", "defensive": "SHY"},
    run_fn=run_trend,
    symbols=("TQQQ", "UPRO", "QLD", "SSO", "QQQ", "SPY", "SHY", "IEF"),
))

register(StrategySpec(
    name="leveraged_trend_regime",
    family="leveraged_trend",
    hypothesis="Holding the leveraged ETF only in uptrend (above SMA200) AND low-volatility (20d vol below its "
               "trailing 1y median) regimes of the underlying yields higher Sharpe than trend-only or buy-and-hold leverage.",
    param_grid={"lev": ["TQQQ", "UPRO", "QLD", "SSO"], "mapping": list(MAPPINGS), "defensive": ["CASH", "SHY", "IEF"]},
    default_params={"lev": "TQQQ", "mapping": "lev_unlev_def", "defensive": "SHY"},
    run_fn=run_regime,
    symbols=("TQQQ", "UPRO", "QLD", "SSO", "QQQ", "SPY", "SHY", "IEF"),
))
