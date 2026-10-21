"""Mechanical ICT detectors.

Every function here is PURE and DETERMINISTIC: it takes arrays / dataclasses
and returns dataclasses, with no I/O, clock or global state. Each takes an
``end`` index meaning "the last COMPLETED bar you may look at"; nothing beyond
``end`` is ever read, which is how look-ahead is prevented. The same functions
drive live trading and the backtest.

Index conventions: all indices are positions in one bar frame (normally the
5-minute frame, which spans several sessions so ATR and swings are warm).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .models import (
    FVG,
    MSS,
    Bias,
    Direction,
    Displacement,
    FVGState,
    LiquidityPool,
    OrderBlock,
    PoolSide,
    Sweep,
    Swing,
)


@dataclass(frozen=True)
class Bars:
    """Immutable OHLCV arrays (positional)."""

    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __len__(self) -> int:
        return len(self.close)

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> "Bars":
        return cls(*(df[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close", "volume")))


# --------------------------------------------------------------------------- #
# Swings (fractals)
# --------------------------------------------------------------------------- #


def find_swings(high: np.ndarray, low: np.ndarray, n: int, end: int | None = None) -> list[Swing]:
    """Fractal swings with ``n`` bars each side.

    A swing high at i needs high[i] > every high in the n bars BEFORE and
    >= every high in the n bars AFTER (so of two equal adjacent highs only the
    first counts). It is only *known* once bar i+n has completed, recorded as
    ``confirmed_index``. Only swings confirmed at or before ``end`` are returned.
    """
    last = len(high) - 1 if end is None else min(end, len(high) - 1)
    if last - n < n:
        return []
    h = np.asarray(high[: last + 1], dtype=float)
    lo = np.asarray(low[: last + 1], dtype=float)
    win_h = np.lib.stride_tricks.sliding_window_view(h, 2 * n + 1)  # row r centred on r + n
    win_l = np.lib.stride_tricks.sliding_window_view(lo, 2 * n + 1)
    centre_h, centre_l = win_h[:, n], win_l[:, n]
    is_high = (centre_h > win_h[:, :n].max(axis=1)) & (centre_h >= win_h[:, n + 1 :].max(axis=1))
    is_low = (centre_l < win_l[:, :n].min(axis=1)) & (centre_l <= win_l[:, n + 1 :].min(axis=1))
    swings: list[Swing] = []
    for r in np.flatnonzero(is_high | is_low):
        i = int(r) + n
        if is_high[r]:
            swings.append(Swing(i, float(h[i]), "high", i + n))
        if is_low[r]:
            swings.append(Swing(i, float(lo[i]), "low", i + n))
    return swings


def swings_known_at(swings: Sequence[Swing], index: int, kind: str | None = None) -> list[Swing]:
    return [s for s in swings if s.confirmed_index <= index and (kind is None or s.kind == kind)]


# --------------------------------------------------------------------------- #
# Liquidity pools
# --------------------------------------------------------------------------- #


def swing_pools(swings: Sequence[Swing], end: int, lookback: int) -> list[LiquidityPool]:
    pools = []
    for s in swings:
        if s.confirmed_index <= end and s.index >= end - lookback:
            side = PoolSide.BUY_SIDE if s.kind == "high" else PoolSide.SELL_SIDE
            pools.append(LiquidityPool(f"swing_{s.kind}", "swing", side, s.price, s.confirmed_index + 1))
    return pools


def equal_level_pools(
    swings: Sequence[Swing], end: int, lookback: int, tolerance: float, min_touches: int
) -> list[LiquidityPool]:
    """Equal highs / lows: clusters of >= ``min_touches`` confirmed swings whose
    prices lie within ``tolerance`` (absolute $, normally k*ATR) of each other.
    The pool sits at the cluster extreme (max of EQH, min of EQL) and becomes
    available after the LAST member is confirmed."""
    pools: list[LiquidityPool] = []
    for kind, side, name in (("high", PoolSide.BUY_SIDE, "EQH"), ("low", PoolSide.SELL_SIDE, "EQL")):
        members = sorted(
            (s for s in swings if s.kind == kind and s.confirmed_index <= end and s.index >= end - lookback),
            key=lambda s: s.price,
        )
        i = 0
        while i < len(members):
            j = i
            while j + 1 < len(members) and members[j + 1].price - members[i].price <= tolerance:
                j += 1
            cluster = members[i : j + 1]
            if len(cluster) >= min_touches:
                price = max(s.price for s in cluster) if kind == "high" else min(s.price for s in cluster)
                avail = max(s.confirmed_index for s in cluster) + 1
                pools.append(LiquidityPool(name, "equal_levels", side, price, avail, touches=len(cluster)))
            i = j + 1
    return pools


def level_pair_pools(name: str, kind: str, high: float | None, low: float | None, available_from: int) -> list[LiquidityPool]:
    """Static high/low pair (prev day, prev week, premarket, opening range)."""
    pools = []
    if high is not None and np.isfinite(high):
        pools.append(LiquidityPool(f"{name}_high", kind, PoolSide.BUY_SIDE, float(high), available_from))
    if low is not None and np.isfinite(low):
        pools.append(LiquidityPool(f"{name}_low", kind, PoolSide.SELL_SIDE, float(low), available_from))
    return pools


# --------------------------------------------------------------------------- #
# Sweeps
# --------------------------------------------------------------------------- #


def detect_sweep(
    bars: Bars,
    pool: LiquidityPool,
    atr: np.ndarray,
    *,
    min_buffer_atr: float,
    min_buffer_abs: float,
    reclaim_within: int,
    start: int,
    end: int,
) -> Sweep | None:
    """First sweep of ``pool`` in [max(start, pool.available_from), end].

    A sweep = a bar trades beyond the pool by >= buffer (max of k*ATR and an
    absolute minimum) and some bar within ``reclaim_within`` bars (counting
    the breach bar itself) CLOSES back inside. The first breach consumes the
    pool: if it does not reclaim in time it was a breakout, not a sweep, and
    None is returned. A breach whose reclaim window is still open at ``end``
    also returns None (it may become a sweep on a later bar).
    """
    first = max(start, pool.available_from)
    buy_side = pool.side is PoolSide.BUY_SIDE
    for j in range(first, end + 1):
        a = atr[j]
        if not np.isfinite(a):
            continue
        buffer = max(min_buffer_atr * a, min_buffer_abs)
        breached = bars.high[j] >= pool.price + buffer if buy_side else bars.low[j] <= pool.price - buffer
        if not breached:
            continue
        last_allowed = j + reclaim_within - 1
        for m in range(j, min(last_allowed, end) + 1):
            inside = bars.close[m] < pool.price if buy_side else bars.close[m] > pool.price
            if inside:
                window = slice(j, m + 1)
                extreme = float(bars.high[window].max() if buy_side else bars.low[window].min())
                return Sweep(pool, j, m, extreme)
        return None  # breakout (or still pending) - pool consumed
    return None


# --------------------------------------------------------------------------- #
# Displacement / MSS
# --------------------------------------------------------------------------- #


def displacement_at(
    bars: Bars, i: int, atr_value: float, *, min_body_atr: float, max_wick_fraction: float
) -> Displacement | None:
    o, h, l, c = bars.open[i], bars.high[i], bars.low[i], bars.close[i]
    rng = h - l
    if not np.isfinite(atr_value) or atr_value <= 0 or rng <= 0:
        return None
    body = abs(c - o)
    wick_fraction = (rng - body) / rng
    body_atr = body / atr_value
    if body_atr < min_body_atr or wick_fraction > max_wick_fraction or c == o:
        return None
    direction = Direction.LONG if c > o else Direction.SHORT
    return Displacement(i, direction, float(body), float(body_atr), float(wick_fraction))


def detect_mss(
    bars: Bars,
    sweep: Sweep,
    swings: Sequence[Swing],
    atr: np.ndarray,
    *,
    min_body_atr: float,
    max_wick_fraction: float,
    max_bars_after_sweep: int,
    end: int,
) -> MSS | None:
    """Market structure shift after a sweep.

    Buy-side sweep -> bearish MSS: a displacement candle CLOSES below the last
    swing low formed before the sweep. Sell-side sweep -> bullish MSS mirror.
    The FIRST close beyond the level decides: if that candle is not a
    displacement candle the structure broke without intent -> no MSS. If
    price exceeds the sweep extreme first, the sweep failed -> no MSS.
    """
    direction = sweep.trade_direction
    want_kind = "low" if direction is Direction.SHORT else "high"
    last = min(end, sweep.sweep_index + max_bars_after_sweep)
    for d in range(sweep.reclaim_index, last + 1):
        # The extreme already covers [sweep_index, reclaim_index]; any later bar
        # trading beyond it means the sweep failed.
        if d > sweep.reclaim_index:
            beyond_extreme = (
                bars.high[d] > sweep.extreme if direction is Direction.SHORT else bars.low[d] < sweep.extreme
            )
            if beyond_extreme:
                return None
        candidates = [
            s for s in swings if s.kind == want_kind and s.index < sweep.sweep_index and s.confirmed_index <= d
        ]
        if not candidates:
            continue
        level = max(candidates, key=lambda s: s.index)
        broke = bars.close[d] < level.price if direction is Direction.SHORT else bars.close[d] > level.price
        if not broke:
            continue
        disp = displacement_at(bars, d, atr[d], min_body_atr=min_body_atr, max_wick_fraction=max_wick_fraction)
        if disp is None or disp.direction is not direction:
            return None
        return MSS(sweep, disp, level)
    return None


# --------------------------------------------------------------------------- #
# Fair value gaps
# --------------------------------------------------------------------------- #


def fvg_at(bars: Bars, i: int, atr_value: float, min_size_atr: float) -> FVG | None:
    """3-candle FVG ending at bar i (known once bar i completes).
    Bullish: low[i] > high[i-2]. Bearish: high[i] < low[i-2]."""
    if i < 2 or not np.isfinite(atr_value):
        return None
    min_size = min_size_atr * atr_value
    if bars.low[i] > bars.high[i - 2] and bars.low[i] - bars.high[i - 2] >= min_size:
        return FVG(i, Direction.LONG, float(bars.high[i - 2]), float(bars.low[i]))
    if bars.high[i] < bars.low[i - 2] and bars.low[i - 2] - bars.high[i] >= min_size:
        return FVG(i, Direction.SHORT, float(bars.high[i]), float(bars.low[i - 2]))
    return None


def find_fvgs(bars: Bars, atr: np.ndarray, min_size_atr: float, start: int, end: int) -> list[FVG]:
    out = []
    for i in range(max(2, start), end + 1):
        gap = fvg_at(bars, i, atr[i], min_size_atr)
        if gap is not None:
            out.append(gap)
    return out


def fvg_state(bars: Bars, fvg: FVG, end: int) -> FVGState:
    """Fill state of ``fvg`` using bars (fvg.index, end]."""
    st = FVGState(fvg)
    for k in range(fvg.index + 1, end + 1):
        if fvg.direction is Direction.LONG:
            low, close = bars.low[k], bars.close[k]
            st.touched |= low <= fvg.top
            st.reached_midpoint |= low <= fvg.midpoint
            st.filled |= low <= fvg.bottom
            st.invalidated |= close < fvg.bottom
        else:
            high, close = bars.high[k], bars.close[k]
            st.touched |= high >= fvg.bottom
            st.reached_midpoint |= high >= fvg.midpoint
            st.filled |= high >= fvg.top
            st.invalidated |= close > fvg.top
    return st


# --------------------------------------------------------------------------- #
# Optional confluence
# --------------------------------------------------------------------------- #


def find_order_block(bars: Bars, mss: MSS, lookback_before_sweep: int = 3) -> OrderBlock | None:
    """Last OPPOSING candle before the displacement candle (bullish candle for
    a bearish MSS and vice versa), searched back to a few bars before the sweep."""
    d = mss.displacement.index
    lo = max(0, mss.sweep.sweep_index - lookback_before_sweep)
    for k in range(d - 1, lo - 1, -1):
        bullish = bars.close[k] > bars.open[k]
        bearish = bars.close[k] < bars.open[k]
        if (mss.direction is Direction.SHORT and bullish) or (mss.direction is Direction.LONG and bearish):
            return OrderBlock(k, mss.direction, float(bars.low[k]), float(bars.high[k]))
    return None


def zones_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return a_low <= b_high and b_low <= a_high


def in_premium_discount(direction: Direction, price: float, range_low: float, range_high: float) -> bool:
    """Longs only in the discount half (<= equilibrium), shorts only in premium (>=)."""
    if range_high <= range_low:
        return False
    eq = (range_high + range_low) / 2.0
    return price <= eq if direction is Direction.LONG else price >= eq


# --------------------------------------------------------------------------- #
# Higher-timeframe bias
# --------------------------------------------------------------------------- #


def structure_bias(high: np.ndarray, low: np.ndarray, n: int, end: int | None = None) -> Bias:
    """Bullish if the last two confirmed swing highs AND lows are rising,
    bearish if both falling, else neutral."""
    swings = find_swings(high, low, n, end)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return Bias.NEUTRAL
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return Bias.BULLISH
    if lh and ll:
        return Bias.BEARISH
    return Bias.NEUTRAL


def ema_bias(close: np.ndarray, ema_values: np.ndarray) -> Bias:
    if len(close) < 2 or not np.isfinite(ema_values[-1]) or not np.isfinite(ema_values[-2]):
        return Bias.NEUTRAL
    if close[-1] > ema_values[-1] and ema_values[-1] > ema_values[-2]:
        return Bias.BULLISH
    if close[-1] < ema_values[-1] and ema_values[-1] < ema_values[-2]:
        return Bias.BEARISH
    return Bias.NEUTRAL


def combine_bias(daily: Bias, hourly: Bias, mode: str) -> Bias:
    if mode == "daily_only":
        return daily
    if mode == "hourly_only":
        return hourly
    if mode == "both_agree":
        return daily if daily == hourly else Bias.NEUTRAL
    if mode == "either":
        if daily == hourly or hourly is Bias.NEUTRAL:
            return daily
        if daily is Bias.NEUTRAL:
            return hourly
        return Bias.NEUTRAL  # conflicting
    raise ValueError(f"unknown bias combine mode {mode!r}")


def bias_allows(bias: Bias, direction: Direction, allow_neutral: bool) -> bool:
    if bias is Bias.NEUTRAL:
        return allow_neutral
    return (bias is Bias.BULLISH) == (direction is Direction.LONG)
