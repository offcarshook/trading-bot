"""Hand-built mechanics tests for the daily volatility breakout."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.strategies import volbreakout as vb  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0, short_borrow_rate=0)
P = dict(vb.SPEC.default_params)  # k=0.5, prior-day range, long only, no trend filter


def _df(rows):
    idx = pd.bdate_range("2020-01-06", periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1e6)


def test_long_stop_fill_and_close_exit():
    # day0 range = 2 -> day1 level = 100 + 0.5*2 = 101; high 103 touches -> entry 101, exit close 102.5
    df = _df([(100, 101, 99, 100), (100, 103, 99.5, 102.5), (102, 102.2, 101.8, 102)])
    t, nb = vb.symbol_trades(df, "SPY", P, 1 / 3)
    assert nb == 0 and len(t) == 1
    r = t.iloc[0]
    assert r.date == df.index[1] and r.entry_price == 101 and r.exit_price == 102.5
    assert r.entry_kind == "stop" and r.exit_kind == "close"
    # day2 range check: level = 102 + 0.5*3.5 -> not touched. No trade on day0 (no prior range).


def test_gap_through_fills_at_open_semantics_and_no_signal_bar_trade():
    # levels always sit above the open, so entry = max(open, level) = level; never trades day 0
    df = _df([(100, 104, 96, 100), (100, 101.9, 99, 101)])  # level 102, high 101.9 -> no fill
    t, _ = vb.symbol_trades(df, "SPY", P, 0.5)
    assert t.empty


def test_both_touched_books_worse_trade_and_short_side():
    p = dict(P, allow_short=True)
    df = _df([(100, 101, 99, 100),
              (100, 101.5, 98.5, 100),   # both touched -> book worse: short@99->100 (-1.01%) vs long@101->100
              (100, 100.5, 98, 98.5)])   # range(prev)=3 -> short level 98.5, low 98 -> short at 98.5, exit 98.5
    t, nb = vb.symbol_trades(df, "SPY", p, 0.5)
    assert nb == 1
    assert list(t.direction) == ["short", "short"]
    assert list(t.entry_price) == [99.0, 98.5]
    # flip close so the long is the worse side
    df2 = _df([(100, 101, 99, 100), (100, 101.5, 98.5, 98.6)])
    t2, nb2 = vb.symbol_trades(df2, "SPY", p, 0.5)
    assert nb2 == 1 and list(t2.direction) == ["long"] and t2.iloc[0].entry_price == 101


def test_both_touched_not_skipped_no_selection_bias():
    # a whipsaw day must still cost money (skipping it would be look-ahead)
    p = dict(P, allow_short=True)
    df = _df([(100, 101, 99, 100), (100, 102, 98, 100)])
    t, _ = vb.symbol_trades(df, "SPY", p, 0.5)
    assert len(t) == 1


def test_trend_filter_blocks_longs_below_sma():
    rows = [(100 - i, 101 - i, 99 - i, 100 - i) for i in range(5)] + [(95, 99, 94.5, 98)]
    p = dict(P, trend_sma=3)
    t, _ = vb.symbol_trades(_df(rows), "SPY", p, 0.5)
    assert t.empty
    t2, _ = vb.symbol_trades(_df(rows), "SPY", P, 0.5)
    assert len(t2) >= 1


def test_costs_reduce_returns_and_flat_overnight_sizes(monkeypatch):
    df = _df([(100, 101, 99, 100), (100, 103, 99.5, 102.5), (102, 102.2, 101.8, 102)])
    data = ResearchData({s: df for s in vb.UNIVERSE})
    b = vb.SPEC.run(data, {}, CostModel())
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)
    a = vb.SPEC.run(data, {}, ZERO)
    assert a.n_trades == 6
    assert np.isclose(a.returns.iloc[1], 2.0 * (102.5 / 101 - 1))
    assert b.returns.sum() < a.returns.sum()
    assert a.trades["size"].sum() <= 2.0 + 1e-9
    assert (a.trades.entry_time == a.trades.exit_time).all()  # same-session exit
