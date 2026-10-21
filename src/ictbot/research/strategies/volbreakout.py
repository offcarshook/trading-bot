"""Daily volatility breakout (Larry Williams / Toby Crabel "open range expansion").

Hypothesis: when price moves away from today's open by more than a fraction k
of recent volatility (prior-day range or ATR through yesterday), the move tends
to continue into the close, so a buy-stop at open + k*vol held to the close
earns a positive net return after costs.

Mechanics (daily bars only, flat every night):
  * levels are fixed after the 09:30 open: long = open + k*vol, short = open - k*vol,
    where vol uses bars through YESTERDAY only.
  * long fills at max(open, level) when today's high >= level (kind 'stop'),
    short fills at min(open, level) when today's low <= level; exit at today's close.
  * when shorts are enabled and both levels are touched the intraday order is
    unknowable from daily bars -> the worse of the two trades is booked (pessimistic)
    and the count is reported in notes['both_touched'].
  * optional trend filter: long only if yesterday's close > SMA(n) through yesterday
    (short only if below).
  * size per trade = max_gross / number of universe symbols, so the sum of all
    simultaneous trades can never exceed max_gross (no same-day look-ahead scaling).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategySpec, register
from ..engine import TRADE_COLUMNS, run_trades
from .common import available

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "GLD", "TLT"]


def _vol_measure(df: pd.DataFrame, measure: str, n: int) -> pd.Series:
    """Volatility through YESTERDAY (shifted by one session)."""
    if measure == "range":
        return (df["high"] - df["low"]).shift(1)
    prev_c = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_c).abs(), (df["low"] - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean().shift(1)


def symbol_trades(df: pd.DataFrame, sym: str, p: dict, size: float) -> tuple[pd.DataFrame, int]:
    df = df.sort_index()
    o, h, lo, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    vol = _vol_measure(df, p["measure"], int(p["atr_n"])).to_numpy(float)
    k = float(p["k"])
    ok = np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(c) & np.isfinite(vol) & (vol > 0) & (o > 0)
    long_lvl = o + k * vol
    short_lvl = o - k * vol
    long_ok = ok.copy()
    short_ok = ok.copy() if p["allow_short"] else np.zeros(len(o), bool)
    tn = int(p["trend_sma"])
    if tn > 0:
        prev_c = df["close"].shift(1)
        sma = df["close"].rolling(tn, min_periods=tn).mean().shift(1)
        up = (prev_c > sma).to_numpy()
        dn = (prev_c < sma).to_numpy()
        long_ok &= up
        short_ok &= dn
    hit_l = long_ok & (h >= long_lvl)
    hit_s = short_ok & (lo <= short_lvl) & (short_lvl > 0)
    both = hit_l & hit_s
    # Both OCO stops touched: the first fill is unknowable from daily bars.
    # Skipping these days would condition on the full-day range (look-ahead /
    # selection bias against whipsaw losers), so take the WORSE of the two trades.
    lpx = np.maximum(o, long_lvl)
    spx = np.minimum(o, short_lvl)
    with np.errstate(divide="ignore", invalid="ignore"):
        l_ret = c / lpx - 1.0
        s_ret = 1.0 - c / spx
    keep_long = both & (l_ret <= s_ret)
    hit_l &= ~both | keep_long
    hit_s &= ~both | ~keep_long
    rows = []
    for mask, direction, px in ((hit_l, "long", np.maximum(o, long_lvl)), (hit_s, "short", np.minimum(o, short_lvl))):
        if not mask.any():
            continue
        d = df.index[mask]
        rows.append(pd.DataFrame({
            "date": d, "symbol": sym, "direction": direction, "entry_time": d, "entry_price": px[mask],
            "exit_time": d, "exit_price": c[mask], "size": size, "entry_kind": "stop", "exit_kind": "close",
            "exit_reason": "close",
        }))
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=TRADE_COLUMNS)
    return out, int(both.sum())


def run(data, p, costs):
    syms = available(data, UNIVERSE)
    dates = data.panel("close", syms).index if syms else pd.DatetimeIndex([])
    max_gross = float(p["max_gross"])
    size = max_gross / max(len(UNIVERSE), 1)
    frames, skipped = [], 0
    for s in syms:
        t, nb = symbol_trades(data.daily[s], s, p, size)
        skipped += nb
        if not t.empty:
            frames.append(t)
    trades = pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"]) if frames else pd.DataFrame(columns=TRADE_COLUMNS)
    res = run_trades(trades, dates, costs, max_gross=max_gross)
    res.notes["both_touched"] = skipped
    return res


SPEC = register(StrategySpec(
    name="vol_breakout_daily",
    family="volatility_breakout",
    hypothesis="A move beyond open +/- k*(prior range or ATR through yesterday) continues to the close, so a stop entry held to the close is profitable net of costs.",
    param_grid={"k": [0.3, 0.5, 0.7], "measure": ["range", "atr"], "atr_n": [10], "allow_short": [False, True],
                "trend_sma": [0, 200], "max_gross": [2.0]},
    default_params={"k": 0.5, "measure": "range", "atr_n": 10, "allow_short": False, "trend_sma": 0, "max_gross": 2.0},
    run_fn=run,
    symbols=tuple(UNIVERSE),
))
