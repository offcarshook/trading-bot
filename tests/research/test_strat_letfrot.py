"""Mechanics of the broad / leveraged ETF momentum rotation strategies (letfrot)."""

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
from ictbot.research.strategies import letfrot as L  # noqa: E402
from ictbot.research.strategies.common import MARGIN_BUFFER, margin_requirement, rebalance_mask  # noqa: E402
from ictbot.research.universe import ALL_DAILY, CRYPTO  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0, short_borrow_rate=0)
N = 320
CAP3X = (1.0 - MARGIN_BUFFER) / 0.75  # most gross a margin account can hold in 3x LETFs (~1.293)
CAP1X = (1.0 - MARGIN_BUFFER) / 0.50  # ... in 2x LETFs or ordinary ETFs (Reg-T 50%, ~1.94)


def _frame(idx, close):
    close = np.asarray(close, float)
    open_ = np.concatenate(([close[0]], close[:-1]))  # open = previous close: no overnight gaps
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001, "low": np.minimum(open_, close) * 0.999,
                         "close": close, "volume": 1e6}, index=idx)


def _data(drifts: dict, n: int = N, seed: int = 0, noise: float = 0.0) -> ResearchData:
    """Deterministic log-drift paths (scalar = constant daily drift, array = per-day log returns)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-07", periods=n)  # starts on a Monday
    daily = {}
    for s, mu in drifts.items():
        r = np.full(n, float(mu)) if np.isscalar(mu) else np.asarray(mu, float)
        if noise:
            r = r + rng.normal(0, noise, n)
        daily[s] = _frame(idx, 100.0 * np.exp(np.cumsum(r)))
    return ResearchData(daily)


def _letf(**kw):
    return dict(L.LETF_SPEC.default_params, **kw)


def _broad(**kw):
    return dict(L.BROAD_SPEC.default_params, **kw)


def _nz(row: pd.Series) -> dict:
    return {k: v for k, v in row.items() if abs(v) > 1e-12}


@pytest.fixture
def zero_spread(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #


def test_scores_blend_skip_week_and_risk_adjusted():
    idx = pd.bdate_range("2019-01-01", periods=300)
    g = 1.001
    close = pd.DataFrame({"A": 100 * g ** np.arange(300)}, index=idx)
    b = L.momentum_score(close, "blend")["A"]
    s = L.momentum_score(close, "blend_skip1w")["A"]
    assert np.isnan(b.iloc[125]) and b.iloc[126] == pytest.approx(np.mean([g ** 21 - 1, g ** 63 - 1, g ** 126 - 1]))
    # skip-1w legs end 5 sessions ago: 21->16, 63->58, 126->121 sessions of growth
    assert np.isnan(s.iloc[125]) and s.iloc[126] == pytest.approx(np.mean([g ** 16 - 1, g ** 58 - 1, g ** 121 - 1]))
    b12 = L.blended_return(close, L.LEGS["blend_1_3_6_12"])["A"]
    assert np.isnan(b12.iloc[251]) and b12.iloc[252] == pytest.approx(np.mean([g ** k - 1 for k in (21, 63, 126, 252)]))

    # risk-adjusted = blend / annualized vol of the trailing 63 daily log returns
    lr = 0.001 + 0.01 * np.where(np.arange(300) % 2 == 0, 1.0, -1.0)
    lr[0] = 0.0
    c2 = pd.DataFrame({"B": 100 * np.exp(np.cumsum(lr))}, index=idx)
    t = 299
    vol = np.std(lr[t - 62:t + 1], ddof=1) * np.sqrt(252)
    expect = L.blended_return(c2, L.LEGS["blend"])["B"].iloc[t] / vol
    assert L.momentum_score(c2, "riskadj")["B"].iloc[t] == pytest.approx(expect)
    # a zero-volatility path scores NaN (never selected), not +inf
    assert L.momentum_score(close, "riskadj")["A"].dropna().empty

    # changing the future never changes a past score
    fut = c2.copy()
    fut.iloc[280:] *= 3.0
    for sch in L.LEGS:
        pd.testing.assert_frame_equal(L.momentum_score(c2, sch).iloc[:280], L.momentum_score(fut, sch).iloc[:280])
    with pytest.raises(ValueError):
        L.momentum_score(c2, "nope")


def test_one_per_underlying_keeps_only_best_fund_of_each_index():
    idx = pd.bdate_range("2020-01-01", periods=2)
    sc = pd.DataFrame({"SSO": [0.1, np.nan], "UPRO": [0.3, np.nan], "SPXL": [0.2, 0.5], "TQQQ": [0.25, 0.1],
                       "QLD": [np.nan, 0.2], "SOXL": [0.05, 0.9]}, index=idx)
    out = L.one_per_underlying(sc)
    r0, r1 = out.iloc[0], out.iloc[1]
    assert r0["UPRO"] == 0.3 and np.isnan(r0["SSO"]) and np.isnan(r0["SPXL"])  # best S&P 500 fund only
    assert r0["TQQQ"] == 0.25 and np.isnan(r0["QLD"])  # QLD has no score
    assert r1["SPXL"] == 0.5 and np.isnan(r1["UPRO"]) and np.isnan(r1["SSO"])
    assert r1["QLD"] == 0.2 and np.isnan(r1["TQQQ"])
    assert r0["SOXL"] == 0.05 and r1["SOXL"] == 0.9  # ungrouped funds untouched


# --------------------------------------------------------------------------- #
# LETF rotation: selection, margin cap, regime filter, weekly schedule, maintenance calls
# --------------------------------------------------------------------------- #

LETF_DRIFTS = {"UPRO": 0.004, "SPXL": 0.0039, "SSO": 0.003, "TQQQ": 0.0035, "QLD": 0.0034, "SOXL": 0.002, "TMF": -0.001,
               "SPY": 0.001, "IEF": 0.0001}


@pytest.mark.parametrize("margin,expected_each", [(1.0, 0.5), (1.5, CAP3X / 2), (1.95, CAP3X / 2)])
def test_letf_top_n_one_per_index_and_margin_cap(zero_spread, margin, expected_each):
    d = _data(LETF_DRIFTS)
    res = L.run_letf(d, _letf(score="blend", top_n=2, regime="off", margin=margin), ZERO)
    w0 = res.weights.iloc[L.LETF_WARMUP]  # forced first decision right after the warm-up
    # SPXL is the 2nd-best fund overall but tracks the same index as UPRO -> TQQQ takes the 2nd slot
    assert _nz(w0).keys() == {"UPRO", "TQQQ"}
    assert w0["UPRO"] == pytest.approx(expected_each) and w0["TQQQ"] == pytest.approx(expected_each)
    assert res.weights.iloc[: L.LETF_WARMUP].abs().to_numpy().sum() == 0.0
    # the engine fills it at the next open: held gross never exceeds what the broker allows
    assert res.exposure.iloc[L.LETF_WARMUP + 1] == pytest.approx(2 * expected_each)
    n = res.notes
    assert n["requested_gross"] == margin and n["margin_calls"] == 0
    assert n["effective_gross_max"] == pytest.approx(2 * expected_each)
    assert n["cap_binding_share"] == (1.0 if margin > CAP3X else 0.0)
    assert "survivorship" in n["survivorship_caveat"] or "biased upward" in n["survivorship_caveat"]


def test_letf_2x_book_is_capped_at_reg_t_not_letf_limit(zero_spread):
    d = _data({"SSO": 0.003, "QLD": 0.0035, "SPY": 0.001})  # 2x funds: 50% requirement
    res = L.run_letf(d, _letf(score="blend", top_n=2, regime="off", margin=1.95), ZERO)
    w0 = res.weights.iloc[L.LETF_WARMUP]
    assert w0["SSO"] == pytest.approx(CAP1X / 2) and w0["QLD"] == pytest.approx(CAP1X / 2)
    assert res.notes["effective_gross_max"] == pytest.approx(CAP1X)
    usage = sum(abs(v) * margin_requirement(k) for k, v in w0.items())
    assert usage == pytest.approx(1.0 - MARGIN_BUFFER)


@pytest.mark.parametrize("regime", ["off", "cash", "IEF", "TMF"])
def test_regime_filter_switches_on_first_session_of_week_only(zero_spread, regime):
    spy = np.where(np.arange(N) < 260, 0.001, -0.02)  # SPY breaks below its 200d SMA a few days after row 260
    d = _data(dict(LETF_DRIFTS, SPY=spy))
    res = L.run_letf(d, _letf(score="blend", top_n=2, regime=regime, margin=1.0), ZERO)
    w = res.weights
    idx = w.index
    c = d.daily["SPY"]["close"]
    off = (c <= c.rolling(200).mean()).to_numpy()
    r0 = int(np.flatnonzero(off & (np.arange(N) > 260))[0])  # first risk-off close
    reb = rebalance_mask(idx, "W").to_numpy()
    r1 = int(np.flatnonzero(reb & (np.arange(N) >= r0))[0])  # first rebalance session at/after it
    assert idx[r1].dayofweek == 0 and r1 > r0  # (r0 is mid-week here) -> nothing happens until Monday
    assert _nz(w.iloc[r1 - 1]).keys() == {"UPRO", "TQQQ"}  # still invested between r0 and the rebalance
    got = _nz(w.iloc[r1])
    if regime == "off":
        assert got.keys() == {"UPRO", "TQQQ"}
    elif regime == "cash":
        assert got == {}
        assert res.exposure.iloc[r1] > 0.99 and res.exposure.iloc[r1 + 1] == 0.0  # decided at close, exits next open
    else:
        assert got == {regime: pytest.approx(1.0)}  # defensive sleeve, unmargined (TMF is 3x but held at 1.0)
    assert res.notes["market_filter"] is (regime != "off")


def test_letf_trades_only_after_weekly_decisions(zero_spread):
    names = ["UPRO", "TQQQ", "SOXL", "TECL", "FAS", "LABU"]
    d = _data({**{s: 0.0005 for s in names}, "SPY": 0.0005}, noise=0.03, seed=3)  # rankings change often
    res = L.run_letf(d, _letf(score="blend", top_n=1, regime="off", margin=1.0), ZERO)
    idx = res.returns.index
    pos = np.arange(len(idx))
    decisions = (rebalance_mask(idx, "W").to_numpy() & (pos >= L.LETF_WARMUP)) | (pos == L.LETF_WARMUP)
    traded = np.flatnonzero(res.turnover.to_numpy() > 1e-12)
    assert len(traded) >= 4  # several switches happened
    assert set(traded) <= set(np.flatnonzero(decisions) + 1)  # only on the open after a decision
    assert all(idx[i - 1].dayofweek == 0 for i in traded if i - 1 != L.LETF_WARMUP)  # decisions = Mondays here
    assert res.notes["margin_calls"] == 0 and res.notes["rebalances"] == int(decisions.sum())


def test_maintenance_breach_delevers_next_open(zero_spread):
    r = np.full(N, 0.002)
    idx = pd.bdate_range("2019-01-07", periods=N)
    x = int(np.flatnonzero((idx.dayofweek == 2) & (np.arange(N) > L.LETF_WARMUP + 5))[0])  # a Wednesday
    r[x] = np.log(0.85)  # the 3x fund falls 15% in one session, mid-week
    d = _data({"UPRO": r, "SPY": 0.001})
    # band=0: the engine trades exactly to every target, so the book and the engine agree to the last digit
    res = L.run_letf(d, _letf(score="blend", top_n=1, regime="off", margin=1.95, band=0.0), ZERO)
    w = res.weights["UPRO"]
    assert w.iloc[L.LETF_WARMUP] == pytest.approx(CAP3X)
    # drifted book at the close of x, from the Monday rebalance (filled at Tuesday's open = Monday's close)
    mon = x - 2
    close = d.daily["UPRO"]["close"]
    g = close.iloc[x] / close.iloc[mon]
    drifted = CAP3X * g / (1.0 - CAP3X + CAP3X * g)
    assert drifted * 0.75 > 1.0  # equity below the 75% maintenance requirement
    assert res.notes["margin_calls"] == 1 and res.notes["margin_call_dates"] == [str(idx[x].date())]
    assert w.iloc[x] == pytest.approx(CAP3X)  # de-lever decision at the close of x
    assert res.exposure.iloc[x] == pytest.approx(w.iloc[x - 1])  # still held through the crash day
    assert res.turnover.iloc[x + 1] == pytest.approx(drifted - CAP3X) and res.exposure.iloc[x + 1] == pytest.approx(CAP3X)
    # without borrowed money there is never a call
    unlev = L.run_letf(d, _letf(score="blend", top_n=1, regime="off", margin=1.0), ZERO)
    assert unlev.notes["margin_calls"] == 0 and unlev.exposure.max() <= 1.0 + 1e-12


THREE_3X = ["SOXL", "TECL", "FAS"]  # three 3x funds on different indexes (no same-underlying dedup)


def test_marginal_breach_is_not_swallowed_by_no_trade_band(zero_spread):
    r = np.where(np.arange(N) < L.LETF_WARMUP, 0.002, 0.0)  # flat after the first fill: weekly targets = held book
    idx = pd.bdate_range("2019-01-07", periods=N)
    x = int(np.flatnonzero((idx.dayofweek == 2) & (np.arange(N) > L.LETF_WARMUP + 5))[0])  # a Wednesday
    r[x] = np.log(0.895)  # all three fall 10.5%: the book is only JUST past maintenance
    d = _data({**{s: r for s in THREE_3X}, "SPY": 0.001})
    band = 0.02
    res = L.run_letf(d, _letf(score="blend", top_n=3, regime="off", margin=1.95, band=band), ZERO)
    close = d.daily["SOXL"]["close"]
    g = close.iloc[x] / close.iloc[L.LETF_WARMUP]  # first fill at the open after the warm-up = that close
    drifted = CAP3X * g / (1.0 - CAP3X + CAP3X * g)
    assert 1.0 < 0.75 * drifted < 1.01  # a marginal breach ...
    assert (drifted - CAP3X) / 3 < band  # ... where plain de-levering to the cap would be < band per fund
    assert res.notes["margin_call_dates"][0] == str(idx[x].date())
    # the forced sale still executes at the next open and leaves the book inside the initial requirement
    assert res.turnover.iloc[x + 1] >= 3 * L.CALL_MIN_SELL_BANDS * band - 1e-9
    assert 0.75 * res.exposure.iloc[x + 1] <= 1.0 - MARGIN_BUFFER + 1e-9
    for s in THREE_3X:
        assert res.weights[s].iloc[x] == pytest.approx(drifted / 3 - L.CALL_MIN_SELL_BANDS * band)


def test_held_book_is_exactly_what_the_engine_holds_under_the_band(zero_spread):
    # noisy, gap-free paths: weekly targets often land within the band, so the engine keeps the drifted book
    d = _data({**{s: 0.0005 for s in THREE_3X}, "SPY": 0.0005}, noise=0.012, seed=4)
    res = L.run_letf(d, _letf(score="blend", top_n=3, regime="off", margin=1.95, band=0.02), ZERO)
    idx = res.returns.index
    pos = np.arange(len(idx))
    decision = (rebalance_mask(idx, "W").to_numpy() & (pos >= L.LETF_WARMUP)) | (pos == L.LETF_WARMUP)
    decision |= np.isin(idx, pd.DatetimeIndex(res.notes["margin_call_dates"]))
    assert res.notes["margin_calls"] <= 20
    held_gross = res.weights.abs().sum(axis=1).to_numpy()
    after_hold = np.flatnonzero(~decision[:-1] & (pos[:-1] >= L.LETF_WARMUP)) + 1
    # no gap and no trade at the open after a hold row: the engine's gross = the book's gross at the prior close
    np.testing.assert_allclose(res.exposure.to_numpy()[after_hold], held_gross[after_hold - 1], atol=1e-12)
    skipped = [i for i in np.flatnonzero(decision[:-1]) + 1 if res.turnover.iloc[i] == 0.0 and i > L.LETF_WARMUP + 1]
    assert len(skipped) >= 3  # band-suppressed rebalances happened, so a target-reset book would be wrong here


def test_leverage_cut_funds_carry_3x_requirement_before_the_cut(zero_spread):
    idx = pd.bdate_range("2019-01-07", "2021-06-30")
    d = ResearchData({"NUGT": _frame(idx, 100 * np.exp(0.001 * np.arange(len(idx)))),
                      "SPY": _frame(idx, 100 * np.exp(0.0005 * np.arange(len(idx))))})
    assert L.LEVERAGE_CUTS == {"NUGT": ("2020-04-01", 3.0), "ERX": ("2020-04-01", 3.0)}
    init, maint = L.requirements(idx, ["NUGT", "SPY", "SSO"])
    cut = np.asarray(idx >= pd.Timestamp("2020-04-01"))
    assert 0 < cut.sum() < len(idx)
    assert (init[~cut, 0] == 0.75).all() and (maint[~cut, 0] == 0.75).all()  # 3x before 2020-04-01
    assert (init[cut, 0] == 0.50).all() and (maint[cut, 0] == 0.50).all()  # 2x afterwards
    assert (init[:, 1] == 0.50).all() and (maint[:, 1] == 0.30).all() and (init[:, 2] == 0.50).all()
    res = L.run_letf(d, _letf(score="blend", top_n=1, regime="off", margin=1.95, band=0.0), ZERO)
    w = res.weights["NUGT"]
    reb = (rebalance_mask(idx, "W").to_numpy() & (np.arange(len(idx)) >= L.LETF_WARMUP)) | (np.arange(len(idx)) == L.LETF_WARMUP)
    assert np.allclose(w[reb & ~cut], CAP3X) and np.allclose(w[reb & cut], CAP1X)
    assert res.exposure[~cut].max() <= CAP3X + 1e-9  # never held above the 3x limit while NUGT was 3x


# --------------------------------------------------------------------------- #
# Broad dual momentum: absolute filter vs SHY, margin, park
# --------------------------------------------------------------------------- #

BROAD_DRIFTS = {"SPY": 0.003, "QQQ": 0.002, "XLK": 0.0015, "IWM": 0.00005, "EFA": -0.001, "SHY": 0.0001}


@pytest.mark.parametrize("top_n,margin,expected", [
    (3, 1.0, {"SPY": 1 / 3, "QQQ": 1 / 3, "XLK": 1 / 3}),
    (3, 1.95, {"SPY": CAP1X / 3, "QQQ": CAP1X / 3, "XLK": CAP1X / 3}),  # 1.95 requested -> 1.94 allowed
    (5, 1.0, {"SPY": 0.2, "QQQ": 0.2, "XLK": 0.2, "SHY": 0.4}),  # IWM / EFA do not beat SHY
    (5, 1.5, {"SPY": 0.3, "QQQ": 0.3, "XLK": 0.3, "SHY": 0.1}),  # SHY only from the 10% of equity not deployed
    (5, 1.95, {"SPY": 0.39, "QQQ": 0.39, "XLK": 0.39}),  # risky 1.17 already borrows: no SHY bought on margin
])
def test_broad_absolute_filter_parks_in_shy_from_unborrowed_equity(zero_spread, top_n, margin, expected):
    d = _data(BROAD_DRIFTS)
    res = L.run_broad(d, _broad(top_n=top_n, margin=margin, score="blend_1_3_6_12", rebalance="M"), ZERO)
    got = _nz(res.weights.iloc[L.BROAD_WARMUP])
    assert got.keys() == expected.keys()
    for k, v in expected.items():
        assert got[k] == pytest.approx(v)
    assert res.notes["effective_gross_max"] == pytest.approx(sum(expected.values()))
    assert res.notes["requested_gross"] == margin and res.notes["park"] == "SHY"
    # never borrow at the margin rate to hold T-bills: SHY > 0 only while the book is not levered
    w = res.weights.iloc[L.BROAD_WARMUP:]
    assert ((w.drop(columns="SHY").sum(axis=1) <= 1.0 + 1e-9) | (w["SHY"] <= 1e-12)).all()
    assert res.notes["share_slots_failed"] == pytest.approx(0.4 if top_n == 5 else 0.0)


def test_broad_without_shy_keeps_failed_slots_in_cash_and_flat_without_universe(zero_spread):
    d = _data({k: v for k, v in BROAD_DRIFTS.items() if k != "SHY"})
    res = L.run_broad(d, _broad(top_n=5, margin=1.0), ZERO)  # hurdle falls back to 0
    got = _nz(res.weights.iloc[L.BROAD_WARMUP])
    assert got == {"SPY": pytest.approx(0.2), "QQQ": pytest.approx(0.2), "XLK": pytest.approx(0.2), "IWM": pytest.approx(0.2)}
    assert res.notes["park"] == "cash"
    flat = L.run_letf(_data({"USO": 0.001, "SPY": 0.001}), _letf(), CostModel())
    assert flat.n_trades == 0 and flat.returns.abs().sum() == 0.0 and "flat_reason" in flat.notes
    assert L.run_broad(_data({"USO": 0.001}), _broad(), CostModel()).n_trades == 0


# --------------------------------------------------------------------------- #
# Causality incl. the maintenance-call path, broker feasibility, spec
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def hot_data():
    # high-volatility synthetic data so margined books actually breach maintenance; 7-day crypto bars present
    # (crypto_start must lie inside the window, or the crypto frames come back EMPTY and nothing is tested)
    d = synthetic_data(ALL_DAILY, start="2016-01-04", end="2018-12-31", seed=5, vol=0.035, crypto_symbols=tuple(CRYPTO),
                       crypto_start="2016-01-04")
    assert all(len(d.crypto[s]) > 1000 for s in CRYPTO) and (d.crypto["BTC/USD"].index.dayofweek >= 5).any()
    return d


@pytest.mark.parametrize("spec_name", ["letf_momentum_rotation", "broad_etf_momentum"])
def test_crypto_never_leaks_into_etf_books_or_calendar(hot_data, spec_name):
    spec = L.LETF_SPEC if spec_name == "letf_momentum_rotation" else L.BROAD_SPEC
    params = {"margin": 1.95} if spec is L.LETF_SPEC else {}
    with_c = spec.run(hot_data, params, CostModel())
    no_c = spec.run(ResearchData(hot_data.daily, hot_data.intraday, dict(hot_data.meta)), params, CostModel())
    pd.testing.assert_series_equal(with_c.returns, no_c.returns)
    pd.testing.assert_frame_equal(with_c.weights, no_c.weights)
    assert not any("/" in c for c in with_c.weights.columns)
    assert (with_c.returns.index.dayofweek < 5).all()  # stock calendar only, no crypto weekend rows
    assert with_c.returns.index.equals(hot_data.dates())


@pytest.mark.parametrize("spec_name,params", [
    ("letf_momentum_rotation", {"margin": 1.95, "regime": "off", "top_n": 1, "score": "blend_skip1w"}),
    ("letf_momentum_rotation", {"margin": 1.5, "regime": "TMF", "top_n": 3, "score": "riskadj"}),
    ("broad_etf_momentum", {"margin": 1.95, "rebalance": "W", "top_n": 3}),
])
def test_truncation_invariance_and_broker_feasibility(hot_data, spec_name, params):
    spec = L.LETF_SPEC if spec_name == "letf_momentum_rotation" else L.BROAD_SPEC
    cutoff = pd.Timestamp("2018-03-29")
    full = spec.run(hot_data, params, CostModel())
    part = spec.run(hot_data.truncate(cutoff), params, CostModel())
    a = full.returns[full.returns.index <= cutoff]
    b = part.returns.reindex(a.index)
    assert len(a) > 500
    np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), atol=1e-12)
    wa = full.weights[full.weights.index <= cutoff]
    np.testing.assert_allclose(wa.to_numpy(), part.weights.reindex(index=wa.index, columns=wa.columns).to_numpy(), atol=1e-12)
    calls_before = [x for x in full.notes["margin_call_dates"] if pd.Timestamp(x) <= cutoff]
    assert calls_before == part.notes["margin_call_dates"]
    if spec_name == "letf_momentum_rotation" and params["top_n"] == 1:
        assert len(calls_before) >= 1  # the maintenance-call path is exercised by this check
    # every row the strategy would send as a trade target respects the broker's margin capacity, using the
    # per-session requirement (all of 2016-2018 is before the NUGT/ERX leverage cut -> 75% for both)
    init, maint = L.requirements(full.weights.index, list(full.weights.columns))
    a = full.weights.abs().to_numpy()
    usage, maint_usage = (a * init).sum(axis=1), (a * maint).sum(axis=1)
    pos = np.arange(len(usage))
    reb = rebalance_mask(full.weights.index, params.get("rebalance", "W")).to_numpy()
    warm = L.LETF_WARMUP if spec is L.LETF_SPEC else L.BROAD_WARMUP
    targets = (reb & (pos >= warm)) | (pos == warm)
    assert usage[targets].max() <= 1.0 - MARGIN_BUFFER + 1e-9
    # on every other close the book is what the engine holds: never left in maintenance breach without a call
    calls = np.isin(full.weights.index, pd.DatetimeIndex(full.notes["margin_call_dates"]))
    assert maint_usage[~targets & ~calls].max() <= 1.0 + 1e-9
    assert usage[calls].max(initial=0.0) <= 1.0 - MARGIN_BUFFER + 1e-9


@pytest.mark.parametrize("spec", [L.LETF_SPEC, L.BROAD_SPEC])
def test_spec_pre_registration(spec):
    n = len(spec.trials())
    assert 12 <= n <= 120
    for k, v in spec.default_params.items():
        assert v in spec.param_grid[k]
    assert set(spec.param_grid["margin"]) == {1.0, 1.5, 1.95}
    assert "SURVIVORSHIP" in spec.hypothesis and spec.split_mode == "default"
