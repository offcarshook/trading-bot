from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import ResearchData  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.strategies import regimealloc as ra  # noqa: E402


def _df(close):
    c = pd.Series(close, index=pd.bdate_range("2020-01-01", periods=len(close)))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6})


def test_classify_regimes():
    n = 60
    up = np.linspace(100, 130, n)
    down = np.linspace(130, 100, n)
    spy = pd.Series(np.r_[up, down], index=pd.bdate_range("2020-01-01", periods=2 * n))
    bond_up = pd.Series(np.linspace(100, 120, 2 * n), index=spy.index)
    reg = ra.classify(spy, bond_up, 20, 20, False)
    assert reg.iloc[:19].isna().all()
    assert reg.iloc[50] == 0 and reg.iloc[-1] == 2
    reg2 = ra.classify(spy, bond_up[::-1].set_axis(spy.index), 20, 20, False)
    assert reg2.iloc[-1] == 3


def test_min_hold_limits_switches():
    reg = pd.Series([0, 0, 2, 0, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0], dtype=float)
    out = ra.apply_min_hold(reg, 5)
    # first switch allowed at i=5 (5 sessions after start), next not before i=10
    assert list(out[:5]) == [0] * 5 and out[5] == 2 and out[9] == 2 and out[10] == 0


def test_missing_asset_goes_to_cash_proxy_and_sums_to_one():
    reg = pd.Series([0.0, 3.0, np.nan])
    w = ra.regime_weights(reg, ra.ALLOC_MAPS["balanced"], ["SPY", "SHY"])
    assert w.loc[0, "SPY"] == 0.6 and abs(w.loc[0, "SHY"] - 0.4) < 1e-12
    assert w.loc[1, "SHY"] == 1.0 and w.iloc[2].sum() == 0.0
    for m in ra.ALLOC_MAPS.values():
        for a in m.values():
            assert abs(sum(a.values()) - 1.0) < 1e-12


def test_run_unlevered_next_open_and_costs():
    n = 400
    rng = np.random.default_rng(0)
    daily = {s: _df(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))) for s in ra.ASSETS}
    data = ResearchData(daily)
    p = dict(ra.SPEC.default_params, trend_sma=50, bond_sma=50, vol_filter=False)
    res = ra.SPEC.run(data, p, CostModel())
    assert res.weights.sum(axis=1).max() <= 1.0 + 1e-9
    assert res.exposure.max() <= 1.0 + 1e-6
    first = res.weights.index[res.weights.sum(axis=1) > 0][0]
    pos = res.returns.index.get_loc(first)
    assert res.turnover.iloc[pos] == 0 and res.turnover.iloc[pos + 1] > 0  # executes next session
    assert (res.returns <= res.gross_returns + 1e-12).all() and res.costs.sum() > 0


def test_adversarial_future_perturbation_leaves_past_regimes_unchanged():
    import numpy as np
    import pandas as pd
    from ictbot.research.strategies.regimealloc import classify, apply_min_hold
    idx = pd.bdate_range("2015-01-01", periods=600)
    rng = np.random.default_rng(1)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 600))), idx)
    bond = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, 600))), idx)
    a = apply_min_hold(classify(spy, bond, 100, 50, True), 5)
    spy2, bond2 = spy.copy(), bond.copy()
    spy2.iloc[450:] *= 0.5
    bond2.iloc[450:] *= 2.0
    b = apply_min_hold(classify(spy2, bond2, 100, 50, True), 5)
    pd.testing.assert_series_equal(a.iloc[:450], b.iloc[:450])
