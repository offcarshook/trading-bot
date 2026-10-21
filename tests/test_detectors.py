"""Synthetic-candle tests for every ICT detector."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import bars_from_ohlc, flat_rows
from ictbot import ict_detectors as det
from ictbot.indicators import atr
from ictbot.models import Bias, Direction, LiquidityPool, PoolSide


# --------------------------------------------------------------------------- #
# Swings
# --------------------------------------------------------------------------- #


def test_swing_high_and_low_with_confirmation_index():
    highs = np.array([10, 11, 12, 15, 12, 11, 10, 9, 10, 11], dtype=float)
    lows = highs - 1
    lows[7] = 5  # deep swing low at 7
    swings = det.find_swings(highs, lows, n=2)
    sh = [s for s in swings if s.kind == "high"]
    sl = [s for s in swings if s.kind == "low"]
    assert [(s.index, s.price, s.confirmed_index) for s in sh] == [(3, 15.0, 5)]
    assert [(s.index, s.price, s.confirmed_index) for s in sl] == [(7, 5.0, 9)]


def test_swing_not_known_before_confirmation_no_lookahead():
    highs = np.array([10, 11, 12, 15, 12, 11, 10], dtype=float)
    lows = highs - 1
    assert [s for s in det.find_swings(highs, lows, 2, end=4) if s.kind == "high"] == []
    assert [s.index for s in det.find_swings(highs, lows, 2, end=5) if s.kind == "high"] == [3]


def test_equal_adjacent_highs_count_once():
    highs = np.array([10, 11, 15, 15, 11, 10, 9], dtype=float)
    swings = [s for s in det.find_swings(highs, highs - 1, 2) if s.kind == "high"]
    assert [s.index for s in swings] == [2]


def test_equal_level_pool_cluster():
    highs = np.array([10, 12, 10, 9, 10, 12.04, 10, 9, 10, 11.0, 10, 9], dtype=float)
    swings = det.find_swings(highs, highs - 1, 1)
    pools = det.equal_level_pools(swings, end=11, lookback=50, tolerance=0.05, min_touches=2)
    eqh = [p for p in pools if p.name == "EQH"]
    assert len(eqh) == 1
    assert eqh[0].price == pytest.approx(12.04)
    assert eqh[0].touches == 2
    assert eqh[0].side is PoolSide.BUY_SIDE
    assert eqh[0].available_from == 7  # last member (index 5) confirmed at 6 -> usable from 7


# --------------------------------------------------------------------------- #
# Sweeps
# --------------------------------------------------------------------------- #


def _bsl(price=101.0, avail=0):
    return LiquidityPool("PD_high", "prev_day", PoolSide.BUY_SIDE, price, avail)


def _ssl(price=99.0, avail=0):
    return LiquidityPool("PD_low", "prev_day", PoolSide.SELL_SIDE, price, avail)


SWEEP_KW = dict(min_buffer_atr=0.05, min_buffer_abs=0.02, reclaim_within=2)


def test_buy_side_sweep_reclaimed_next_bar_records_extreme():
    rows = flat_rows(15) + [(100.8, 101.40, 100.7, 101.2), (101.2, 101.25, 100.5, 100.6)]
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    sw = det.detect_sweep(b, _bsl(), a, start=0, end=len(b) - 1, **SWEEP_KW)
    assert sw is not None
    assert (sw.sweep_index, sw.reclaim_index) == (15, 16)
    assert sw.extreme == pytest.approx(101.40)
    assert sw.trade_direction is Direction.SHORT


def test_breakout_without_reclaim_is_not_a_sweep():
    rows = flat_rows(15) + [(100.8, 101.4, 100.7, 101.3), (101.3, 101.6, 101.2, 101.5), (101.5, 101.7, 100.0, 100.5)]
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    # reclaim happens on the 3rd bar, outside k=2 -> pool consumed by a breakout
    assert det.detect_sweep(b, _bsl(), a, start=0, end=len(b) - 1, **SWEEP_KW) is None


def test_poke_smaller_than_buffer_is_ignored():
    rows = flat_rows(15) + [(100.8, 101.01, 100.7, 100.9)]
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    assert det.detect_sweep(b, _bsl(), a, start=0, end=len(b) - 1, **SWEEP_KW) is None


def test_sweep_pending_until_reclaim_bar_completes():
    rows = flat_rows(15) + [(100.8, 101.4, 100.7, 101.3), (101.3, 101.35, 100.4, 100.5)]
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    assert det.detect_sweep(b, _bsl(), a, start=0, end=15, **SWEEP_KW) is None  # not knowable yet
    sw = det.detect_sweep(b, _bsl(), a, start=0, end=16, **SWEEP_KW)
    assert sw is not None and sw.reclaim_index == 16


def test_sell_side_sweep_mirror():
    rows = flat_rows(15) + [(99.2, 99.3, 98.6, 99.1)]
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    sw = det.detect_sweep(b, _ssl(), a, start=0, end=15, **SWEEP_KW)
    assert sw is not None
    assert sw.extreme == pytest.approx(98.6)
    assert sw.trade_direction is Direction.LONG


def test_pool_not_available_yet_cannot_be_swept():
    rows = flat_rows(15) + [(100.8, 101.4, 100.7, 100.9)]
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    assert det.detect_sweep(b, _bsl(avail=16), a, start=0, end=15, **SWEEP_KW) is None


# --------------------------------------------------------------------------- #
# Displacement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bar,expected",
    [
        ((100.0, 100.05, 98.9, 98.95), Direction.SHORT),  # body 1.05 = 2.1 ATR, tiny wicks
        ((100.0, 101.10, 99.95, 101.05), Direction.LONG),
        ((100.0, 100.9, 98.9, 99.4), None),  # long upper wick
        ((100.0, 100.2, 99.6, 99.7), None),  # body too small
    ],
)
def test_displacement(bar, expected):
    b = bars_from_ohlc([bar])
    d = det.displacement_at(b, 0, 0.5, min_body_atr=1.2, max_wick_fraction=0.35)
    assert (d.direction if d else None) is expected


# --------------------------------------------------------------------------- #
# MSS
# --------------------------------------------------------------------------- #


def _mss_rows(displacement_bar):
    rows = flat_rows(14)
    rows += [
        (100.0, 100.3, 99.8, 100.2),
        (100.2, 100.4, 99.9, 100.1),
        (100.1, 100.2, 99.5, 99.7),  # 16: swing low 99.5
        (99.7, 100.3, 99.6, 100.2),
        (100.2, 100.6, 100.1, 100.5),
        (100.5, 100.9, 100.4, 100.8),
        (100.8, 101.3, 100.7, 100.9),  # 20: sweeps 101.0, closes back inside
        displacement_bar,  # 21
    ]
    return rows


def _run_mss(rows, end=None):
    b = bars_from_ohlc(rows)
    a = atr(b.high, b.low, b.close, 14)
    end = len(b) - 1 if end is None else end
    sw = det.detect_sweep(b, _bsl(avail=14), a, start=14, end=end, **SWEEP_KW)
    assert sw is not None
    swings = det.find_swings(b.high, b.low, 2, end=end)
    return det.detect_mss(b, sw, swings, a, min_body_atr=1.2, max_wick_fraction=0.35, max_bars_after_sweep=12, end=end)


def test_bearish_mss_on_displacement_close_below_swing_low():
    mss = _run_mss(_mss_rows((100.9, 100.95, 99.2, 99.3)))
    assert mss is not None
    assert mss.direction is Direction.SHORT
    assert mss.broken_swing.price == pytest.approx(99.5)
    assert mss.index == 21


def test_structure_break_without_displacement_is_rejected():
    # closes below 99.5 but with a huge lower wick -> not displacement
    assert _run_mss(_mss_rows((100.9, 100.95, 98.0, 99.4))) is None


def test_new_high_beyond_sweep_extreme_invalidates():
    rows = _mss_rows((100.9, 101.5, 100.6, 100.8))  # trades above 101.3
    rows.append((100.8, 100.85, 99.0, 99.1))
    assert _run_mss(rows) is None


# --------------------------------------------------------------------------- #
# FVG
# --------------------------------------------------------------------------- #


def test_bullish_and_bearish_fvg_with_size_filter():
    bull = bars_from_ohlc([(100, 100.5, 99.8, 100.4), (100.4, 101.5, 100.3, 101.4), (101.4, 101.8, 100.9, 101.7)])
    g = det.fvg_at(bull, 2, 0.5, 0.1)
    assert g is not None and g.direction is Direction.LONG
    assert (g.bottom, g.top) == (100.5, 100.9)
    assert g.midpoint == pytest.approx(100.7)
    assert g.entry_edge() == 100.9
    assert det.fvg_at(bull, 2, 0.5, 1.0) is None  # 0.4 gap < 1.0*ATR

    bear = bars_from_ohlc([(101, 101.2, 100.6, 100.7), (100.7, 100.8, 99.5, 99.6), (99.6, 100.1, 99.3, 99.4)])
    g = det.fvg_at(bear, 2, 0.5, 0.1)
    assert g is not None and g.direction is Direction.SHORT
    assert (g.bottom, g.top) == (100.1, 100.6)


def test_overlapping_candles_have_no_fvg():
    b = bars_from_ohlc([(100, 100.5, 99.8, 100.4), (100.4, 100.9, 100.3, 100.8), (100.8, 101.0, 100.4, 100.9)])
    assert det.fvg_at(b, 2, 0.5, 0.0) is None


def test_fvg_fill_state_tracking():
    rows = [
        (100, 100.5, 99.8, 100.4),
        (100.4, 101.5, 100.3, 101.4),
        (101.4, 101.8, 100.9, 101.7),  # gap 100.5-100.9
        (101.7, 101.8, 100.85, 101.0),  # touches top only
        (101.0, 101.1, 100.65, 100.8),  # reaches midpoint 100.7
        (100.8, 100.9, 100.3, 100.4),  # fills + closes below bottom -> invalidated
    ]
    b = bars_from_ohlc(rows)
    g = det.fvg_at(b, 2, 0.5, 0.1)
    s3 = det.fvg_state(b, g, 3)
    assert s3.touched and not s3.reached_midpoint
    s4 = det.fvg_state(b, g, 4)
    assert s4.reached_midpoint and not s4.filled
    s5 = det.fvg_state(b, g, 5)
    assert s5.filled and s5.invalidated


# --------------------------------------------------------------------------- #
# Confluence and bias
# --------------------------------------------------------------------------- #


def test_order_block_is_last_opposing_candle():
    rows = _mss_rows((100.9, 100.95, 99.2, 99.3))
    b = bars_from_ohlc(rows)
    mss = _run_mss(rows)
    ob = det.find_order_block(b, mss)
    assert ob is not None and ob.index == 20  # bullish sweep candle right before the down move
    assert (ob.low, ob.high) == (100.7, 101.3)


def test_premium_discount():
    assert det.in_premium_discount(Direction.LONG, 99.0, 98.0, 102.0)
    assert not det.in_premium_discount(Direction.LONG, 101.0, 98.0, 102.0)
    assert det.in_premium_discount(Direction.SHORT, 101.0, 98.0, 102.0)
    assert not det.in_premium_discount(Direction.SHORT, 99.0, 98.0, 102.0)


def test_structure_bias():
    up_h = np.array([10, 12, 11, 10, 11, 14, 12, 11, 12, 16, 14, 13], dtype=float)
    up_l = up_h - 1
    assert det.structure_bias(up_h, up_l, 1) is Bias.BULLISH
    assert det.structure_bias(30 - up_l, 30 - up_h, 1) is Bias.BEARISH  # vertical mirror
    assert det.combine_bias(Bias.BULLISH, Bias.BEARISH, "both_agree") is Bias.NEUTRAL
    assert det.combine_bias(Bias.BULLISH, Bias.NEUTRAL, "either") is Bias.BULLISH
    assert det.bias_allows(Bias.BEARISH, Direction.LONG, allow_neutral=True) is False
    assert det.bias_allows(Bias.NEUTRAL, Direction.LONG, allow_neutral=True) is True


def test_atr_is_causal():
    rows = flat_rows(20)
    b = bars_from_ohlc(rows)
    a1 = atr(b.high, b.low, b.close, 14)
    rows2 = rows + [(100, 110, 90, 100)]
    b2 = bars_from_ohlc(rows2)
    a2 = atr(b2.high, b2.low, b2.close, 14)
    np.testing.assert_allclose(a1, a2[:-1])  # adding a future bar changes nothing in the past
