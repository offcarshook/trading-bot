"""Causal indicators: the value at index i only uses data up to and including i."""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.concatenate(([np.nan], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder ATR seeded with the simple mean of the first ``period`` true ranges.
    NaN until ``period`` bars exist."""
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    n = len(high)
    out = np.full(n, np.nan)
    if n < period:
        return out
    tr = true_range(high, low, close)
    out[period - 1] = tr[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def ema(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def relative_volume(volume: np.ndarray, window: int = 20) -> np.ndarray:
    """volume[i] / mean(volume[i-window:i]) - excludes the current bar from the base."""
    vol = pd.Series(np.asarray(volume, dtype=float))
    base = vol.shift(1).rolling(window, min_periods=max(3, window // 2)).mean()
    return (vol / base.replace(0, np.nan)).to_numpy()


def rolling_correlation(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    """Rolling Pearson correlation of simple returns on the intersection of timestamps."""
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    rets = joined.pct_change().dropna()
    return rets["a"].rolling(window, min_periods=max(10, window // 4)).corr(rets["b"])
