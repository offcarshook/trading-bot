"""Shared causal helpers for strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ResearchData


def available(data: ResearchData, symbols: list[str]) -> list[str]:
    return [s for s in symbols if s in data.daily]


def vol_target_weights(raw: pd.DataFrame, rets: pd.DataFrame, target_vol: float, lookback: int = 60,
                       max_gross: float = 1.0, per_asset_cap: float = 1.0) -> pd.DataFrame:
    """Scale raw signals (+1/0/-1 or fractional) so each position targets
    ``target_vol / n_active`` annualized vol, then cap gross exposure.
    Uses volatility estimated through the decision date (causal)."""
    vol = rets.rolling(lookback, min_periods=max(10, lookback // 2)).std() * np.sqrt(252)
    n_active = raw.ne(0).sum(axis=1).replace(0, np.nan)
    w = raw.div(vol).mul(target_vol).div(n_active, axis=0)
    w = w.clip(-per_asset_cap, per_asset_cap).fillna(0.0)
    gross = w.abs().sum(axis=1)
    scale = (max_gross / gross).clip(upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)


def rebalance_mask(index: pd.DatetimeIndex, freq: str) -> pd.Series:
    """True on the FIRST session of each new period ('D' = every day, 'W', 'M').
    (Using the LAST session would require knowing tomorrow's date is in a new
    period - harmless with a known calendar, but it fails the strict causality test.)"""
    if freq == "D":
        return pd.Series(True, index=index)
    per = pd.Series(index.to_period("W-FRI" if freq == "W" else "M"), index=index)
    return per.ne(per.shift(1))


def hold_between_rebalances(w: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Keep target rows only on rebalance sessions; other rows become all-NaN,
    which the engine treats as "hold the drifted position, no trade"."""
    mask = rebalance_mask(w.index, freq)
    return w.where(mask, np.nan)


# --------------------------------------------------------------------------- #
# Broker margin capacity
# --------------------------------------------------------------------------- #

REG_T_INITIAL = 0.50  # Reg-T initial margin for ordinary long stock / ETFs
LETF_MAINT_PER_X = 0.25  # FINRA 4210 / Notice 09-53: leveraged ETF maintenance = 25% x leverage factor
MARGIN_BUFFER = 0.03  # stay a little inside the limit


def margin_requirement(symbol: str) -> float:
    from ..universe import INSTRUMENTS

    inst = INSTRUMENTS.get(symbol)
    if "/" in symbol or (inst and inst.asset_class == "crypto"):
        return 1.0  # Alpaca crypto is not marginable: fully paid with cash
    lev = inst.leverage_factor if inst else 1.0
    return min(1.0, max(REG_T_INITIAL, LETF_MAINT_PER_X * lev))


def cap_to_margin(w: pd.DataFrame) -> pd.DataFrame:
    """Scale each row so sum(|w_i| * requirement_i) <= 1 - buffer: the most a
    margin account can hold (3x LETF -> ~1.29x gross, 1x ETF -> ~1.94x)."""
    req = pd.Series({c: margin_requirement(c) for c in w.columns})
    used = w.abs().mul(req, axis=1).sum(axis=1)
    scale = ((1.0 - MARGIN_BUFFER) / used).clip(upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)
