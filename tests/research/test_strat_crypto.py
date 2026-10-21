"""Mechanics of the crypto spot strategies (crypto_trend, crypto_momentum_rotation)."""

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
from ictbot.research.strategies import crypto as C  # noqa: E402
from ictbot.research.universe import CRYPTO  # noqa: E402

ZERO = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0, margin_rate=0, short_borrow_rate=0)
START = "2021-01-04"  # a Monday


def _frame(idx, log_ret, gaps=None, p0=100.0):
    close = p0 * np.exp(np.cumsum(np.asarray(log_ret, float)))
    prev = np.concatenate(([p0], close[:-1]))
    open_ = prev * (np.exp(gaps) if gaps is not None else 1.0)
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001, "low": np.minimum(open_, close) * 0.999,
                         "close": close, "volume": 1e3}, index=idx)


def _crypto(paths: dict, n: int, listed: dict | None = None, gaps: dict | None = None) -> ResearchData:
    """Hand-built 7-day calendar. ``paths``: coin -> scalar daily log drift or array; ``listed``: coin -> first row."""
    idx = pd.date_range(START, periods=n, freq="D")
    crypto = {}
    for s, mu in paths.items():
        r = np.full(n, float(mu)) if np.isscalar(mu) else np.asarray(mu, float)
        df = _frame(idx, r, (gaps or {}).get(s))
        crypto[s] = df.iloc[(listed or {}).get(s, 0):]
    return ResearchData({}, {}, {}, crypto)


def _trend(**kw):
    return dict(C.TREND_SPEC.default_params, **kw)


def _rot(**kw):
    return dict(C.ROTATION_SPEC.default_params, **kw)


def _book(w: pd.DataFrame) -> pd.DataFrame:
    """What the engine holds after each decision row (all-NaN rows = hold)."""
    return w.ffill().fillna(0.0)


def _zero_spread(monkeypatch):
    monkeypatch.setattr("ictbot.research.costs.half_spread_bps", lambda s: 0.0)


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #


def test_trend_rules_on_hand_built_series():
    idx = pd.date_range(START, periods=9, freq="D")
    c = pd.DataFrame({"X": [10, 10, 10, 10.1, 9.9, 10.5, 10.4, 10.1, 9.6]}, index=idx)
    sma = C.trend_state(c, "sma", 3)["X"]
    assert sma.iloc[:2].sum() == 0  # no SMA yet -> out
    assert sma.iloc[3] == 1 and sma.iloc[4] == 0 and sma.iloc[5] == 1
    band = C.trend_state(c, "sma_band", 3)["X"]
    # 10.1 is inside the +-3% band (no entry); 10.5 > sma*1.03 enters; 10.4/10.1 stay in (not < sma*0.97); 9.6 exits
    assert band.iloc[3] == 0 and band.iloc[5] == 1 and band.iloc[6] == 1 and band.iloc[7] == 1 and band.iloc[8] == 0
    dc = C.trend_state(c, "donchian", 4)["X"]  # entry > max of the 4 PRIOR closes, exit < min of the 2 PRIOR closes
    # row 5: 10.5 > max(10, 10, 10.1, 9.9) enters; row 6: 10.4 >= min(9.9, 10.5) stays; row 7: 10.1 < min(10.5, 10.4) exits;
    # row 8: 9.6 is no new high -> stays out
    assert dc.tolist() == [0, 0, 0, 0, 0, 1, 1, 0, 0]


def test_trend_rules_are_causal_and_need_full_windows():
    idx = pd.date_range(START, periods=400, freq="D")
    rng = np.random.default_rng(1)
    c = pd.DataFrame({"X": 100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, 400)))}, index=idx)
    fut = c.copy()
    fut.iloc[300:] *= 0.3  # a crash in the future
    for rule in ("sma", "sma_band", "donchian"):
        for n in (20, 200):
            a = C.trend_state(c, rule, n).iloc[:300]
            b = C.trend_state(fut, rule, n).iloc[:300]
            pd.testing.assert_frame_equal(a, b)
            assert C.trend_state(c, rule, n).iloc[: n - 1].to_numpy().sum() == 0  # no full window -> out


def test_momentum_scores_and_top_n():
    idx = pd.date_range(START, periods=80, freq="D")
    g = 1.01
    close = pd.DataFrame({"A": 100 * g ** np.arange(80), "B": 100 * 1.02 ** np.arange(80)}, index=idx)
    r7 = C.momentum_score(close, "r7")["A"]
    assert np.isnan(r7.iloc[6]) and r7.iloc[7] == pytest.approx(g ** 7 - 1)
    bl = C.momentum_score(close, "blend")["A"]
    assert np.isnan(bl.iloc[59]) and bl.iloc[79] == pytest.approx(np.mean([g ** 7 - 1, g ** 14 - 1, g ** 30 - 1, g ** 60 - 1]))
    scores = pd.DataFrame({"A": [1.0, np.nan, 0.5], "B": [2.0, 1.0, 0.5], "C": [0.0, 3.0, np.nan]})
    m = C.top_n_mask(scores, 2)
    assert m.tolist() == [[True, True, False], [False, True, True], [True, True, False]]  # NaN never chosen, ties -> column order


# --------------------------------------------------------------------------- #
# crypto_trend
# --------------------------------------------------------------------------- #


def test_trend_pool_weights_equal_and_inverse_vol():
    n = 260
    alt = (-1.0) ** np.arange(n)
    paths = {"BTC/USD": 0.004 + 0.01 * alt, "ETH/USD": 0.004 + 0.02 * alt, "SOL/USD": -0.004}  # SOL in a downtrend
    d = _crypto(paths, n)
    d0 = C.TREND_MIN_HISTORY - 1  # first row on which a coin has enough history
    for sizing, expected in [("equal", [0.5, 0.5, 0.0]), ("inv_vol", [2 / 3, 1 / 3, 0.0])]:
        _, w, info = C.trend_weights(d, _trend(coins="btc_eth_sol", rule="sma", n=50, sizing=sizing, rebalance="D"))
        assert _book(w).iloc[:d0].to_numpy().sum() == 0.0  # nothing held before the warm-up (same for every trial)
        assert info["mask"][d0]  # entered on the first eligible row (set changed)
        np.testing.assert_allclose(w.iloc[d0].to_numpy(), expected, atol=1e-9)
        assert _book(w).sum(axis=1).max() <= 1.0 + 1e-12
    # all coins in a downtrend -> cash
    _, w, _ = C.trend_weights(_crypto({"BTC/USD": -0.003, "ETH/USD": -0.002}, n), _trend(rule="sma", n=20))
    assert _book(w).to_numpy().sum() == 0.0


def test_trend_next_open_execution_and_exit_to_cash(monkeypatch):
    _zero_spread(monkeypatch)
    n, crash = 320, 260
    r = np.where(np.arange(n) < crash, 0.005, -0.03)
    gaps = 0.001 * (-1.0) ** np.arange(n)
    d = _crypto({"BTC/USD": r}, n, gaps={"BTC/USD": gaps})  # ETH missing -> BTC alone
    p = _trend(rule="sma", n=20, rebalance="D")
    res = C.TREND_SPEC.run(d, p, ZERO)
    _, w, info = C.trend_weights(d, p)
    btc = d.crypto["BTC/USD"]
    o, c = btc["open"].to_numpy(), btc["close"].to_numpy()
    rets = res.returns.to_numpy()
    d0 = C.TREND_MIN_HISTORY - 1
    assert w.iloc[d0, 0] == 1.0 and np.all(rets[: d0 + 1] == 0.0)
    assert rets[d0 + 1] == pytest.approx(c[d0 + 1] / o[d0 + 1] - 1)  # bought at the NEXT open
    assert rets[d0 + 2] == pytest.approx(c[d0 + 2] / c[d0 + 1] - 1)  # then held close to close
    exits = [i for i in np.flatnonzero(info["mask"]) if i > d0]
    assert len(exits) == 1 and crash <= exits[0] < crash + 5 and w.iloc[exits[0], 0] == 0.0
    x = exits[0]
    assert rets[x + 1] == pytest.approx(o[x + 1] / c[x] - 1)  # overnight leg, sold at the open
    assert np.all(rets[x + 2:] == 0.0)  # cash afterwards
    # exposure is held on rows d0+1 .. x (the exit trades at the open of x+1); live execution rows = d0+1 .. n-1
    assert res.notes["time_in_market"] == pytest.approx((x - d0) / (n - 1 - d0))
    # real costs: the entry pays half-spread + slippage (28 + 1 bp for BTC) on the traded notional
    monkeypatch.undo()
    res_c = C.TREND_SPEC.run(d, p, CostModel())
    assert res_c.returns.iloc[d0 + 1] == pytest.approx((1 - 29e-4) * c[d0 + 1] / o[d0 + 1] - 1)


def test_late_listed_coin_is_skipped_until_it_has_history():
    n, listed = 420, 100
    d = _crypto({"BTC/USD": -0.002, "ETH/USD": -0.002, "SOL/USD": 0.006}, n, listed={"SOL/USD": listed})
    _, w, _ = C.trend_weights(d, _trend(coins="btc_eth_sol", rule="sma", n=20))
    held = _book(w)["SOL/USD"].to_numpy()
    first = int(np.argmax(held > 0))
    assert first == listed + C.TREND_MIN_HISTORY - 1 and held[first] == 1.0  # pool: the only coin in trend gets the book
    # rotation: a late, explosive listing is not ranked before COIN_MIN_HISTORY real bars
    n, listed = 330, 250
    paths = {"BTC/USD": 0.002, "ETH/USD": 0.004, "SOL/USD": 0.006, "LTC/USD": -0.002, "AVAX/USD": 0.03}
    d = _crypto(paths, n, listed={"AVAX/USD": listed})
    _, w, _ = C.rotation_weights(d, _rot(lookback="r7", top_n=2, regime_n=50, rebalance="D"))
    b = _book(w)
    start = C.REGIME_MIN_HISTORY - 1
    np.testing.assert_allclose(b.iloc[start:listed + C.COIN_MIN_HISTORY - 1][["SOL/USD", "ETH/USD"]].to_numpy(), 0.5)
    assert b.iloc[: listed + C.COIN_MIN_HISTORY - 1]["AVAX/USD"].sum() == 0.0
    last = b.iloc[listed + C.COIN_MIN_HISTORY - 1]
    assert last["AVAX/USD"] == 0.5 and last["SOL/USD"] == 0.5 and last.sum() == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# crypto_momentum_rotation
# --------------------------------------------------------------------------- #


def test_rotation_regime_filter_unfilled_slots_and_warmup():
    n, crash = 330, 260
    btc = np.where(np.arange(n) < crash, 0.003, -0.02)
    d = _crypto({"BTC/USD": btc, "ETH/USD": 0.004}, n)
    _, w, info = C.rotation_weights(d, _rot(lookback="r14", top_n=3, regime_n=50, rebalance="D"))
    b = _book(w)
    start = C.REGIME_MIN_HISTORY - 1
    assert b.iloc[:start].to_numpy().sum() == 0.0  # nothing before BTC has REGIME_MIN_HISTORY bars (all trials)
    np.testing.assert_allclose(b.iloc[start:crash].to_numpy(), 1 / 3)  # 2 coins for 3 slots -> 1/3 each, 1/3 cash
    off = int(np.argmax(~info["risk_on"][crash:])) + crash
    assert crash <= off < crash + 5
    assert b.iloc[off:].to_numpy().sum() == 0.0  # BTC below its SMA -> all cash although ETH still rises
    res = C.ROTATION_SPEC.run(d, _rot(lookback="r14", top_n=3, regime_n=50, rebalance="D"), CostModel())
    assert res.exposure.iloc[start + 1] == pytest.approx(2 / 3)  # bought 2 x 1/3 at the next open
    assert res.exposure.max() < 1.0  # uninvested cash does not grow, so the invested share drifts up - never above 1
    assert 0.0 < res.notes["time_in_market"] < 1.0


def test_no_crypto_is_flat_on_the_stock_calendar():
    d = synthetic_data(["SPY", "QQQ"], start="2020-01-01", end="2020-12-31", seed=1)
    for spec in (C.TREND_SPEC, C.ROTATION_SPEC):
        res = spec.run(d, spec.default_params, CostModel())
        assert res.n_trades == 0 and res.returns.abs().sum() == 0.0 and len(res.returns) == len(d.dates())
    only_alts = _crypto({"DOGE/USD": 0.01}, 300)
    assert C.ROTATION_SPEC.run(only_alts, C.ROTATION_SPEC.default_params, CostModel()).n_trades == 0  # no BTC filter -> flat


# --------------------------------------------------------------------------- #
# Schedule, re-weight band, holes
# --------------------------------------------------------------------------- #


def test_weekly_and_daily_schedules():
    n = 40
    idx = pd.date_range(START, periods=n, freq="D")  # Monday; W-FRI weeks start on Saturdays
    target = pd.DataFrame({"A": np.where(np.arange(n) >= 2, 1.0, 0.0)}, index=idx)  # signal turns on Wednesday 01-06
    close = pd.DataFrame({"A": 100.0}, index=idx)
    wD, mD = C.schedule(target, close, "D")
    wW, mW = C.schedule(target, close, "W")
    assert np.flatnonzero(mD).tolist() == [2] and wD.iloc[2, 0] == 1.0
    first_sat = int(np.argmax(idx.dayofweek == 5))
    assert np.flatnonzero(mW).tolist() == [first_sat] and wW.iloc[first_sat, 0] == 1.0
    assert wW.drop(wW.index[first_sat]).isna().all().all()  # every other row = hold
    # re-weight band: 50/50 target, A jumps once. +10% drifts the book ~2.4 pts (no trade), +30% ~6.5 pts (re-weight
    # on the next first-session-of-week only)
    tgt = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    for jump, expect_reweight in [(1.10, False), (1.30, True)]:
        a = np.where(np.arange(n) >= 10, 100 * jump, 100.0)
        px = pd.DataFrame({"A": a, "B": 100.0}, index=idx)
        for freq in ("D", "W"):
            w, m = C.schedule(tgt, px, freq)
            rows = np.flatnonzero(m).tolist()
            entry = 0  # row 0 is a first session of a week too (and the D set change)
            later_sats = [i for i in range(11, n) if idx[i].dayofweek == 5]
            assert rows == ([entry, later_sats[0]] if expect_reweight else [entry]), (jump, freq, rows)


def test_untradable_held_coin_keeps_weight_and_others_are_scaled():
    n = 30
    idx = pd.date_range(START, periods=n, freq="D")
    tgt = pd.DataFrame({"A": 0.5, "B": 0.5, "C": 0.0}, index=idx)
    tgt.iloc[12:] = [0.0, 0.5, 0.5]  # A leaves the selection while it has no price
    px = pd.DataFrame({"A": 100.0, "B": 100.0, "C": 100.0}, index=idx)
    px.iloc[11:16, 0] = np.nan  # long hole in A
    w, m = C.schedule(tgt, px, "D")
    assert m[12]
    np.testing.assert_allclose(w.iloc[12].to_numpy(), [0.5, 0.25, 0.25])  # A stuck at 0.5, B+C scaled into 0.5
    assert np.nansum(w.to_numpy(), axis=1).max() <= 1.0 + 1e-12
    after = [i for i in np.flatnonzero(m) if i > 12]
    assert after and after[0] == 16 and w.iloc[16].tolist() == [0.0, 0.5, 0.5]  # sold once A trades again


def test_short_feed_holes_are_filled_long_ones_are_not():
    idx = pd.date_range(START, periods=20, freq="D")
    df = _frame(idx, np.full(20, 0.01))
    holey = df.drop(idx[[5, 6]]).drop(idx[10:15])  # 2-day hole (filled) and 5-day hole (3 filled, 2 missing)
    f = C.fill_short_holes(holey)
    assert idx[5] in f.index and idx[6] in f.index and f.loc[idx[6], "close"] == df.loc[idx[4], "close"]
    assert f.loc[idx[5], "open"] == f.loc[idx[5], "close"] and f.loc[idx[5], "volume"] == 0.0
    assert idx[12] in f.index and idx[13] not in f.index and idx[14] not in f.index
    pd.testing.assert_frame_equal(f.loc[idx[15]:], df.loc[idx[15]:], check_freq=False)
    # history counts REAL bars only
    d = ResearchData({}, {}, {}, {"BTC/USD": holey})
    _, _, close, hist = C.prepare(d, ["BTC/USD"])
    assert hist["BTC/USD"].iloc[-1] == len(holey) and close["BTC/USD"].notna().sum() == len(holey) + 5
    assert C.printed(hist)["BTC/USD"].tolist() == close.index.isin(holey.index).tolist()  # filled rows are not prints
    assert int(C.printed(hist)["BTC/USD"].sum()) == len(holey)
    # a TRAILING hole is filled the same way, up to the end of the feed (whether the coin prints again is unknown)
    t = C.fill_short_holes(df.iloc[:10], end=idx[15])
    assert t.index[-1] == idx[12] and (t.loc[idx[10]:, "close"] == df.loc[idx[9], "close"]).all()
    assert C.fill_short_holes(df.iloc[:10], end=idx[11]).index[-1] == idx[11]


def test_trailing_hole_decision_is_causal():
    """ETH misses the bars of the day BTC exits and the next one. In the full data the hole is followed by bars, in the
    data truncated inside the hole it is not; the decision taken inside the hole must not depend on which is the case."""
    n = 330
    d = _crypto({"BTC/USD": np.where(np.arange(n) < 295, 0.004, -0.05), "ETH/USD": 0.003}, n)
    p = _trend(rule="sma", n=20, rebalance="D")
    _, w0, i0 = C.trend_weights(d, p)
    x = [i for i in np.flatnonzero(i0["mask"]) if i > 250][0]  # BTC exit decision on clean data: ETH takes the book
    assert w0.iloc[x].tolist() == [0.0, 1.0]
    idx = d.crypto["BTC/USD"].index
    d.crypto["ETH/USD"] = d.crypto["ETH/USD"].drop(idx[[x, x + 1]])
    _, w, info = C.trend_weights(d, p)
    for cut in (idx[x], idx[x + 1]):
        _, wp, _ = C.trend_weights(d.truncate(cut), p)
        pd.testing.assert_frame_equal(w.loc[:cut], wp.loc[:cut], check_freq=False)
        for spec, q in ((C.TREND_SPEC, p), (C.ROTATION_SPEC, _rot(lookback="r7", top_n=2, regime_n=50, rebalance="D"))):
            a, b = spec.run(d, q, CostModel()).returns.loc[:cut], spec.run(d.truncate(cut), q, CostModel()).returns.loc[:cut]
            np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), atol=1e-12)
    # BTC is sold on the exit day; ETH (no print that day) is frozen at its drifted half, not bought up at a stale price ...
    assert w.iloc[x, 0] == 0.0 and 0.45 < w.iloc[x, 1] < 0.55
    # ... and in "D" the rest is bought on the first day ETH prints again (not at the next weekly check)
    nxt = [i for i in np.flatnonzero(info["mask"]) if i > x]
    assert nxt[0] == x + 2 and w.iloc[x + 2].tolist() == [0.0, 1.0]
    # rotation: held ETH (rank 2 of 3) misses two bars. Its filled close keeps it ranked - in the truncated data too,
    # otherwise BTC would replace it there but not in the full data
    y = 300
    d = _crypto({"BTC/USD": 0.002, "ETH/USD": 0.004, "SOL/USD": 0.006}, n)
    d.crypto["ETH/USD"] = d.crypto["ETH/USD"].drop(idx[[y, y + 1]])
    q = _rot(lookback="r7", top_n=2, regime_n=50, rebalance="D")
    _, w, _ = C.rotation_weights(d, q)
    assert _book(w).iloc[y - 1].tolist() == [0.0, 0.5, 0.5] and _book(w).iloc[y + 1].tolist() == [0.0, 0.5, 0.5]
    for cut in (idx[y], idx[y + 1]):
        _, wp, _ = C.rotation_weights(d.truncate(cut), q)
        pd.testing.assert_frame_equal(w.loc[:cut], wp.loc[:cut], check_freq=False)


def test_held_coin_is_not_sold_inside_a_hole_that_outlasts_the_fill(monkeypatch):
    """SOL (held, top-1) stops printing for 8 days. Its stale filled close falls behind ETH's momentum on the filled days;
    selling it then would fail on day FFILL_LIMIT+1 (no bar) while ETH is bought: a 200% book. It must stay frozen."""
    _zero_spread(monkeypatch)
    n, h, hole = 330, 280, 8
    d = _crypto({"BTC/USD": 0.003, "ETH/USD": 0.004, "SOL/USD": 0.006}, n)
    idx = d.crypto["BTC/USD"].index
    d.crypto["SOL/USD"] = d.crypto["SOL/USD"].drop(idx[h:h + hole])
    p = _rot(lookback="r7", top_n=1, regime_n=50, rebalance="D")
    _, w, info = C.rotation_weights(d, p)
    assert _book(w).iloc[h - 1]["SOL/USD"] == 1.0
    assert not info["mask"][h - 1:h + hole].any()  # no decision while SOL has no print
    margin_only = CostModel(open_slippage_bps=0, stop_slippage_bps=0, close_slippage_bps=0, sec_fee_rate=0)  # 7% margin rate
    res = C.ROTATION_SPEC.run(d, p, margin_only)
    assert res.exposure.max() <= 1.0 + 1e-12 and res.costs.max() == 0.0  # never borrowed: no margin interest charged
    # the frozen held coin earns nothing inside the hole and the move across it is booked when it prints again
    sol = d.crypto["SOL/USD"]["close"]
    assert np.all(res.returns.iloc[h:h + hole].to_numpy() == 0.0)
    assert res.returns.iloc[h + hole] == pytest.approx(sol.loc[idx[h + hole]] / sol.loc[idx[h - 1]] - 1)


def test_book_model_books_the_move_across_a_hole():
    """The re-weight band is judged on a model of the drifted book; a +40% move across A's missing bars must count."""
    n = 30
    idx = pd.date_range(START, periods=n, freq="D")  # Monday; Saturdays at rows 5, 12, 19, 26
    tgt = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    a = np.where(np.arange(n) < 8, 100.0, 140.0)
    px = pd.DataFrame({"A": a, "B": 100.0}, index=idx)
    px.iloc[8:11, 0] = np.nan  # A has no price on rows 8-10 and prints 140 on row 11
    w, m = C.schedule(tgt, px, "W")
    assert np.flatnonzero(m).tolist() == [0, 12]  # A drifted to 0.7/1.2 = 58%: re-weighted on the next weekly row
    np.testing.assert_allclose(w.iloc[12].to_numpy(), [0.5, 0.5])


# --------------------------------------------------------------------------- #
# Causality with crypto data (the generic test fixture carries no crypto)
# --------------------------------------------------------------------------- #


def _staggered(holes: bool) -> ResearchData:
    d = synthetic_data(["SPY"], start="2019-01-01", end="2023-06-30", seed=11, crypto_symbols=tuple(CRYPTO), crypto_start="2019-01-01")
    for s, first in {"SOL/USD": "2019-09-15", "AVAX/USD": "2020-06-01", "UNI/USD": "2021-01-10", "AAVE/USD": "2021-08-01"}.items():
        d.crypto[s] = d.crypto[s][d.crypto[s].index >= first]
    if holes:
        rng = np.random.default_rng(3)
        for s in ("DOGE/USD", "LINK/USD", "AAVE/USD"):  # feed holes: many short ones (filled) plus one long one each
            df = d.crypto[s]
            drop = set(rng.choice(len(df), 40, replace=False).tolist())
            start = int(rng.integers(100, len(df) - 20))
            drop |= set(range(start, start + 6))
            d.crypto[s] = df.drop(df.index[sorted(drop)])
    return d


@pytest.fixture(scope="module")
def staggered():
    """Late listings AND feed holes."""
    return _staggered(holes=True)


@pytest.fixture(scope="module")
def staggered_clean():
    """Late listings, complete daily bars."""
    return _staggered(holes=False)


def _sample(spec, k):
    """~k grid points spread over the grid, each in BOTH schedules ("rebalance" is the last, fastest-varying
    grid key, so trial i and i^1 differ only in it), plus the defaults."""
    trials = spec.trials()
    assert list(spec.param_grid)[-1] == "rebalance"
    idx = set(np.linspace(0, len(trials) - 1, k).astype(int).tolist())
    idx |= {i ^ 1 for i in idx if (i ^ 1) < len(trials)}
    return [trials[i] for i in sorted(idx)] + [dict(spec.default_params)]


def _hole_cutoffs(d: ResearchData) -> list[pd.Timestamp]:
    """Cutoffs INSIDE feed holes: day 2 (filled) and day 5 (past FFILL_LIMIT) of LINK's long hole, and a
    one-day DOGE hole - truncating there leaves a trailing hole whose fill must not depend on later bars."""
    cal = d.crypto["BTC/USD"].index
    link = cal.difference(d.crypto["LINK/USD"].index)
    starts = link[~link.isin(link + pd.Timedelta(days=1))]
    longest = max(starts, key=lambda t: sum((t + pd.Timedelta(days=j)) in link for j in range(10)))
    doge = cal.difference(d.crypto["DOGE/USD"].index)
    single = [t for t in doge if t >= pd.Timestamp("2020-06-01") and (t - pd.Timedelta(days=1)) not in doge
              and (t + pd.Timedelta(days=1)) not in doge]
    assert (longest + pd.Timedelta(days=4)) in link and single
    return [longest + pd.Timedelta(days=1), longest + pd.Timedelta(days=4), single[0]]


@pytest.mark.parametrize("spec", [C.TREND_SPEC, C.ROTATION_SPEC], ids=lambda s: s.name)
def test_truncation_invariance_with_crypto(spec, staggered):
    costs = CostModel()
    cutoffs = [pd.Timestamp(x) for x in ("2020-10-31", "2021-06-02", "2022-03-15")]  # Sat / Wed / Tue
    cutoffs += _hole_cutoffs(staggered)
    parts = {c: staggered.truncate(c) for c in cutoffs}
    for p in _sample(spec, 7):
        full = spec.run(staggered, p, costs)
        for cutoff in cutoffs:
            part = spec.run(parts[cutoff], p, costs)
            a = full.returns[full.returns.index <= cutoff]
            b = part.returns[part.returns.index <= cutoff]
            assert a.index.equals(b.index) and len(a) > 300
            np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), atol=1e-12, err_msg=f"{spec.name} {p} look-ahead")
            wa = full.weights[full.weights.index <= cutoff].fillna(0)
            wb = part.weights[part.weights.index <= cutoff].fillna(0)
            cols = wa.columns.intersection(wb.columns)
            np.testing.assert_allclose(wa[cols].to_numpy(), wb.loc[wa.index, cols].to_numpy(), atol=1e-12)
            assert full.notes["time_in_market"] >= 0.0


@pytest.mark.parametrize("spec", [C.TREND_SPEC, C.ROTATION_SPEC], ids=lambda s: s.name)
def test_long_only_gross_at_most_one(spec, staggered_clean, staggered):
    for p in _sample(spec, 12):
        for data, tol in ((staggered_clean, 1e-9), (staggered, 2e-3)):
            # tol on holey data: a frozen coin (no print on the decision day) that is still untradable at the next
            # open keeps its EXECUTED weight, which differs from the decision's book model by one overnight move
            res = spec.run(data, p, CostModel())
            assert res.exposure.max() <= 1.0 + tol, (p, res.exposure.max())
            assert (res.weights.to_numpy() >= -1e-12).all(), p
            if tol < 1e-6:
                assert res.costs.min() >= -1e-12  # cash earns nothing, no margin interest
            assert 0.0 <= res.notes["time_in_market"] <= 1.0 and res.notes["live_days"] > 0


def test_specs_are_preregistered_and_adaptive():
    for spec, lo in [(C.TREND_SPEC, 12), (C.ROTATION_SPEC, 12)]:
        n = len(spec.trials())
        assert lo <= n <= 120, (spec.name, n)
        assert spec.split_mode == "adaptive" and set(spec.symbols) <= set(CRYPTO)
        for k, v in spec.default_params.items():
            assert v in spec.param_grid[k], (spec.name, k)
        assert set(spec.default_params) == set(spec.param_grid)
