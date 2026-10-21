from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.strategies import orb  # noqa: E402

P = dict(orb.SPEC.default_params, or_minutes=15, stop_frac=1.0, target_r=0.0)


def _day(date, bars):
    """bars: list of (open, high, low, close) starting 09:30 NY, 5-minute spacing."""
    t0 = pd.Timestamp(date).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
    idx = pd.date_range(t0, periods=len(bars), freq="5min")
    df = pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    return df


def _data(intraday):
    daily = {}
    for s, df in intraday.items():
        g = df.groupby(df.index.tz_localize(None).normalize())
        daily[s] = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                                 "close": g["close"].last(), "volume": g["volume"].sum()})
    return ResearchData(daily, intraday)


OR3 = [(100, 101, 99, 100)] * 3  # 15-minute OR: high 101, low 99


def test_long_breakout_gap_fill_and_close_exit():
    bars = OR3 + [(100, 100.8, 99.5, 100.5), (102, 103, 101.8, 102.5), (102.5, 104, 102, 103.5)]
    res = orb.run(_data({"SPY": _day("2020-01-02", bars)}), P, CostModel())
    t = res.trades.iloc[0]
    assert t.direction == "long" and t.entry_price == 102  # gapped over 101 -> fill at bar open
    assert t.entry_time == _day("2020-01-02", bars).index[4]  # first bar after the OR, not an OR bar
    assert t.exit_reason == "close" and t.exit_price == 103.5 and t.exit_kind == "close"
    # risk = 102-99 = 3 (2.94%) -> 1%/2.94% = 0.34 size, below cap 2/3
    assert np.isclose(t["size"], 0.01 / (3 / 102))
    assert res.returns.iloc[0] < res.gross_returns.iloc[0]  # costs reduce returns


def test_no_trade_on_or_bars_and_ambiguous_bar_skipped():
    # OR bars themselves are wide, but no entry; first post-OR bar touches both sides -> skipped
    bars = OR3 + [(100, 101.5, 98.5, 100), (100, 102, 99.5, 101.5)]
    res = orb.run(_data({"SPY": _day("2020-01-02", bars)}), P, CostModel())
    assert res.trades.empty and res.notes["skipped_ambiguous_bar"] == 1


def test_short_stop_wins_when_bar_hits_both_stop_and_target():
    p = dict(P, stop_frac=0.5, target_r=1.0)
    # short entry at 99, stop 99+1=100, target 98; bar 5 touches both 100 and 98 -> stop
    bars = OR3 + [(99.5, 99.6, 98.9, 99.2), (99.2, 100.2, 97.5, 98.0), (98, 98, 90, 90)]
    t = orb.run(_data({"QQQ": _day("2020-01-02", bars)}), p, CostModel()).trades.iloc[0]
    assert t.direction == "short" and t.entry_price == 99
    assert t.exit_reason == "stop" and t.exit_price == 100 and t.exit_kind == "stop"


def test_target_hit_and_one_trade_per_day_flat_each_day():
    p = dict(P, target_r=1.5)
    d1 = OR3 + [(100.5, 101.2, 100.4, 101.1), (101.1, 104.2, 101, 104), (104, 104, 98, 98.5)]
    d2 = OR3 + [(100, 100.5, 99.5, 100)]  # early close-ish short day, no breakout
    df = pd.concat([_day("2020-01-02", d1), _day("2020-01-03", d2)])
    res = orb.run(_data({"IWM": df}), p, CostModel())
    assert len(res.trades) == 1
    t = res.trades.iloc[0]
    assert t.exit_reason == "target" and np.isclose(t.exit_price, 101 + 1.5 * 2)
    assert t.exit_time.date() == t.entry_time.date()


def test_trend_filter_blocks_long_without_history():
    p = dict(P, trend_filter=True)
    bars = OR3 + [(100.5, 102, 100.4, 101.5)]
    res = orb.run(_data({"SPY": _day("2020-01-02", bars)}), p, CostModel())
    assert res.trades.empty
