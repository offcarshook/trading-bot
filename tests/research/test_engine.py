from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.engine import run_trades, run_weights  # noqa: E402
from ictbot.research import validation as V  # noqa: E402
from ictbot.research.metrics import summarize, sharpe  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0, short_borrow_rate=0)


def _data(closes, opens):
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    df = pd.DataFrame({"open": opens, "high": np.maximum(opens, closes), "low": np.minimum(opens, closes), "close": closes, "volume": 1.0}, index=idx)
    return ResearchData({"SPY": df})


def _zero_spread(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)


def test_next_open_execution_and_gap_accounting(monkeypatch):
    _zero_spread(monkeypatch)
    d = _data(closes=[100, 110, 121, 121], opens=[100, 105, 115, 121])
    w = pd.DataFrame({"SPY": [1.0, 1.0, 1.0, 1.0]}, index=d.daily["SPY"].index)
    r = run_weights(d, w, ZERO).returns
    # decided at close of day0 -> bought at OPEN day1 (105): day1 return = 110/105-1 (no overnight exposure yet)
    assert r.iloc[1] == pytest.approx(110 / 105 - 1)
    # day2 holds overnight 110->115 and intraday 115->121
    assert r.iloc[2] == pytest.approx(121 / 110 - 1)


def test_decision_today_cannot_earn_todays_move(monkeypatch):
    _zero_spread(monkeypatch)
    d = _data(closes=[100, 200, 200], opens=[100, 100, 200])
    w = pd.DataFrame({"SPY": [0.0, 1.0, 1.0]}, index=d.daily["SPY"].index)  # decide long only at close of day1
    r = run_weights(d, w, ZERO).returns
    assert r.iloc[1] == 0.0  # the 100->200 jump happened before we could act


def test_costs_and_financing_reduce_returns():
    d = _data(closes=[100] * 30, opens=[100] * 30)
    w = pd.DataFrame({"SPY": [2.0] * 30}, index=d.daily["SPY"].index)
    r = run_weights(d, w, CostModel()).returns
    assert r.sum() < 0  # spread on entry + margin interest on the borrowed 1x


def test_run_trades_costs_both_sides():
    idx = pd.bdate_range("2020-01-01", periods=3)
    trades = pd.DataFrame([{"date": idx[1], "symbol": "SPY", "direction": "long", "entry_time": idx[1], "entry_price": 100.0, "exit_time": idx[1],
                            "exit_price": 101.0, "size": 1.0, "entry_kind": "stop", "exit_kind": "close", "exit_reason": "eod"}])
    res = run_trades(trades, idx, CostModel())
    assert 0 < res.returns.iloc[1] < 0.01
    assert res.n_trades == 1


def test_deflated_sharpe_penalizes_many_trials():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0005, 0.01, 1500), index=pd.bdate_range("2016-01-01", periods=1500))
    few = V.deflated_sharpe(r, list(rng.normal(0, 0.01, 2)), 2)["dsr"]
    many = V.deflated_sharpe(r, list(rng.normal(0, 0.03, 300)), 300)["dsr"]
    assert many < few


def test_pbo_high_for_pure_noise():
    rng = np.random.default_rng(1)
    m = pd.DataFrame(rng.normal(0, 0.01, (1200, 40)))
    assert V.pbo_cscv(m, max_combos=500)["pbo"] > 0.3


def test_walk_forward_uses_only_past_for_selection():
    idx = pd.bdate_range("2016-01-01", "2021-12-31")
    a = pd.Series(np.where(idx < pd.Timestamp("2019-01-01"), 0.002, -0.002), index=idx)  # great early, bad later
    b = pd.Series(0.0005, index=idx)
    wf = V.walk_forward({"a": a, "b": b}, idx[0].date(), idx[-1].date(), train_years=3, step_months=6)
    assert wf["choices"][0]["chosen"] == "a"  # chosen on past data, so it gets punished out of sample
    assert wf["oos_returns"].iloc[:20].mean() < 0


def test_leverage_analysis_shows_volatility_drag():
    rng = np.random.default_rng(2)
    r = pd.Series(rng.normal(0.0, 0.01, 2000), index=pd.bdate_range("2016-01-01", periods=2000))
    r = r - r.mean() + 0.0004  # exact positive edge
    la = V.leverage_analysis(r, (0.05,), max_leverage=10, n_boot=50)
    assert la["kelly_leverage"] > 0
    assert "5%" in la["targets"]


def test_summary_monthly_geo_mean():
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    r = pd.Series(0.0, index=idx)
    r.iloc[0] = 0.12
    s = summarize(r)
    assert s["monthly_geo_mean"] == pytest.approx(1.12 ** (1 / 12) - 1, rel=1e-6)
    assert sharpe(r) > 0


def test_all_nan_rows_hold_without_trading(monkeypatch):
    _zero_spread(monkeypatch)
    d = _data(closes=[100, 110, 99, 120, 130], opens=[100, 105, 100, 118, 125])
    idx = d.daily["SPY"].index
    w = pd.DataFrame({"SPY": [0.5, np.nan, np.nan, np.nan, np.nan]}, index=idx)
    res = run_weights(d, w, ZERO)
    assert res.turnover.iloc[1] == pytest.approx(0.5)  # one entry trade...
    assert res.turnover.iloc[2:].sum() == pytest.approx(0.0)  # ...then pure drift, no re-trading to 0.5


def test_missing_bar_move_is_booked_when_trading_resumes(monkeypatch):
    _zero_spread(monkeypatch)
    idx = pd.bdate_range("2020-01-01", periods=4)
    a = pd.DataFrame({"open": [100, 100, np.nan, 50], "high": 100, "low": 50, "close": [100, 100, np.nan, 50], "volume": 1.0}, index=idx)
    b = pd.DataFrame({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1.0}, index=idx)
    d = ResearchData({"A": a, "B": b})
    w = pd.DataFrame({"A": [1.0] * 4, "B": [0.0] * 4}, index=idx)
    eq = (1 + run_weights(d, w, ZERO).returns).prod()
    assert eq == pytest.approx(0.5)  # the -50% across the missing day is not erased


def test_cap_to_margin_respects_letf_maintenance():
    from ictbot.research.strategies.common import cap_to_margin

    w = pd.DataFrame({"TQQQ": [1.95], "SPY": [0.0]}, index=pd.bdate_range("2020-01-01", periods=1))
    capped = cap_to_margin(w)
    assert capped["TQQQ"].iloc[0] == pytest.approx(0.97 / 0.75)
    w2 = pd.DataFrame({"SPY": [1.95]}, index=w.index)
    assert cap_to_margin(w2)["SPY"].iloc[0] == pytest.approx(1.94)
