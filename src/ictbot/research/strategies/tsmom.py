"""Time-series momentum (trend following) across a multi-asset ETF universe.

Hypothesis: assets whose own trailing return is positive tend to keep rising
(and negative keep falling) over the next weeks - the classic managed-futures
"trend" premium (Moskowitz, Ooi & Pedersen 2012). Positions are volatility
targeted so quiet and volatile assets contribute similar risk.
"""

from __future__ import annotations

import pandas as pd

from ..base import StrategySpec, register
from ..engine import run_weights
from .common import available, hold_between_rebalances, vol_target_weights

UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "DBC", "VNQ", "UUP"]


def run(data, p, costs):
    syms = available(data, UNIVERSE)
    close = data.panel("close", syms)
    rets = close.pct_change()
    lb = int(p["lookback"])
    mom = close / close.shift(lb) - 1.0
    if p["confirm_sma"]:
        sma = close.rolling(lb, min_periods=lb // 2).mean()
        trend_ok_long = close > sma
        trend_ok_short = close < sma
    else:
        trend_ok_long = trend_ok_short = pd.DataFrame(True, index=close.index, columns=close.columns)
    raw = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    raw[(mom > 0) & trend_ok_long] = 1.0
    if p["allow_short"]:
        raw[(mom < 0) & trend_ok_short] = -1.0
    raw[mom.isna()] = 0.0
    w = vol_target_weights(raw, rets, p["target_vol"], lookback=60, max_gross=p["max_gross"], per_asset_cap=0.5)
    w = hold_between_rebalances(w, p["rebalance"])
    return run_weights(data, w, costs, band=0.01)


SPEC = register(StrategySpec(
    name="tsmom_multi_asset",
    family="trend_following",
    hypothesis="Own-asset trailing return sign predicts next-period return across asset classes (vol-targeted).",
    param_grid={"lookback": [63, 126, 252], "allow_short": [False, True], "target_vol": [0.10, 0.20], "rebalance": ["W", "M"],
                "confirm_sma": [False, True], "max_gross": [1.0]},
    default_params={"lookback": 126, "allow_short": False, "target_vol": 0.10, "rebalance": "W", "confirm_sma": False, "max_gross": 1.0},
    run_fn=run,
    symbols=tuple(UNIVERSE),
))
