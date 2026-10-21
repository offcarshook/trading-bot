"""DEGEN MODE - maximum broker-feasible leverage (PAPER experiment only).

Alpaca caps stock buying power at ~2x overnight (Reg-T), so the most exposure
reachable is a 3x daily-reset leveraged ETF held with ~2x margin: ~6x the
underlying index. These strategies trade REAL leveraged-ETF prices (decay,
gaps and all) and pay margin interest on everything above 1x equity.

* degen_meanrev_letf - the meanrev_regime signals computed on SPY/QQQ/IWM/DIA,
  executed in UPRO/TQQQ/TNA/UDOW, optionally concentrating all margin into
  whatever is signalling.
* degen_trend_letf - TQQQ or UPRO with margin while the underlying trends up.
* degen_combo - mean-reversion trades when they fire, otherwise the trend
  sleeve; always within the margin cap.

No risk screens beyond the broker's buying power. Expect very large drawdowns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategySpec, register
from ..engine import run_weights
from .levtrend import trend_state
from .meanrev import positions, signals

LETF = {"SPY": "UPRO", "QQQ": "TQQQ", "IWM": "TNA", "DIA": "UDOW"}
MAX_MARGIN = 1.95  # stay just under the ~2x overnight buying power

MR_BASE = {"signal": "ibs", "exit_rule": "rsi2", "max_hold": 5, "allow_short": False}


def _meanrev_matrix(data, p, index) -> pd.DataFrame:
    """1.0 while a long mean-reversion trade is open on an UNDERLYING (decision dates)."""
    cols = {}
    sp = dict(MR_BASE, threshold=p["threshold"], vol_filter=bool(p["vol_filter"]))
    for und, lev in LETF.items():
        if und not in data.daily or lev not in data.daily:
            continue
        df = data.daily[und].sort_index()
        df = df[~df.index.duplicated(keep="last")]
        pos, _ = positions(signals(df, sp), int(sp["max_hold"]))
        cols[lev] = pd.Series(np.clip(pos, 0, None), index=df.index).reindex(index).ffill().fillna(0.0)
    return pd.DataFrame(cols, index=index)


def _size_meanrev(active: pd.DataFrame, margin: float, alloc: str) -> pd.DataFrame:
    if active.empty:
        return active
    if alloc == "equal_slots":
        return active * (margin / active.shape[1])
    n = active.sum(axis=1).replace(0, np.nan)
    return active.div(n, axis=0).mul(margin).fillna(0.0)  # concentrate all margin into the open trades


def run_meanrev_letf(data, p, costs):
    index = data.dates()
    margin = min(float(p["margin"]), MAX_MARGIN)
    w = _size_meanrev(_meanrev_matrix(data, p, index), margin, p["alloc"])
    res = run_weights(data, w, costs, band=0.02)
    res.notes.update({"time_in_market": float((w.sum(axis=1) > 0).mean()), "max_gross": float(w.sum(axis=1).max())})
    return res


def _trend_weights(data, index, lev: str, sma: int, margin: float) -> pd.DataFrame:
    und = {v: k for k, v in LETF.items()}[lev]
    uc = data.daily[und]["close"].reindex(index)
    state = trend_state(uc, sma, "band2").astype(bool)
    ok = data.daily[lev]["close"].reindex(index).notna()
    return pd.DataFrame({lev: np.where(state & ok, margin, 0.0)}, index=index)


def run_trend_letf(data, p, costs):
    index = data.dates()
    lev = p["lev"]
    if lev not in data.daily:
        raise ValueError(f"{lev} missing")
    w = _trend_weights(data, index, lev, int(p["sma"]), min(float(p["margin"]), MAX_MARGIN))
    res = run_weights(data, w, costs, band=0.02)
    res.notes.update({"time_in_market": float((w.sum(axis=1) > 0).mean())})
    return res


def run_combo(data, p, costs):
    index = data.dates()
    mr = _size_meanrev(_meanrev_matrix(data, p, index), MAX_MARGIN, "concentrate")
    tr = _trend_weights(data, index, "TQQQ", int(p["sma"]), min(float(p["trend_margin"]), MAX_MARGIN))
    mr_on = mr.sum(axis=1) > 0
    cols = sorted(set(mr.columns) | set(tr.columns))
    w = pd.DataFrame(0.0, index=index, columns=cols)
    w.loc[mr_on, mr.columns] = mr.loc[mr_on].to_numpy()
    w.loc[~mr_on, tr.columns] = tr.loc[~mr_on].to_numpy()
    res = run_weights(data, w, costs, band=0.02)
    res.notes.update({"time_meanrev": float(mr_on.mean()), "time_trend": float(((~mr_on) & (tr.sum(axis=1) > 0)).mean())})
    return res


register(StrategySpec(
    name="degen_meanrev_letf",
    family="degen_leverage",
    hypothesis="The mean-reversion edge on index ETFs survives being expressed through 3x leveraged ETFs with up to ~2x margin (~6x underlying).",
    param_grid={"margin": [1.0, 1.5, 1.95], "alloc": ["equal_slots", "concentrate"], "threshold": ["loose", "strict"], "vol_filter": [True, False]},
    default_params={"margin": 1.95, "alloc": "concentrate", "threshold": "strict", "vol_filter": True},
    run_fn=run_meanrev_letf,
    symbols=tuple(LETF) + tuple(LETF.values()),
))

register(StrategySpec(
    name="degen_trend_letf",
    family="degen_leverage",
    hypothesis="Holding a 3x index ETF with up to ~2x margin only while the underlying trends up compounds faster than unlevered trend following.",
    param_grid={"lev": ["TQQQ", "UPRO"], "sma": [100, 150, 200], "margin": [1.0, 1.5, 1.95]},
    default_params={"lev": "TQQQ", "sma": 150, "margin": 1.5},
    run_fn=run_trend_letf,
    symbols=("QQQ", "SPY", "TQQQ", "UPRO"),
))

register(StrategySpec(
    name="degen_combo",
    family="degen_leverage",
    hypothesis="Using idle time between mean-reversion trades for a margined TQQQ trend position raises growth over either sleeve alone.",
    param_grid={"trend_margin": [1.0, 1.5, 1.95], "sma": [150, 200], "threshold": ["loose", "strict"], "vol_filter": [True]},
    default_params={"trend_margin": 1.5, "sma": 150, "threshold": "strict", "vol_filter": True},
    run_fn=run_combo,
    symbols=tuple(LETF) + tuple(LETF.values()),
))
