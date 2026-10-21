"""Hand-built mechanics tests for the regime-filtered mean-reversion strategy."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData, grid  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.data import synthetic_data  # noqa: E402
from ictbot.research.strategies import meanrev  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0, short_borrow_rate=0)
P = dict(meanrev.SPEC.default_params)  # rsi2 / loose (RSI<10) / sma5 exit / max_hold 5 / long only / gross 1
D = 250  # index of the signal bar in the hand-built series (> 200 so the regime SMA exists)


def _zero_spread(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)


def _frame(closes, highs=None, lows=None, pad=0.004):
    c = np.asarray(closes, float)
    o = np.concatenate(([c[0]], 0.5 * (c[:-1] + c[1:])))  # open between the two closes -> gap != 0
    h = np.maximum(o, c) * (1 + pad) if highs is None else np.asarray(highs, float)
    lo = np.minimum(o, c) * (1 - pad) if lows is None else np.asarray(lows, float)
    idx = pd.bdate_range("2019-01-01", periods=len(c))
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": 1e6}, index=idx)


def _trend(n=D, step=0.002, start=100.0):
    return list(start * (1 + step) ** np.arange(n))


def _then(path, rets):
    out = list(path)
    for r in rets:
        out.append(out[-1] * (1 + r))
    return out


def _run(df, costs=ZERO, **kw):
    return meanrev.run(ResearchData({"SPY": df}), dict(P, **kw), costs)


def test_rsi2_entry_fills_next_open_and_exits_next_open_after_sma5(monkeypatch):
    _zero_spread(monkeypatch)
    df = _frame(_then(_trend(), [-0.03, -0.01, 0.025, 0.025] + [0.002] * 10))
    res = _run(df, max_hold=10)
    w, r, c, o = res.weights["SPY"], res.returns, df["close"], df["open"]
    assert (w.iloc[:D] == 0).all(), "uptrend with RSI(2)=100 must not trigger"
    assert w.iloc[D] == 1.0, "-3% close in a bull regime -> long decided at that close"
    sma5 = c.rolling(5).mean()
    exit_t = next(t for t in range(D + 1, len(df)) if c.iloc[t] > sma5.iloc[t])
    assert (w.iloc[D:exit_t] == 1.0).all() and (w.iloc[exit_t:] == 0).all()
    # no trading on the signal bar: the -3% day is not captured
    assert r.iloc[D] == 0.0
    # bought at the NEXT open: first day earns only open->close
    assert r.iloc[D + 1] == pytest.approx(c.iloc[D + 1] / o.iloc[D + 1] - 1)
    # exit decided at exit_t's close, sold at the next open: only the overnight gap is earned
    assert r.iloc[exit_t + 1] == pytest.approx(o.iloc[exit_t + 1] / c.iloc[exit_t] - 1)
    assert (r.iloc[exit_t + 2:] == 0).all()
    assert res.notes["round_trips"] == 1


def test_regime_filter_blocks_longs_in_downtrend_and_short_side_mirrors(monkeypatch):
    _zero_spread(monkeypatch)
    dip = _frame(_then(_trend(step=-0.002), [-0.03, -0.01, 0.025, 0.025] + [-0.002] * 10))
    assert (_run(dip).weights["SPY"] == 0).all(), "oversold below the 200d SMA must not buy"
    assert (_run(dip, allow_short=True).weights["SPY"] == 0).all(), "oversold is not a short signal"

    spike = _frame(_then(_trend(step=-0.002), [0.03] + [-0.002] * 12))
    assert (_run(spike).weights["SPY"] == 0).all(), "long-only run must stay flat"
    res = _run(spike, allow_short=True)
    w, c, o = res.weights["SPY"], spike["close"], spike["open"]
    assert (w.iloc[:D] == 0).all() and w.iloc[D] == -1.0
    sma5 = c.rolling(5).mean()
    exit_t = next(t for t in range(D + 1, len(spike)) if c.iloc[t] < sma5.iloc[t])
    assert (w.iloc[D:exit_t] == -1.0).all() and (w.iloc[exit_t:] == 0).all()
    assert res.returns.iloc[D] == 0.0
    assert res.returns.iloc[D + 1] == pytest.approx(-(c.iloc[D + 1] / o.iloc[D + 1] - 1))


def test_time_stop_exits_after_max_hold_and_does_not_rebuy_persistent_washout(monkeypatch):
    _zero_spread(monkeypatch)
    # crash then a steady grind lower: RSI(2) stays < 10 and close stays below its 5d SMA
    df = _frame(_then(_trend(), [-0.04] + [-0.003] * 14 + [0.01] * 6))
    for hold in (5, 10):
        w = _run(df, max_hold=hold).weights["SPY"]
        assert (w.iloc[D:D + hold] == 1.0).all(), hold
        assert (w.iloc[D + hold:] == 0).all(), f"max_hold={hold}: must exit and not re-enter while the signal persists"
    # the RSI(2) > 70 exit fires on the first strong up close (day D+15) instead
    w = _run(df, exit_rule="rsi2", max_hold=30).weights["SPY"]
    assert (w.iloc[D:D + 15] == 1.0).all() and w.iloc[D + 15] == 0.0
    r2 = meanrev.rsi(df["close"], 2)
    assert r2.iloc[D + 14] < 70 < r2.iloc[D + 15]


def test_time_stop_rearms_when_signal_already_off():
    le = np.zeros(12, bool)
    le[[1, 7, 8]] = True  # signal at 1; off on the time-stop bar 6; fresh signal at 7
    sig = {"long_entry": le, "short_entry": np.zeros(12, bool), "exit_long": np.zeros(12, bool), "exit_short": np.zeros(12, bool)}
    pos, holds = meanrev.positions(sig, max_hold=5)
    assert pos.tolist() == [0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1]
    assert holds == [5, 4]
    le[6] = True  # still oversold on the time-stop bar -> blocked until it switches off (bar 9)
    le[9] = False
    le[10] = True
    pos, _ = meanrev.positions(sig, max_hold=5)
    assert pos.tolist() == [0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1]


def test_ibs_thresholds_and_exit_not_checked_on_entry_bar(monkeypatch):
    _zero_spread(monkeypatch)
    closes = _trend(D + 10)
    df = _frame(closes)
    c = df["close"].to_numpy()
    df.loc[df.index[D], ["low", "high"]] = [c[D] * (1 - 0.0015), c[D] * (1 + 0.0085)]  # IBS = 0.15
    assert meanrev.ibs(df).iloc[D] == pytest.approx(0.15)
    assert (meanrev.ibs(df).drop(df.index[D]).dropna() > 0.3).all()
    strict = _run(df, signal="ibs", threshold="strict").weights["SPY"]
    assert (strict == 0).all(), "IBS 0.15 is not below the strict 0.10 threshold"
    res = _run(df, signal="ibs", threshold="loose")
    w = res.weights["SPY"]
    # entry decided at D (close above SMA5 on D itself does NOT exit), exit decided at D+1
    assert w.iloc[D] == 1.0 and w.iloc[D + 1] == 0.0 and (w.drop(w.index[D]) == 0).all()
    assert res.returns.iloc[D + 1] == pytest.approx(df["close"].iloc[D + 1] / df["open"].iloc[D + 1] - 1)
    assert res.returns.iloc[D + 2] == pytest.approx(df["open"].iloc[D + 2] / df["close"].iloc[D + 1] - 1)


def test_consecutive_down_closes(monkeypatch):
    _zero_spread(monkeypatch)
    df = _frame(_then(_trend(), [-0.001] * 3 + [0.002] * 8))
    loose = _run(df, signal="down_days", threshold="loose").weights["SPY"]
    assert (loose.iloc[:D + 2] == 0).all() and loose.iloc[D + 2] == 1.0, "3rd lower close -> entry"
    assert (_run(df, signal="down_days", threshold="strict").weights["SPY"] == 0).all(), "needs 4 lower closes"
    np.testing.assert_array_equal(meanrev.run_length(pd.Series([True, True, False, True, True, True, False])).to_numpy(),
                                  [1, 2, 0, 1, 2, 3, 0])


def test_vol_filter_blocks_entries_when_realized_vol_is_high(monkeypatch):
    _zero_spread(monkeypatch)
    calm = [0.005, -0.003] * 200  # 400 calm days, drifting up
    wild = [-0.025, 0.03] * 10  # 20 high-vol days ending on an up close, still drifting up (bull regime holds)
    df = _frame(_then([100.0], calm + wild + [-0.01] * 3 + [0.01] * 5))
    t = 1 + len(calm) + len(wild) + 2  # bar of the 3rd lower close
    off = _run(df, signal="down_days", threshold="loose", vol_filter=False).weights["SPY"]
    assert off.iloc[t] == 1.0 and (off.iloc[:t] == 0).all()
    on = _run(df, signal="down_days", threshold="loose", vol_filter=True).weights["SPY"]
    assert (on == 0).all(), "20d vol far above its trailing 1y 80th percentile -> no entry"


def test_costs_reduce_returns_on_entry_and_exit():
    df = _frame(_then(_trend(), [-0.03, -0.01, 0.025, 0.025] + [0.002] * 10))
    res = _run(df, CostModel(), max_hold=10)
    c, o = df["close"], df["open"]
    entry_cost = (0.5 + 1.0) / 1e4  # SPY half-spread + open slippage on 100% of equity
    assert res.returns.iloc[D + 1] == pytest.approx((1 - entry_cost) * (c.iloc[D + 1] / o.iloc[D + 1]) - 1, abs=1e-12)
    assert res.costs.iloc[D + 1] == pytest.approx(entry_cost)
    assert (res.returns <= res.gross_returns + 1e-15).all()
    assert res.returns.sum() < res.gross_returns.sum()
    assert res.n_trades == 2  # one buy + one sell: the band suppresses drift re-balancing
    stressed = _run(df, CostModel().stressed(2.0), max_hold=10)
    assert stressed.returns.sum() < res.returns.sum()


def test_equal_budget_missing_symbols_and_bars_and_gross_cap():
    d = synthetic_data(["SPY", "IWM", "TLT"], start="2016-01-04", end="2018-12-31", seed=5)
    d.daily["IWM"] = d.daily["IWM"].drop(d.daily["IWM"].index[[300, 301, 450]])  # missing bars
    res = meanrev.run(d, dict(P, signal="ibs"), CostModel())
    assert list(res.weights.columns) == ["SPY", "IWM"]
    assert res.notes["per_symbol_weight"] == 0.5
    assert set(np.round(np.unique(res.weights.to_numpy()), 12)) <= {0.0, 0.5}
    assert np.isfinite(res.returns).all() and res.n_trades > 0
    capped = meanrev.run(d, dict(P, gross=5.0), CostModel())
    assert capped.notes["per_symbol_weight"] == pytest.approx(meanrev.MAX_GROSS / 2)
    none = meanrev.run(ResearchData({"TLT": d.daily["TLT"]}), P, CostModel())
    assert none.n_trades == 0 and (none.returns == 0).all()


@pytest.mark.parametrize("signal", ["rsi2", "ibs", "down_days"])
def test_no_lookahead_including_short_side_and_vol_filter(signal):
    data = synthetic_data(meanrev.UNIVERSE, start="2016-01-04", end="2018-06-29", seed=13)
    cutoff = pd.Timestamp("2017-10-31")
    p = dict(P, signal=signal, allow_short=True, vol_filter=True, max_hold=10)
    full = meanrev.run(data, p, CostModel())
    part = meanrev.run(data.truncate(cutoff), p, CostModel())
    a = full.returns[full.returns.index <= cutoff]
    np.testing.assert_allclose(a.to_numpy(), part.returns.reindex(a.index).to_numpy(), atol=1e-12)
    wa = full.weights[full.weights.index <= cutoff]
    np.testing.assert_allclose(wa.to_numpy(), part.weights.reindex(wa.index).to_numpy(), atol=1e-12)
    assert (full.weights < 0).any().any(), "short side should be exercised by this test"


def test_grid_is_preregistered_and_small():
    spec = meanrev.SPEC
    n = len(grid(spec.param_grid))
    assert 12 <= n <= 150
    assert all(k in spec.param_grid and spec.default_params[k] in spec.param_grid[k] for k in spec.default_params)
    assert max(spec.param_grid["gross"]) <= meanrev.MAX_GROSS
