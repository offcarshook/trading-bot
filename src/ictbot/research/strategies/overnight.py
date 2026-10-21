"""Overnight vs intraday return decomposition on SPY / QQQ / IWM.

Hypothesis (overnight_drift): most of the US equity premium accrues between the
close and the next open (Cliff, Cooper & Gulen 2008; Lou, Polk & Skouras 2019),
so buying at the close and selling at the next open earns a positive return -
the question is whether it survives two trades a day of costs.
Control (intraday_drift_control): buying the open and selling the same close
should earn ~nothing (or negative) net of costs.

Trades are built from adjusted RTH daily bars (daily open = first 5-min bar
open, close = last regular bar close, early closes included). Decisions use
only data through the close BEFORE the entry session (overnight, since a
market-on-close order must be sent before that close prints) or through the
PRIOR close (intraday control); weekday filters use only the entry date's own
weekday (no future calendar knowledge, so no pre-holiday filter).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategySpec, register
from ..engine import TRADE_COLUMNS, run_trades
from .common import available

UNIVERSE = ["SPY", "QQQ", "IWM"]
SMA_LEN = 200


def _universe(data, which):
    return available(data, UNIVERSE if which == "all" else [which])


def _regime_ok(close: pd.Series, filt: str) -> pd.Series:
    """True when the close (of the same row) is above its trailing 200-day SMA."""
    if filt == "none":
        return pd.Series(True, index=close.index)
    sma = close.rolling(SMA_LEN, min_periods=SMA_LEN).mean()
    return (close > sma).fillna(False)


def _build(data, p, mode):
    syms = _universe(data, p["universe"])
    dates = data.dates()
    if not syms:
        return pd.DataFrame(columns=TRADE_COLUMNS), dates
    size = float(p["size_mult"]) / len(syms)
    frames = []
    for s in syms:
        # reindex onto the master calendar so a missing session yields NaN (no trade) instead of
        # silently stitching a multi-day "overnight" hold across the gap
        d = data.daily[s].reindex(dates)
        if d["close"].notna().sum() < 2:
            continue
        o, c = d["open"], d["close"]
        ok = _regime_ok(c, p["trend_filter"])
        idx = d.index
        if mode == "overnight":
            # entry at close of row i-1, exit at open of row i; trade dated at exit session
            entry_px, exit_px = c.shift(1), o
            entry_date = pd.Series(idx, index=idx).shift(1)
            # MOC entry at close i-1 must be decided BEFORE that close prints, so the regime uses the
            # last COMPLETED close (i-2), not the entry close itself
            signal = ok.shift(2, fill_value=p["trend_filter"] == "none").astype(bool)
            if p["skip_weekday"]:
                signal &= pd.Series(pd.DatetimeIndex(entry_date).weekday != 4, index=idx)  # skip Friday-close entries
            entry_kind, exit_kind = "close", "open"
            entry_time = pd.DatetimeIndex(entry_date) + pd.Timedelta(hours=16)
            exit_time = idx + pd.Timedelta(hours=9, minutes=30)
        else:
            # buy open of row i, sell close of row i; regime decided with the PRIOR close
            entry_px, exit_px = o, c
            signal = ok.shift(1, fill_value=False).astype(bool)
            if p["skip_weekday"]:
                signal &= pd.Series(idx.weekday != 0, index=idx)  # skip Mondays (mirror of Friday-night skip)
            entry_kind, exit_kind = "open", "close"
            entry_time = idx + pd.Timedelta(hours=9, minutes=30)
            exit_time = idx + pd.Timedelta(hours=16)
        valid = signal.to_numpy() & np.isfinite(entry_px.to_numpy(float)) & np.isfinite(exit_px.to_numpy(float)) \
            & (entry_px.to_numpy(float) > 0)
        if not valid.any():
            continue
        frames.append(pd.DataFrame({
            "date": idx[valid], "symbol": s, "direction": "long",
            "entry_time": np.asarray(entry_time)[valid], "entry_price": entry_px.to_numpy(float)[valid],
            "exit_time": np.asarray(exit_time)[valid], "exit_price": exit_px.to_numpy(float)[valid],
            "size": size, "entry_kind": entry_kind, "exit_kind": exit_kind, "exit_reason": "scheduled",
        }))
    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TRADE_COLUMNS)
    return trades, dates


def run_overnight(data, p, costs):
    trades, dates = _build(data, p, "overnight")
    return run_trades(trades, dates, costs, max_gross=2.0)


def run_intraday(data, p, costs):
    trades, dates = _build(data, p, "intraday")
    return run_trades(trades, dates, costs, max_gross=2.0)


GRID = {"universe": ["all", "SPY", "QQQ", "IWM"], "trend_filter": ["none", "sma200"], "skip_weekday": [False, True],
        "size_mult": [1.0]}
DEFAULTS = {"universe": "all", "trend_filter": "none", "skip_weekday": False, "size_mult": 1.0}

register(StrategySpec(
    name="overnight_drift",
    family="overnight_intraday_decomposition",
    hypothesis="Holding SPY/QQQ/IWM from the close to the next open earns a positive mean return that survives "
               "close+open trading costs (overnight premium).",
    param_grid=GRID, default_params=DEFAULTS, run_fn=run_overnight, symbols=tuple(UNIVERSE),
))

register(StrategySpec(
    name="intraday_drift_control",
    family="overnight_intraday_decomposition",
    hypothesis="Control: holding SPY/QQQ/IWM from the open to the same-day close earns a mean return no greater "
               "than zero net of costs.",
    param_grid=GRID, default_params=DEFAULTS, run_fn=run_intraday, symbols=tuple(UNIVERSE),
))
