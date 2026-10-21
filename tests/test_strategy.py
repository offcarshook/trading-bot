"""End-to-end setup search on a synthetic day + look-ahead / time-filter tests."""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from conftest import DAY0, DAY1, flat_rows, frame_5m, session
from ictbot.config import BotConfig
from ictbot.data import aggregate_session, daily_from_minutes
from ictbot.indicators import atr
from ictbot.models import Direction
from ictbot.strategy import (
    EntryPlan,
    SymbolFrames,
    build_frames,
    entry_window_open,
    find_setups,
    pending_entry_action,
    round_to_tick,
)
from ictbot.timeutils import NY, ny_dt

# Previous day: range 97.0 - 101.0 -> PDH 101.0, PDL 97.0
DAY0_ROWS = flat_rows(20)
DAY0_ROWS[2] = (100.0, 100.25, 97.0, 100.0)
DAY0_ROWS[5] = (100.0, 101.0, 99.75, 100.0)

TODAY_ROWS = [
    (100.0, 100.4, 99.8, 100.2),
    (100.2, 100.5, 100.0, 100.4),
    (100.4, 100.5, 99.6, 99.8),  # swing low 99.6
    (99.8, 100.3, 99.7, 100.2),
    (100.2, 100.6, 100.1, 100.5),
    (100.5, 100.9, 100.4, 100.8),
    (100.8, 101.3, 100.7, 100.9),  # sweeps PDH 101.0 and closes back inside
    (100.9, 100.95, 99.3, 99.4),  # bearish displacement below 99.6 -> MSS
    (99.4, 99.5, 98.8, 98.9),  # completes bearish FVG 99.5 - 100.7
]


def make_frames(today_rows=TODAY_ROWS) -> SymbolFrames:
    prev = frame_5m(DAY0_ROWS, DAY0)
    today = frame_5m(today_rows, DAY1)
    bars5 = pd.concat([prev, today])
    daily = pd.DataFrame(
        [{"open": 100.0, "high": 101.0, "low": 97.0, "close": 100.0, "volume": 1e5}], index=[DAY0]
    )
    return SymbolFrames("SPY", session(DAY1), bars5, bars5.iloc[:0], daily, {}, today_start=len(prev))


def test_short_setup_after_pdh_sweep_mss_fvg(cfg: BotConfig):
    res = find_setups(make_frames(), cfg)
    assert len(res.setups) == 1, res.records
    s = res.setups[0]
    assert s.direction is Direction.SHORT
    assert s.sweep.pool.name == "PD_high"
    assert (s.fvg.bottom, s.fvg.top) == (99.5, 100.7)
    assert s.entry == pytest.approx(100.1)  # consequent encroachment
    b = make_frames().bars5
    a = atr(b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy(), 14)[s.confirm_index]
    assert s.stop == round_to_tick(101.3 + 0.1 * a, 0.01, "up")
    assert s.target == pytest.approx(97.0)
    assert s.target_pool == "PD_low"
    assert s.reward_risk >= cfg.execution.min_reward_risk
    assert "htf_pool_swept" in s.tags and "order_block" in s.tags
    assert s.score >= cfg.ict.scoring.min_score


def test_setup_id_is_deterministic(cfg: BotConfig):
    a = find_setups(make_frames(), cfg).setups[0].setup_id
    b = find_setups(make_frames(), cfg).setups[0].setup_id
    assert a == b


def test_min_rr_filter_skips_setup(cfg: BotConfig):
    strict = dataclasses.replace(cfg, execution=dataclasses.replace(cfg.execution, min_reward_risk=5.0))
    res = find_setups(make_frames(), strict)
    assert res.setups == []
    assert any(r.reason == "reward_risk_below_min" for r in res.records)


def test_setup_not_offered_once_entry_already_traded(cfg: BotConfig):
    rows = TODAY_ROWS + [(98.9, 100.2, 98.8, 99.9)]  # retraces through the midpoint
    res = find_setups(make_frames(rows), cfg)
    assert res.setups == []
    assert any(r.reason == "entry_already_traded" for r in res.records)


def test_stale_setup_is_ignored(cfg: BotConfig):
    rows = TODAY_ROWS + [(98.9, 99.0, 98.85, 98.95)] * (cfg.ict.fvg.max_setup_age_bars + 1)
    assert find_setups(make_frames(rows), cfg).setups == []


def test_premium_discount_requirement(cfg: BotConfig):
    # Shallow displacement leg: CE ends up in the discount half -> no short
    rows = TODAY_ROWS[:-1] + [(99.4, 99.5, 99.3, 99.35)]
    res = find_setups(make_frames(rows), cfg)
    assert res.setups == []
    assert [r.reason for r in res.records] == ["entry_not_in_premium_discount"]


def test_no_lookahead_in_frame_building(cfg: BotConfig):
    """1m bars beyond `asof` - or inside the still-forming 5m bar - are never used."""
    sess = session(DAY1)
    idx = pd.date_range(sess.open, periods=60, freq="1min", tz=NY)
    prices = np.linspace(100, 101, 60)
    m1 = pd.DataFrame({"open": prices, "high": prices + 0.05, "low": prices - 0.05, "close": prices, "volume": 100.0}, index=idx)
    asof = ny_dt(DAY1, dt.time(10, 2, 30))
    fr = build_frames("SPY", m1, [session(DAY0), sess], asof, cfg)
    assert fr.bars5.index[-1] == ny_dt(DAY1, dt.time(9, 55))  # 10:00 bar still forming
    # identical frames whether or not future data is present in the input
    fr2 = build_frames("SPY", m1[m1.index < asof], [session(DAY0), sess], asof, cfg)
    pd.testing.assert_frame_equal(fr.bars5, fr2.bars5)
    # completion delay: at 10:00:05 the 9:55 bar is NOT yet considered complete
    fr3 = build_frames("SPY", m1, [session(DAY0), sess], ny_dt(DAY1, dt.time(10, 0, 5)), cfg)
    assert fr3.bars5.index[-1] == ny_dt(DAY1, dt.time(9, 50))


def test_backtest_precomputed_frames_identical_to_incremental(cfg: BotConfig):
    from ictbot.data import aggregate_session as agg

    sess = session(DAY1)
    idx = pd.date_range(sess.open, periods=120, freq="1min", tz=NY)
    px = 100 + np.sin(np.arange(120) / 7.0)
    m1 = pd.DataFrame({"open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 50.0}, index=idx)
    full = (agg(m1, sess, 5), agg(m1, sess, 60))
    for minute in (7, 35, 60, 61, 119):
        asof = sess.open + dt.timedelta(minutes=minute)
        a = build_frames("SPY", m1, [session(DAY0), sess], asof, cfg, delay_s=0)
        b = build_frames("SPY", m1, [session(DAY0), sess], asof, cfg, delay_s=0, today_full=full)
        pd.testing.assert_frame_equal(a.bars5, b.bars5)
        pd.testing.assert_frame_equal(a.bars1h, b.bars1h)


def test_aggregation_ohlcv_and_daily(cfg: BotConfig):
    sess = session(DAY1)
    idx = pd.date_range(sess.open, periods=10, freq="1min", tz=NY)
    m1 = pd.DataFrame(
        {"open": range(10), "high": [x + 0.5 for x in range(10)], "low": [x - 0.5 for x in range(10)], "close": [x + 0.25 for x in range(10)], "volume": 1.0},
        index=idx,
        dtype=float,
    )
    b5 = aggregate_session(m1, sess, 5)
    assert list(b5["open"]) == [0, 5]
    assert list(b5["high"]) == [4.5, 9.5]
    assert list(b5["low"]) == [-0.5, 4.5]
    assert list(b5["close"]) == [4.25, 9.25]
    assert list(b5["volume"]) == [5, 5]
    d = daily_from_minutes(m1, [sess])
    assert d.loc[DAY1, "high"] == 9.5 and d.loc[DAY1, "low"] == -0.5


def test_premarket_bars_excluded_from_rth_frames(cfg: BotConfig):
    sess = session(DAY1)
    pre = pd.date_range(ny_dt(DAY1, dt.time(8, 0)), periods=30, freq="1min", tz=NY)
    rth = pd.date_range(sess.open, periods=30, freq="1min", tz=NY)
    m1 = pd.DataFrame({"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 10.0}, index=pre.append(rth))
    m1.loc[pre, "high"] = 150.0  # absurd premarket print must not leak into RTH bars
    fr = build_frames("SPY", m1, [session(DAY0), sess], ny_dt(DAY1, dt.time(10, 1)), cfg)
    assert fr.bars5["high"].max() == pytest.approx(100.1)
    assert fr.premarket["premarket"][0] == 150.0  # ...but is available as a liquidity level


@pytest.mark.parametrize(
    "hhmm,ok,reason",
    [
        ((9, 25), False, "outside_regular_session"),
        ((9, 35), True, "ok"),
        ((10, 59), True, "ok"),
        ((11, 0), False, "outside_kill_zones"),
        ((15, 40), False, "too_close_to_close"),
    ],
)
def test_entry_window(cfg: BotConfig, hhmm, ok, reason):
    ts = ny_dt(DAY1, dt.time(*hhmm))
    assert entry_window_open(ts, session(DAY1), cfg) == (ok, reason)


def test_entry_window_blocks_early_close_day(cfg: BotConfig):
    early = session(DAY1).__class__(DAY1, ny_dt(DAY1, dt.time(9, 30)), ny_dt(DAY1, dt.time(13, 0)))
    assert entry_window_open(ny_dt(DAY1, dt.time(9, 45)), early, cfg) == (False, "early_close_day")


def test_entry_window_dst_winter(cfg: BotConfig):
    winter = dt.date(2025, 1, 15)
    sess = session(winter)
    assert sess.open.utcoffset() == dt.timedelta(hours=-5)
    assert session(DAY1).open.utcoffset() == dt.timedelta(hours=-4)
    assert entry_window_open(ny_dt(winter, dt.time(9, 40)), sess, cfg)[0]


def test_pending_entry_rules(cfg: BotConfig):
    s = EntryPlan.from_setup(find_setups(make_frames(), cfg).setups[0])
    assert EntryPlan.from_dict(s.to_dict()) == s
    keep = pd.Series({"open": 99.0, "high": 99.6, "low": 98.9, "close": 99.2})
    assert pending_entry_action(s, keep, 1, cfg) is None
    assert pending_entry_action(s, keep, cfg.ict.fvg.order_expiry_bars, cfg) == "expired"
    through = pd.Series({"open": 100.0, "high": 100.9, "low": 99.9, "close": 100.8})
    assert pending_entry_action(s, through, 1, cfg) == "fvg_invalidated"
    tgt = pd.Series({"open": 98.0, "high": 98.1, "low": 96.9, "close": 97.5})
    assert pending_entry_action(s, tgt, 1, cfg) == "target_hit_before_fill"
