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
    mask = rebalance_mask(w.index, freq)
    return w.where(mask, np.nan).ffill().fillna(0.0)
