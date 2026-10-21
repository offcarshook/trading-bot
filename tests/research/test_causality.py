"""Generic look-ahead test for EVERY registered strategy.

For a cutoff date D: run the strategy on data truncated at D and on the full
data. Everything the strategy decided or earned up to D must be identical -
if future bars change past decisions, the strategy is peeking.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research.base import load_all_strategies  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.data import synthetic_data  # noqa: E402
from ictbot.research.universe import ALL_DAILY, INTRADAY  # noqa: E402

SPECS = load_all_strategies()


@pytest.fixture(scope="module")
def data():
    return synthetic_data(ALL_DAILY, start="2016-01-04", end="2018-06-29", seed=11, intraday_symbols=tuple(INTRADAY))


def _sample_params(spec, k=3):
    trials = spec.trials()
    idx = np.linspace(0, len(trials) - 1, min(k, len(trials))).astype(int)
    return [trials[i] for i in sorted(set(idx))]


@pytest.mark.parametrize("name", sorted(SPECS))
def test_no_lookahead(name, data):
    spec = SPECS[name]
    cutoff = pd.Timestamp("2017-09-29")
    costs = CostModel()
    for p in _sample_params(spec):
        full = spec.run(data, p, costs)
        part = spec.run(data.truncate(cutoff), p, costs)
        a = full.returns[full.returns.index <= cutoff]
        b = part.returns[part.returns.index <= cutoff]
        common = a.index.intersection(b.index)
        assert len(common) > 100, f"{name}: too few overlapping days"
        np.testing.assert_allclose(a.loc[common].to_numpy(), b.loc[common].to_numpy(), atol=1e-12,
                                   err_msg=f"{name} {p}: returns before the cutoff change when future data is added -> look-ahead")
        if full.weights is not None and part.weights is not None:
            wa = full.weights[full.weights.index <= cutoff].fillna(0)
            wb = part.weights[part.weights.index <= cutoff].fillna(0)
            cols = wa.columns.intersection(wb.columns)
            idx = wa.index.intersection(wb.index)
            np.testing.assert_allclose(wa.loc[idx, cols].to_numpy(), wb.loc[idx, cols].to_numpy(), atol=1e-12,
                                       err_msg=f"{name} {p}: decisions before the cutoff depend on future data")


@pytest.mark.parametrize("name", sorted(SPECS))
def test_spec_is_well_formed(name):
    spec = SPECS[name]
    assert spec.hypothesis and spec.family
    assert spec.param_grid and all(isinstance(v, list) and v for v in spec.param_grid.values())
    for k in spec.default_params:
        assert k in spec.param_grid, f"{name}: default param {k} missing from the pre-registered grid"
    assert len(spec.trials()) <= 400, f"{name}: grid too large - multiple-testing burden"
