"""Mechanics tests for overnight_drift / intraday_drift_control."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.strategies import overnight  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0,
                 short_borrow_rate=0)
P = dict(overnight.DEFAULTS)


def _data(opens, closes, start="2019-01-07"):  # 2019-01-07 is a Monday
    idx = pd.bdate_range(start, periods=len(opens))
    o, c = np.asarray(opens, float), np.asarray(closes, float)
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c,
                       "volume": 1e6}, index=idx)
    return ResearchData({"SPY": df})


def test_overnight_trade_prices_and_dating(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)
    d = _data([100, 102, 99], [101, 98, 100])
    r = overnight.run_overnight(d, P, ZERO)
    t = r.trades
    assert len(t) == 2  # no trade on the first session (no prior close)
    assert list(t["date"]) == list(d.daily["SPY"].index[1:])  # dated on the EXIT session
    assert list(t["entry_price"]) == [101, 98] and list(t["exit_price"]) == [102, 99]
    assert (t["entry_kind"] == "close").all() and (t["exit_kind"] == "open").all()
    np.testing.assert_allclose(r.returns.to_numpy(), [0.0, 102 / 101 - 1, 99 / 98 - 1])


def test_intraday_control_is_open_to_close(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)
    d = _data([100, 102, 99], [101, 98, 100])
    r = overnight.run_intraday(d, P, ZERO)
    np.testing.assert_allclose(r.returns.to_numpy(), [0.0, 98 / 102 - 1, 100 / 99 - 1])  # first day: no prior close
    # flat overnight: every trade enters and exits on its own date
    assert (pd.to_datetime(r.trades["entry_time"]).dt.normalize() == r.trades["date"]).all()


def test_regime_filter_uses_only_entry_close(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)
    n = 260
    c = np.full(n, 100.0)
    c[230] = 110.0  # above the SMA only at row 230's close
    o = c.copy()
    o[231] = 120.0  # huge next-open gap; must not affect the decision
    d = _data(o, c)
    p = dict(P, trend_filter="sma200")
    t = overnight.run_overnight(d, p, ZERO).trades
    # close 230 is known only after the MOC order for close 230 must be sent -> entry at close 231, exit open 232
    assert list(t["date"]) == [d.daily["SPY"].index[232]]
    t2 = overnight.run_intraday(d, p, ZERO).trades
    assert list(t2["date"]) == [d.daily["SPY"].index[231]]  # intraday decided with the prior close


def test_skip_friday_and_monday():
    d = _data([100] * 10, [100] * 10)  # Mon..Fri, Mon..Fri
    t = overnight.run_overnight(d, dict(P, skip_weekday=True), ZERO).trades
    assert not (pd.to_datetime(t["entry_time"]).dt.weekday == 4).any()
    t2 = overnight.run_intraday(d, dict(P, skip_weekday=True), ZERO).trades
    assert not (t2["date"].dt.weekday == 0).any()


def test_costs_reduce_returns_and_sizes():
    d = _data([100, 100, 100, 100], [100, 100, 100, 100])
    r = overnight.run_overnight(d, P, CostModel())
    assert (r.returns.iloc[1:] < 0).all() and r.costs.sum() > 0
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2019-01-07", periods=30)
    frames = {s: pd.DataFrame({"open": 100 + rng.random(30), "high": 102, "low": 98, "close": 100 + rng.random(30),
                               "volume": 1e6}, index=idx) for s in ["SPY", "QQQ", "IWM"]}
    rr = overnight.run_overnight(ResearchData(frames), dict(P, size_mult=2.0), ZERO)
    np.testing.assert_allclose(rr.trades["size"], 2.0 / 3)
    assert rr.trades.groupby("date")["size"].sum().max() <= 2.0 + 1e-12


def test_missing_symbols_graceful():
    d = _data([100, 101], [100, 101])
    assert overnight.run_overnight(d, dict(P, universe="QQQ"), ZERO).n_trades == 0


def test_overnight_regime_not_decided_on_entry_close(monkeypatch):
    """Adversarial: a regime flip that only appears AT the entry close must not trigger that entry."""
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)
    n = 260
    c = np.full(n, 100.0)
    c[-2] = 150.0  # spike at the entry close of the last possible overnight trade
    d = _data(c.copy(), c)
    t = overnight.run_overnight(d, dict(P, trend_filter="sma200"), ZERO).trades
    assert len(t) == 0


def test_missing_session_does_not_stitch_overnight(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)
    idx = pd.bdate_range("2019-01-07", periods=5)
    spy = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6}, index=idx)
    qqq = spy.drop(idx[2])  # QQQ missing one session
    d = ResearchData({"SPY": spy, "QQQ": qqq})
    t = overnight.run_overnight(d, P, ZERO).trades
    q = t[t["symbol"] == "QQQ"]
    assert idx[2] not in set(q["date"]) and idx[3] not in set(q["date"])
    assert ((pd.to_datetime(q["exit_time"]) - pd.to_datetime(q["entry_time"])) < pd.Timedelta(days=1)).all()
