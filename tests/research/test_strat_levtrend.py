from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import REGISTRY, ResearchData, load_all_strategies  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.strategies.levtrend import regime_labels, trend_state  # noqa: E402

load_all_strategies()


def _df(close, idx):
    c = np.asarray(close, float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}, index=idx)


def _data(n=320, crash_at=260):
    idx = pd.bdate_range("2020-01-01", periods=n)
    qqq = np.r_[np.linspace(100, 200, crash_at), np.linspace(200, 120, n - crash_at)]
    r = np.r_[0, np.diff(qqq) / qqq[:-1]]
    tqqq = 50 * np.cumprod(1 + 3 * r)
    shy = 80 * np.cumprod(np.full(n, 1.0001))
    return ResearchData({"QQQ": _df(qqq, idx), "TQQQ": _df(tqqq, idx), "SHY": _df(shy, idx)}), idx


def test_trend_state_filters():
    idx = pd.bdate_range("2020-01-01", periods=8)
    c = pd.Series([10, 10, 10, 10.1, 9.9, 10.5, 10.6, 10.7], idx)
    s = trend_state(c, 3, "none")
    assert s.iloc[:2].sum() == 0  # no SMA yet -> out
    assert s.iloc[3] == 1 and s.iloc[4] == 0
    b = trend_state(c, 3, "band2")
    assert b.iloc[3] == 0 and b.iloc[5] == 1  # 10.1 inside band, 10.5 > sma*1.02
    k = trend_state(c, 3, "confirm3")
    assert k.iloc[5] == 0 and k.iloc[7] == 1  # needs 3 consecutive closes above


def test_switch_executes_next_open_and_defensive():
    data, idx = _data()
    res = REGISTRY["leveraged_trend"].run(data, {"lev": "TQQQ", "sma": 150, "filter": "none", "defensive": "SHY"}, CostModel())
    w = res.weights
    assert w["TQQQ"].iloc[200] == 1.0 and w["SHY"].iloc[200] == 0.0
    exit_day = int(np.argmax((w["SHY"] == 1.0).to_numpy() & (np.arange(len(idx)) > 200)))
    assert w["TQQQ"].iloc[exit_day] == 0.0 and w["TQQQ"].iloc[exit_day - 1] == 1.0
    # decision on exit_day executes next open: exposure on exit_day itself still TQQQ (open=close so returns = TQQQ's)
    tq = data.daily["TQQQ"]["close"].pct_change()
    assert abs(res.gross_returns.iloc[exit_day] - tq.iloc[exit_day]) < 1e-12
    sh = data.daily["SHY"]["close"].pct_change()
    assert abs(res.gross_returns.iloc[exit_day + 2] - sh.iloc[exit_day + 2]) < 1e-12
    assert res.notes["time_in_leveraged"] > 0 and res.notes["time_in_defensive"] > 0


def test_costs_reduce_returns_and_cash_is_flat():
    data, _ = _data()
    p = {"lev": "TQQQ", "sma": 150, "filter": "none", "defensive": "CASH"}
    res = REGISTRY["leveraged_trend"].run(data, p, CostModel())
    assert (res.costs >= 0).all() and res.costs.sum() > 0
    assert res.returns.sum() < res.gross_returns.sum()
    w = res.weights
    cash_days = w.index[w.sum(axis=1) == 0]
    assert len(cash_days) > 10


def test_regime_labels_and_mapping():
    idx = pd.bdate_range("2018-01-01", periods=600)
    rng = np.random.default_rng(0)
    vol = np.where(np.arange(600) < 450, 0.005, 0.03)
    c = pd.Series(100 * np.exp(np.cumsum(0.001 + vol * rng.standard_normal(600))), idx)
    lab = regime_labels(c)
    assert lab.iloc[:251].isna().all()
    assert lab.iloc[470:].dropna().isin([1, 3]).mean() > 0.9  # vol jump -> high-vol regimes
    # truncation invariance
    lab2 = regime_labels(c.iloc[:500])
    pd.testing.assert_series_equal(lab.iloc[:500], lab2)


def test_adversarial_trend_state_prefix_invariant_and_band_holds():
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2015-01-01", periods=600)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600))), index=idx)
    for filt in ("none", "band2", "confirm3"):
        full = trend_state(close, 150, filt)
        part = trend_state(close.iloc[:400], 150, filt)
        pd.testing.assert_series_equal(full.iloc[:400], part)
    # inside the +/-2% band the band2 state must not flip
    c = pd.Series([100.0] * 5 + [103.0, 101.0, 99.0, 97.0], index=pd.bdate_range("2020-01-01", periods=9))
    s = trend_state(c, 5, "band2")
    assert s.iloc[5] == 1.0 and s.iloc[6] == 1.0
