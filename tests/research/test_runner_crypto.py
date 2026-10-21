"""Research runner on crypto (split_mode="adaptive") strategies WITH the null test.

* the null replays the strategy's own run_weights call: its hole-filled crypto view (identical prices)
  and its decision frame with all-NaN HOLD rows, circularly shifted (a shifted run never trades on
  more rows than the strategy decided on); dense stock frames keep the original position shift
* crypto is annualized with its own calendar (~365 rows/yr), not 252
* one strategy raising is recorded as an error, the explore run goes on
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ictbot.research import engine  # noqa: E402
from ictbot.research import report as R  # noqa: E402
from ictbot.research import runner  # noqa: E402
from ictbot.research import validation as V  # noqa: E402
from ictbot.research.base import StrategySpec  # noqa: E402
from ictbot.research.costs import CostModel  # noqa: E402
from ictbot.research.data import synthetic_data  # noqa: E402
from ictbot.research.engine import run_weights  # noqa: E402
from ictbot.research.metrics import sharpe  # noqa: E402
from ictbot.research.strategies import crypto as C  # noqa: E402
from ictbot.research.universe import CRYPTO  # noqa: E402

COSTS = CostModel()
HOLES = {"ETH/USD": ["2021-03-02", "2021-03-03", "2022-07-10"], "SOL/USD": ["2021-11-20"]}  # short holes -> filled by crypto.prepare


@pytest.fixture(scope="module")
def full():
    d = synthetic_data(["SPY", "IEF", "QQQ"], seed=7, crypto_symbols=tuple(CRYPTO))
    for s, days in HOLES.items():
        d.crypto[s] = d.crypto[s].drop(pd.DatetimeIndex(days))
    return d


def _small(spec: StrategySpec, grid: dict) -> StrategySpec:
    return dataclasses.replace(spec, param_grid=grid)


TREND = _small(C.TREND_SPEC, {"coins": ["btc_eth_sol"], "rule": ["sma_band"], "n": [50], "sizing": ["equal"], "rebalance": ["W", "D"]})
ROT = _small(C.ROTATION_SPEC, {"lookback": ["blend"], "top_n": [2], "regime_n": [100], "rebalance": ["W", "D"]})


def _window(spec, full):
    sp = runner.splits_for(spec, full)
    return sp, full.truncate(sp.validation[1])


def _trade_days(res, start, end) -> int:
    return int((V.cut(res.turnover, start, end) > 1e-9).sum())


@pytest.fixture
def few_shifts(monkeypatch):
    """runner's null with 10 shifts instead of 100 (speed); records every call's arguments."""
    calls, real = [], V.position_shift_null

    def wrapped(weights, run_fn, actual, **kw):
        calls.append((weights, run_fn, actual, dict(kw)))
        return real(weights, run_fn, actual, **dict(kw, n_shifts=10))

    monkeypatch.setattr(V, "position_shift_null", wrapped)
    return calls


# --------------------------------------------------------------------------- #
# Engine replay: the strategy's own view and decision rows
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", [TREND, ROT], ids=lambda s: s.name)
def test_replay_is_the_strategys_own_engine_call(spec, full):
    _, data = _window(spec, full)
    p = dict(spec.default_params, rebalance="W")
    res = spec.run(data, p, COSTS)
    view, dec, kw = runner.engine_replay(spec, data, p, COSTS, res.returns)
    assert C.run_weights is engine.run_weights  # patch undone
    for s, days in HOLES.items():  # the strategy's hole-filled view (not data / crypto_view()), same real bars
        if s in dec.columns:
            raw = data.crypto_view().daily[s]
            assert pd.DatetimeIndex(days).isin(view.daily[s].index).all() and not pd.DatetimeIndex(days).isin(raw.index).any()
            assert view.daily[s].loc[raw.index, "close"].equals(raw["close"])
    hold = dec.reindex(res.returns.index).isna().all(axis=1)
    assert hold.mean() > 0.5  # weekly schedule: most rows hold the drifted book
    assert not res.weights.isna().all(axis=1).any()  # ... which StrategyResult.weights (forward-filled) has lost
    assert run_weights(view, dec, COSTS, **kw).returns.equals(res.returns)  # bit-identical replay
    with pytest.raises(ValueError, match="no known symbols"):  # the original bug: replaying on the stock container
        run_weights(data, res.weights, COSTS)


def test_replay_refuses_post_processed_returns(full, few_shifts):
    def run(data, p, costs):
        res = run_weights(data.crypto_view(), pd.DataFrame({"BTC/USD": 0.5}, index=data.crypto_view().dates()), costs)
        res.returns = res.returns - 1e-6  # not what the engine call produced
        return res

    spec = StrategySpec("t_post", "t", "", {"x": [1]}, {}, run, symbols=("BTC/USD",), split_mode="adaptive")
    sp, data = _window(spec, full)
    res = spec.run(data, {"x": 1}, COSTS)
    assert runner.engine_replay(spec, data, {"x": 1}, COSTS, res.returns) is None
    null = runner.null_test(spec, data, res, {"x": 1}, COSTS, sp.train[0], sp.validation[1], 365)
    assert null["method"] == "position_shift" and null["p_value"] is not None and "note" in null  # fallback runs on the crypto view


# --------------------------------------------------------------------------- #
# position_shift_null: hold rows move with their decisions
# --------------------------------------------------------------------------- #


def test_shift_keeps_hold_rows_and_restores_the_decision_in_force():
    n = 200
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    vals = np.full((n, 2), np.nan)
    dec_rows = np.arange(0, n, 17)
    vals[dec_rows] = np.column_stack([np.linspace(0.1, 0.9, len(dec_rows)), np.linspace(0.9, 0.1, len(dec_rows))])
    w = pd.DataFrame(vals, idx, ["A", "B"])
    seen = []
    V.position_shift_null(w, lambda f: seen.append(f) or pd.Series(np.random.default_rng(len(seen)).normal(0, 0.01, n), idx), 0.0, n_shifts=30)
    ff = w.ffill()
    for f in seen:
        hold = f.isna().all(axis=1).to_numpy()
        assert not hold[0]  # never starts in cash
        assert (~hold).sum() in (len(dec_rows), len(dec_rows) + 1)  # same decisions (+ the restored first row)
        k = next(k for k in range(n) if np.allclose(np.roll(vals, k, axis=0)[1:], f.to_numpy()[1:], equal_nan=True))
        assert np.allclose(f.iloc[0], ff.iloc[-k])  # restored row = decision in force at the original row n-k


def test_dense_shift_is_unchanged():
    n = 150
    idx = pd.date_range("2021-01-01", periods=n, freq="B")
    w = pd.DataFrame(np.random.default_rng(1).uniform(0, 1, (n, 2)), idx, ["A", "B"])
    seen = []
    V.position_shift_null(w, lambda f: seen.append(f.to_numpy()) or pd.Series(f["A"].to_numpy() * 1e-3, idx), 0.0, n_shifts=10, seed=3)
    rng = np.random.default_rng(3)
    for got in seen:
        assert np.array_equal(got, np.roll(w.to_numpy(), int(rng.integers(21, n - 21)), axis=0))


# --------------------------------------------------------------------------- #
# The null compares the strategy with ITS OWN schedule at shifted dates
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", [TREND, ROT], ids=lambda s: s.name)
def test_shifted_runs_trade_no_more_often_than_the_strategy(spec, full, monkeypatch):
    sp, data = _window(spec, full)
    s, e = sp.train[0], sp.validation[1]
    p = dict(spec.default_params, rebalance="W")
    res = spec.run(data, p, COSTS)
    view, _, kw = runner.engine_replay(spec, data, p, COSTS, res.returns)
    frames, real = [], V.position_shift_null

    def spy(weights, run_fn, actual, **k):
        frames.append(weights)
        return real(weights, lambda f: frames.append(f) or run_fn(f), actual, **dict(k, n_shifts=12))

    monkeypatch.setattr(V, "position_shift_null", spy)
    null = runner.null_test(spec, data, res, p, COSTS, s, e, 365)
    assert null["method"] == "decision_shift" and null["p_value"] is not None
    win, shifted = frames[0], frames[1:]
    n_dec = int((~win.isna().all(axis=1)).sum())
    assert null["decision_rows"] == n_dec and n_dec < 0.2 * len(win)
    # unshifted replay of the window = the strategy itself once the first in-window decision has traded
    own = run_weights(view, win, COSTS, **kw)
    first = win.index[np.flatnonzero(~win.isna().all(axis=1).to_numpy())[1]]
    after = own.returns.index > first + pd.Timedelta(days=1)
    assert np.allclose(V.cut(own.returns[after], s, e), V.cut(res.returns[after], s, e), atol=1e-12)
    for f in shifted:  # each decision row trades at most once (the next open); +1 = restored first row
        assert _trade_days(run_weights(view, f, COSTS, **kw), s, e) <= n_dec + 1
    # the old null: forward-filled targets re-targeted every row trade on several times as many days
    k = len(win) // 3
    ffill = res.weights[(res.weights.index >= pd.Timestamp(s)) & (res.weights.index <= pd.Timestamp(e))]
    old = run_weights(view, pd.DataFrame(np.roll(ffill.to_numpy(), k, axis=0), ffill.index, ffill.columns), COSTS, **kw)
    assert _trade_days(old, s, e) > 3 * n_dec


def test_dense_stock_null_is_the_original_position_shift(full, few_shifts):
    def run(data, p, costs):
        idx = data.dates()
        return run_weights(data, pd.DataFrame({"SPY": p["w"], "IEF": 1 - p["w"]}, index=idx), costs, band=0.01)

    spec = StrategySpec("t_dense", "t", "", {"w": [0.6]}, {}, run, symbols=("SPY", "IEF"))
    sp = V.Splits.default(full.dates().max().date())
    data = full.truncate(sp.validation[1])
    s, e = sp.train[0], sp.validation[1]
    res = spec.run(data, {"w": 0.6}, COSTS)
    assert runner.engine_replay(spec, data, {"w": 0.6}, COSTS, res.returns) is not None  # replayed, but no hold rows
    got = runner.null_test(spec, data, res, {"w": 0.6}, COSTS, s, e, 252)
    (w, run_fn, actual, kw), = few_shifts
    tv = res.weights[(res.weights.index >= pd.Timestamp(s)) & (res.weights.index <= pd.Timestamp(e))]
    assert w.equals(tv) and actual == sharpe(V.cut(res.returns, s, e)) and kw == {"n_shifts": 100, "periods": 252}
    rolled = pd.DataFrame(np.roll(tv.to_numpy(), 300, axis=0), tv.index, tv.columns)  # band = notes["band"] (absent -> 0), stock data
    assert run_fn(rolled).equals(V.cut(run_weights(data, rolled, COSTS, band=0.0).returns, s, e))
    assert got["method"] == "position_shift" and set(got) == {"p_value", "null_sharpe_p50", "null_sharpe_p95", "n", "method"}


# --------------------------------------------------------------------------- #
# run_explore end to end: crypto WITH the null, a broken strategy, annualization
# --------------------------------------------------------------------------- #


def test_explore_runs_crypto_with_null_and_survives_a_broken_strategy(full, tmp_path, monkeypatch, few_shifts):
    def boom(data, p, costs):
        if costs.cost_multiplier > 1:
            raise RuntimeError("boom in the cost-stress rerun")
        return run_weights(data, pd.DataFrame({"SPY": 1.0}, index=data.dates()), costs)

    broken = StrategySpec("t_broken", "t", "", {"x": [1]}, {}, boom, symbols=("SPY",))
    monkeypatch.setattr(runner, "load_all_strategies", lambda: {"t_broken": broken, TREND.name: TREND, ROT.name: ROT})
    out = runner.run_explore(full, tmp_path)
    reps = {r["strategy"]: r for r in out["strategies"]}
    assert "boom" in reps["t_broken"]["error"] and "checks" not in reps["t_broken"]
    for name in (TREND.name, ROT.name):
        r = reps[name]
        assert r["null_test"]["method"] == "decision_shift" and r["null_test"]["p_value"] is not None
        best = pd.read_csv(tmp_path / "daily_returns.csv.gz", index_col=0, parse_dates=True)[f"{name}__best_full"].dropna()
        (tr_s, tr_e), va_e = [pd.Timestamp(x).date() for x in r["splits"]["train"]], pd.Timestamp(r["splits"]["validation"][1]).date()
        tr = V.cut(best, tr_s, tr_e)
        row = next(t for t in r["trials"] if t["params"] == r["selected_params"])
        assert row["train_sharpe"] == pytest.approx(sharpe(tr, 365), rel=1e-6)  # crypto calendar, not sqrt(252)
        assert r["dsr_train"]["sr0_annualized"] == pytest.approx(r["dsr_train"]["sr0_daily"] * math.sqrt(365))
        regimes = {k: v for k, v in r["regimes_train_val"].items() if k != "by_year"}
        assert "warmup" not in regimes  # weekends / days after the stock validation end carry SPY's label
        assert sum(v["days"] for v in regimes.values()) == len(V.cut(best, tr_s, va_e))
    saved = json.loads((tmp_path / "results.json").read_text())
    assert {r["strategy"] for r in saved["strategies"]} == {"t_broken", TREND.name, ROT.name}
    md = R.explore_markdown(saved)
    assert "boom in the cost-stress rerun" in md
    for name in (TREND.name, ROT.name):
        line = next(x for x in md.splitlines() if x.startswith(f"| {name} | 2 |"))
        assert f"| {reps[name]['null_test']['p_value']:.3f} |" in line
