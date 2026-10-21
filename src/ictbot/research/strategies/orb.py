"""Opening range breakout (ORB) on 5-minute bars for SPY / QQQ / IWM.

Hypothesis: a break of the first M minutes' range (Crabel 1990; Zarattini,
Barbon & Aziz 2023 "A profitable day trading strategy for the U.S. equity
market") signals intraday directional order flow that persists, so a stop
entry at the range edge with a stop at the opposite side / fraction of the
range earns a positive net return after costs.

Mechanics (one trade per symbol per day, flat by the session close):
  * OR = bars whose START is before first_bar_start + M minutes. Entries only
    on bars starting at/after the OR end (never on an OR bar).
  * Buy-stop at OR high, sell-stop at OR low, first touch only. Fill at
    max(bar open, level) for longs, min(bar open, level) for shorts (kind 'stop').
    A bar that touches both levels before any entry is ambiguous -> skipped.
  * Protective stop = entry_side_level -/+ stop_frac * OR width
    (stop_frac=1.0 -> opposite OR side). Fill at min(open, stop) for longs when
    gapping through (kind 'stop'). Stop is checked on the entry bar too
    (conservative: if the entry bar also reaches the stop, it is assumed hit).
  * Target = entry +/- target_r * risk (0 = none). Never credited on the entry
    bar; if a later bar touches stop and target the STOP wins. Limit fill at the
    target price (kind 'open' slippage as a proxy for a resting limit).
  * Otherwise exit at the close of the day's actual last bar (early closes ok).
  * Filters (pre-registered): width_filter keeps OR width / ATR14(daily, through
    yesterday) in [0.05, 0.60]; trend_filter allows longs only if yesterday's
    close > SMA20 through yesterday (shorts only if below).
  * Size = risk_pct / stop distance %, capped at max_size / n_symbols so total
    gross across symbols can never exceed max_size.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategySpec, register
from ..engine import TRADE_COLUMNS, run_trades

UNIVERSE = ["SPY", "QQQ", "IWM"]
NY = "America/New_York"
WIDTH_LO, WIDTH_HI = 0.05, 0.60


def _daily_context(daily: pd.DataFrame | None) -> pd.DataFrame:
    """ATR14 and trend state per date, all computed through YESTERDAY."""
    if daily is None or daily.empty:
        return pd.DataFrame(columns=["atr", "up", "dn"])
    d = daily.sort_index()
    prev_c = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev_c).abs(), (d["low"] - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean().shift(1)
    sma = d["close"].rolling(20, min_periods=20).mean().shift(1)
    return pd.DataFrame({"atr": atr, "up": prev_c > sma, "dn": prev_c < sma}, index=d.index)


def symbol_trades(bars: pd.DataFrame, daily: pd.DataFrame | None, sym: str, p: dict, n_syms: int) -> tuple[list, int]:
    if bars is None or bars.empty:
        return [], 0
    bars = bars.sort_index()
    idx = bars.index
    if idx.tz is None:
        idx = idx.tz_localize(NY)
    else:
        idx = idx.tz_convert(NY)
    o, h, lo, c = (bars[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    t_ns = idx.as_unit("ns").asi8
    day = idx.normalize().tz_localize(None)
    day_ns = day.as_unit("ns").asi8
    starts = np.flatnonzero(np.r_[True, day_ns[1:] != day_ns[:-1]])
    ends = np.r_[starts[1:], len(day_ns)]
    ctx = _daily_context(daily)
    atr = ctx["atr"].reindex(day[starts]).to_numpy(float) if len(ctx) else np.full(len(starts), np.nan)
    up = ctx["up"].reindex(day[starts]).fillna(False).to_numpy(bool) if len(ctx) else np.zeros(len(starts), bool)
    dn = ctx["dn"].reindex(day[starts]).fillna(False).to_numpy(bool) if len(ctx) else np.zeros(len(starts), bool)

    or_ns = int(p["or_minutes"]) * 60 * 10**9
    stop_frac, target_r = float(p["stop_frac"]), float(p["target_r"])
    cap = float(p["max_size"]) / max(n_syms, 1)
    risk_pct = float(p["risk_pct"])
    rows, ambiguous = [], 0
    for k, (a, b) in enumerate(zip(starts, ends)):
        tt = t_ns[a:b]
        n_or = int(np.searchsorted(tt, tt[0] + or_ns))
        if n_or < 1 or n_or >= b - a:
            continue
        oh, ol = h[a:a + n_or].max(), lo[a:a + n_or].min()
        width = oh - ol
        if not (np.isfinite(width) and width > 0 and ol > 0):
            continue
        if p["width_filter"]:
            r = width / atr[k] if np.isfinite(atr[k]) and atr[k] > 0 else np.nan
            if not (WIDTH_LO <= r <= WIDTH_HI):
                continue
        allow_l = allow_s = True
        if p["trend_filter"]:
            allow_l, allow_s = bool(up[k]), bool(dn[k])
        s = a + n_or
        hh, ll, oo, cc = h[s:b], lo[s:b], o[s:b], c[s:b]
        tl = (hh >= oh) if allow_l else np.zeros(b - s, bool)
        ts = (ll <= ol) if allow_s else np.zeros(b - s, bool)
        any_t = tl | ts
        if not any_t.any():
            continue
        j = int(np.argmax(any_t))
        if tl[j] and ts[j]:
            ambiguous += 1
            continue
        if tl[j]:
            sign, entry = 1.0, max(oo[j], oh)
            stop = oh - stop_frac * width
        else:
            sign, entry = -1.0, min(oo[j], ol)
            stop = ol + stop_frac * width
        risk = sign * (entry - stop)
        if not risk > 0 or stop <= 0:
            continue
        target = entry + sign * target_r * risk if target_r > 0 else np.nan
        # exit scan from the entry bar onward
        if sign > 0:
            hit_stop = ll[j:] <= stop
            hit_tgt = hh[j:] >= target if target_r > 0 else np.zeros(len(hh) - j, bool)
        else:
            hit_stop = hh[j:] >= stop
            hit_tgt = ll[j:] <= target if target_r > 0 else np.zeros(len(hh) - j, bool)
        hit_tgt[0] = False  # never credit a target on the entry bar (order unknowable)
        ev = hit_stop | hit_tgt
        if ev.any():
            e = int(np.argmax(ev))
            if hit_stop[e]:  # stop wins ties
                px = min(oo[j + e], stop) if sign > 0 else max(oo[j + e], stop)
                if e == 0:
                    px = stop  # entry bar: open is before our entry, fill at the stop
                xk, reason = "stop", "stop"
            else:
                px, xk, reason = target, "open", "target"
            xi = s + j + e
        else:
            px, xk, reason, xi = cc[-1], "close", "close", b - 1
        size = min(cap, risk_pct / (risk / entry))
        rows.append((day[a], sym, "long" if sign > 0 else "short", idx[s + j], entry, idx[xi], px, size, "stop", xk, reason))
    return rows, ambiguous


def run(data, p, costs):
    syms = [s for s in UNIVERSE if s in data.intraday and not data.intraday[s].empty]
    dates = data.panel("close", [s for s in UNIVERSE if s in data.daily]).index if any(s in data.daily for s in UNIVERSE) else pd.DatetimeIndex([])
    rows, amb = [], 0
    for s in syms:
        r, a = symbol_trades(data.intraday[s], data.daily.get(s), s, p, len(UNIVERSE))
        rows += r
        amb += a
    trades = pd.DataFrame(rows, columns=TRADE_COLUMNS) if rows else pd.DataFrame(columns=TRADE_COLUMNS)
    if not trades.empty:
        trades = trades.sort_values(["date", "symbol"], ignore_index=True)
    res = run_trades(trades, dates, costs, max_gross=float(p["max_size"]))
    res.notes["skipped_ambiguous_bar"] = amb
    return res


SPEC = register(StrategySpec(
    name="orb_intraday",
    family="opening_range_breakout",
    hypothesis="A first-touch stop entry at the edge of the first 5/15/30-minute range of SPY/QQQ/IWM, with a stop at the opposite side (or half the range) and exit by target or the session close, earns positive net returns after costs.",
    param_grid={"or_minutes": [5, 15, 30], "stop_frac": [1.0, 0.5], "target_r": [0.0, 1.5, 3.0],
                "width_filter": [False, True], "trend_filter": [False, True], "risk_pct": [0.01], "max_size": [2.0]},
    default_params={"or_minutes": 15, "stop_frac": 1.0, "target_r": 0.0, "width_filter": False, "trend_filter": False,
                    "risk_pct": 0.01, "max_size": 2.0},
    run_fn=run,
    uses_intraday=True,
    symbols=tuple(UNIVERSE),
))
