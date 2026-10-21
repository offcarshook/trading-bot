"""Mechanics of the cross-sectional / dual momentum rotation strategies (xsmom)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.data import synthetic_data  # noqa: E402
from ictbot.research.strategies import xsmom as X  # noqa: E402
from ictbot.research.strategies.common import rebalance_mask  # noqa: E402
from ictbot.research.universe import ALL_DAILY  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0, short_borrow_rate=0)
N = 320


def _frame(idx, close, gaps=None):
    close = np.asarray(close, float)
    prev = np.concatenate(([close[0]], close[:-1]))
    open_ = prev * (np.exp(gaps) if gaps is not None else 1.0)
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001, "low": np.minimum(open_, close) * 0.999,
                         "close": close, "volume": 1e6}, index=idx)


def _data(drifts: dict, n: int = N, gap_sd: float = 0.0, seed: int = 0) -> ResearchData:
    """Deterministic log-drift paths (scalar = constant daily drift, array = per-day drifts)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    daily = {}
    for s, mu in drifts.items():
        r = np.full(n, float(mu)) if np.isscalar(mu) else np.asarray(mu, float)
        if gap_sd:
            r = r + rng.normal(0, gap_sd, n)
        close = 100.0 * np.exp(np.cumsum(r))
        daily[s] = _frame(idx, close, rng.normal(0, gap_sd, n) if gap_sd else None)
    return ResearchData(daily)


def _asset(**kw):
    return dict(X.ASSET_SPEC.default_params, **kw)


def _sector(**kw):
    return dict(X.SECTOR_SPEC.default_params, **kw)


def _zero_spread(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #


def test_momentum_scores_use_only_trailing_closes():
    idx = pd.bdate_range("2019-01-01", periods=300)
    close = pd.DataFrame({"A": 100 * 1.001 ** np.arange(300)}, index=idx)
    g = 1.001
    r6 = X.momentum_score(close, "ret_6")["A"]
    r121 = X.momentum_score(close, "ret_12_1")["A"]
    bl = X.momentum_score(close, "blend_1_3_6_12")["A"]
    assert np.isnan(r6.iloc[125]) and r6.iloc[126] == pytest.approx(g ** 126 - 1)
    assert np.isnan(r121.iloc[251]) and r121.iloc[252] == pytest.approx(g ** 231 - 1)  # 252 back, skip last 21
    assert np.isnan(bl.iloc[251])
    assert bl.iloc[299] == pytest.approx(np.mean([g ** 21 - 1, g ** 63 - 1, g ** 126 - 1, g ** 252 - 1]))
    # changing the future never changes a past score
    fut = close.copy()
    fut.iloc[280:] *= 3.0
    for sch in X.SCHEMES:
        a = X.momentum_score(close, sch).iloc[:280]
        b = X.momentum_score(fut, sch).iloc[:280]
        pd.testing.assert_frame_equal(a, b)


def test_skip_recent_ignores_last_month_spike():
    idx = pd.bdate_range("2019-01-01", periods=300)
    steady = 100 * np.exp(0.001 * np.arange(300))
    spike = np.full(300, 100.0)
    spike[-15:] = 100 * np.exp(0.02 * np.arange(1, 16))  # +30% in the last 15 sessions only
    close = pd.DataFrame({"STEADY": steady, "SPIKE": spike}, index=idx)
    for scheme, winner in [("ret_6", "SPIKE"), ("ret_12_1", "STEADY")]:
        w = X.rotation_weights(X.momentum_score(close, scheme), top_n=1, defensive=None)
        assert w.iloc[-1][winner] == 1.0 and w.iloc[-1].sum() == 1.0, scheme


# --------------------------------------------------------------------------- #
# Selection, absolute filter, missing symbols
# --------------------------------------------------------------------------- #

DRIFTS = {"SPY": 0.003, "QQQ": 0.002, "IWM": 0.00005, "EFA": -0.001, "SHY": 0.0001}


@pytest.mark.parametrize("top_n,abs_filter,expected", [
    (3, False, {"SPY": 1 / 3, "QQQ": 1 / 3, "IWM": 1 / 3}),
    (3, True, {"SPY": 1 / 3, "QQQ": 1 / 3, "SHY": 1 / 3}),  # IWM does not beat SHY -> its slot goes to SHY
    (6, False, {"SPY": 1 / 6, "QQQ": 1 / 6, "IWM": 1 / 6, "EFA": 1 / 6, "SHY": 2 / 6}),  # only 4 risky assets exist
    (6, True, {"SPY": 1 / 6, "QQQ": 1 / 6, "SHY": 4 / 6}),
])
def test_top_n_selection_and_absolute_filter(top_n, abs_filter, expected):
    d = _data(DRIFTS)  # 8 of the 12 asset-class ETFs are missing -> must be handled
    res = X.run_asset(d, _asset(top_n=top_n, abs_filter=abs_filter, lookback="blend_1_3_6_12", rebalance="M"), ZERO)
    w = res.weights.iloc[X.WARMUP]  # forced first decision right after the warm-up
    got = {k: v for k, v in w.items() if abs(v) > 1e-12}
    assert got.keys() == expected.keys()
    for k, v in expected.items():
        assert got[k] == pytest.approx(v)
    assert res.weights.iloc[: X.WARMUP].abs().to_numpy().sum() == 0.0  # nothing held during warm-up


def test_without_shy_unfilled_slots_stay_in_cash():
    d = _data({k: v for k, v in DRIFTS.items() if k != "SHY"})
    res = X.run_asset(d, _asset(top_n=6, abs_filter=True), ZERO)  # hurdle falls back to 0 (cash)
    w = res.weights.iloc[X.WARMUP]
    assert w["SPY"] == pytest.approx(1 / 6) and w["QQQ"] == pytest.approx(1 / 6) and w["IWM"] == pytest.approx(1 / 6)
    assert w["EFA"] == 0.0 and w.sum() == pytest.approx(0.5)
    assert "SHY" not in res.weights.columns


def test_no_universe_symbols_is_flat_not_an_error():
    d = _data({"USO": 0.001, "UUP": 0.0})
    res = X.run_sector(d, _sector(), CostModel())
    assert res.n_trades == 0 and res.returns.abs().sum() == 0.0


# --------------------------------------------------------------------------- #
# Market filter (sector rotation)
# --------------------------------------------------------------------------- #


def test_market_filter_moves_sector_book_to_shy():
    spy = np.where(np.arange(N) < 255, 0.001, -0.015)  # SPY falls far below its 200d SMA after row 255
    drifts = {"XLK": 0.003, "XLF": 0.002, "XLE": 0.0015, "XLV": 0.001, "XLY": 0.0005, "SHY": 0.0001, "SPY": spy}
    d = _data(drifts)
    idx = d.daily["SPY"].index
    last_reb = np.flatnonzero(rebalance_mask(idx, "W").to_numpy())[-1]
    on = X.run_sector(d, _sector(market_filter=True, abs_filter=False, top_n=3, rebalance="W"), ZERO).weights
    off = X.run_sector(d, _sector(market_filter=False, abs_filter=False, top_n=3, rebalance="W"), ZERO).weights
    # at the first live decision SPY is still above its SMA: filter is irrelevant
    np.testing.assert_allclose(on.iloc[X.WARMUP].to_numpy(), off.iloc[X.WARMUP].to_numpy())
    assert on.iloc[X.WARMUP][["XLK", "XLF", "XLE"]].to_numpy() == pytest.approx([1 / 3] * 3)
    # after the break: the whole book is SHY with the filter, top-3 sectors without it
    assert on.iloc[last_reb]["SHY"] == pytest.approx(1.0) and on.iloc[last_reb].drop("SHY").abs().sum() == 0.0
    assert off.iloc[last_reb][["XLK", "XLF", "XLE"]].to_numpy() == pytest.approx([1 / 3] * 3)
    assert "SPY" not in on.columns  # SPY is the filter, never a holding of the sector book


# --------------------------------------------------------------------------- #
# Execution timing, buy-and-hold between rebalances, costs
# --------------------------------------------------------------------------- #


def test_drift_between_rebalances_is_buy_and_hold():
    idx = pd.bdate_range("2020-01-06", periods=5)
    close = pd.DataFrame({"A": [100, 110, 121, 100, 100.0], "B": [100, 100, 100, 100, 50.0]}, index=idx)
    open_ = pd.DataFrame({"A": [100, 100, 110, 121, 100.0], "B": [100, 100, 100, 100, 100.0]}, index=idx)
    target = pd.DataFrame({"A": 0.5, "B": 0.0}, index=idx)  # 50% A, 50% cash
    w = X.drift_between_rebalances(target, np.array([True, False, False, True, False]), open_, close)
    assert w["A"].iloc[0] == 0.5  # decision row itself: the target
    # filled at open[1]=100; after close[1]=110: A = 0.5*1.1 / (0.5 + 0.55)
    assert w["A"].iloc[1] == pytest.approx(0.55 / 1.05)
    assert w["A"].iloc[2] == pytest.approx(0.605 / 1.105)
    assert w["A"].iloc[3] == 0.5  # new rebalance row resets to the target
    assert w["A"].iloc[4] == pytest.approx(0.5)  # filled at open[4]=100, close 100
    assert (w["B"] == 0).all()


def test_executes_next_open_and_trades_only_on_rebalance_days(monkeypatch):
    _zero_spread(monkeypatch)
    d = _data({"SPY": 0.003, "QQQ": 0.002, "IWM": 0.001, "EFA": -0.001, "SHY": 0.0001}, gap_sd=0.002, seed=3)
    res = X.run_asset(d, _asset(top_n=3, abs_filter=False, rebalance="M"), ZERO)
    idx = res.returns.index
    i0 = X.WARMUP
    # decision at the close of i0 earns nothing on i0 (no trading on the signal bar) ...
    assert res.returns.iloc[: i0 + 1].abs().sum() == 0.0 and res.turnover.iloc[i0] == 0.0
    # ... and is filled at the NEXT open: day i0+1 earns only the open->close move of the 3 picks
    picks = ["SPY", "QQQ", "IWM"]
    intraday = np.mean([d.daily[s]["close"].iloc[i0 + 1] / d.daily[s]["open"].iloc[i0 + 1] - 1 for s in picks])
    assert res.returns.iloc[i0 + 1] == pytest.approx(intraday, abs=1e-12)
    assert res.turnover.iloc[i0 + 1] == pytest.approx(1.0)
    # trades happen only the session after a rebalance decision; held positions just drift in between
    reb = rebalance_mask(idx, "M").to_numpy() | (np.arange(len(idx)) == i0)
    exec_days = np.zeros(len(idx), bool)
    exec_days[1:] = reb[:-1]
    assert (res.turnover.to_numpy()[~exec_days] == 0.0).all()
    assert res.n_trades >= 3


def test_costs_reduce_returns():
    d = synthetic_data(ALL_DAILY, start="2016-01-04", end="2019-12-31", seed=5)
    for spec, p in [(X.ASSET_SPEC, _asset(rebalance="W", top_n=1)), (X.SECTOR_SPEC, _sector(rebalance="W"))]:
        base = spec.run(d, p, CostModel())
        stressed = spec.run(d, p, CostModel().stressed(3.0))
        traded = base.turnover > 0
        assert traded.sum() > 20
        assert (base.costs[traded] > 0).all()
        assert (base.returns[traded] < base.gross_returns[traded]).all()
        assert (1 + stressed.returns).prod() < (1 + base.returns).prod()
        np.testing.assert_allclose(base.gross_returns, stressed.gross_returns, atol=1e-12)


# --------------------------------------------------------------------------- #
# Look-ahead on the FULL pre-registered grids (the generic test samples 3 trials)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def synth():
    return synthetic_data(ALL_DAILY, start="2016-01-04", end="2018-06-29", seed=11)


@pytest.mark.parametrize("spec", [X.ASSET_SPEC, X.SECTOR_SPEC], ids=lambda s: s.name)
def test_full_grid_truncation_invariance(spec, synth):
    cutoff = pd.Timestamp("2017-09-29")
    part_data = synth.truncate(cutoff)
    for p in spec.trials():
        full = spec.run(synth, p, CostModel())
        part = spec.run(part_data, p, CostModel())
        a = full.returns[full.returns.index <= cutoff]
        np.testing.assert_allclose(a.to_numpy(), part.returns.loc[a.index].to_numpy(), atol=1e-12, err_msg=str(p))
        wa = full.weights[full.weights.index <= cutoff]
        np.testing.assert_allclose(wa.to_numpy(), part.weights.loc[wa.index, wa.columns].to_numpy(), atol=1e-12, err_msg=str(p))
        assert full.turnover[full.turnover.index <= cutoff].sum() > 0, p
