"""Crypto spot strategies (Alpaca spot: long-only, NO margin, NO shorting, 24/7, fractional).

Hypotheses
* crypto_trend - per-coin time-series momentum. BTC/USD and ETH/USD (optionally
  SOL/USD) are held only while each coin's own trend rule is "in"; the coins in
  trend share the book (equal or inverse-volatility weight), the rest is cash.
  Crypto returns show strong time-series momentum at 1-8 week horizons and
  moving-average rules predict BTC returns (Liu & Tsyvinski 2021 "Risks and
  Returns of Cryptocurrency"; Detzel, Liu, Strauss, Zhou & Zhu 2021), while the
  large crypto drawdowns (2018, May 2021, 2022) unfold as persistent downtrends.
* crypto_momentum_rotation - cross-sectional crypto momentum (Liu, Tsyvinski &
  Wu 2022 "Common Risk Factors in Cryptocurrency"): hold the top-N Alpaca pairs
  by trailing return, equal weight, but only while BTC/USD is above its n-day
  SMA - alt-coins lose 70-95% in market-wide bear phases, which BTC's trend
  identifies.

Mechanics (both strategies)
* everything runs on ``data.crypto_view()`` (crypto only, calendar-day index),
  so weekend bars never touch stock strategies and vice versa. Without crypto
  data the strategy is flat (zero returns on the stock calendar), not an error.
* feed holes: thin pairs can have days without a printed trade. The first
  FFILL_LIMIT days of every hole are filled with the last close (open=high=low=
  close, volume 0) in the view used for BOTH signals and the engine, also past a
  coin's last bar up to the end of the crypto feed (filling only holes that are
  known to end later would be look-ahead). The engine can therefore always trade
  a coin the day after it printed. "History" counts REAL bars only, so a
  late-listed coin is skipped until it has enough data of its own.
* every trial of a strategy uses the SAME eligibility thresholds (sized for the
  longest window in its grid), so all trials are evaluated over the same live
  window (fair trial comparison).
* decisions use closes through the decision date only (backward rolling windows
  and shifts); the engine executes them at the NEXT open. Long-only, gross <= 1,
  never borrowed cash (Alpaca crypto has no margin).
* schedule ("rebalance"): "W" = decisions only on the first session of each new
  week (``common.rebalance_mask``, first-session semantics; for a 7-day calendar
  that is the Saturday bar); "D" = the same weekly re-weighting PLUS an
  immediate target on any day the set of held coins changes. All other rows are
  all-NaN = hold the drifted position (no trade). A weekly re-weight of an
  unchanged set is skipped unless some coin drifted >= REWEIGHT_BAND from its
  target (whole-book band, judged on a causal model of the drifted book). The
  engine's per-coin band is 0: a per-coin band can keep one coin above target
  while another is bought up to target, i.e. borrow - impossible on Alpaca crypto.
* a coin that did not PRINT on the decision date (inside a hole, filled or not)
  is frozen at its book weight: held -> neither sold nor topped up, unheld -> not
  bought (no fills at stale prices), and the other targets are scaled into the
  remaining capital. Reason: such a coin may be untradable at the next open (day
  FFILL_LIMIT+1 of a long hole); selling it on a filled day while buying the
  others put the book at 200% (borrowed) for days in a hand-built case. Residual:
  the frozen coin's executed weight differs from the decision's causal book model
  by the next overnight move, so gross can exceed 1 by ~0.1% while it stays
  untradable (the engine charges margin interest on it).
* costs: crypto half-spreads in universe.py already include the 25 bp taker fee
  per side (~58 bp round trip for BTC), which is why whipsaw filters, weekly
  schedules and the re-weight band exist.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ResearchData, StrategyResult, StrategySpec, register
from ..engine import run_weights
from ..universe import CRYPTO
from .common import rebalance_mask

BTC = "BTC/USD"
TREND_COINS: dict[str, list[str]] = {"btc_eth": ["BTC/USD", "ETH/USD"], "btc_eth_sol": ["BTC/USD", "ETH/USD", "SOL/USD"]}
FFILL_LIMIT = 3  # days a missing crypto bar is bridged with the last close
REWEIGHT_BAND = 0.05  # re-weight an unchanged book only when some coin drifted >= 5 pts from its target
ENGINE_BAND = 0.0  # every emitted target is traded in full (see module docstring)
TREND_BAND = 0.03  # "sma_band" hysteresis: enter > SMA*(1+3%), exit < SMA*(1-3%) (~1 daily sigma of BTC)
VOL_DAYS = 30  # inverse-vol sizing window (calendar days of log returns)
TREND_MIN_HISTORY = 210  # bars before a coin can be held: > SMA200 / Donchian(200 prior closes) and the vol window
COIN_MIN_HISTORY = 61  # rotation: bars before a coin can be ranked (60-day return needs 61 closes)
REGIME_MIN_HISTORY = 200  # rotation: BTC bars before ANY trade (longest regime SMA in the grid)

# rotation score: average of simple trailing returns close[t]/close[t-L]-1 over the legs
LOOKBACKS: dict[str, tuple[int, ...]] = {"r7": (7,), "r14": (14,), "r30": (30,), "blend": (7, 14, 30, 60), "r60": (60,)}


# --------------------------------------------------------------------------- #
# Data preparation
# --------------------------------------------------------------------------- #


def _flat(data: ResearchData, cv: ResearchData, reason: str) -> StrategyResult:
    idx = cv.dates()
    if not len(idx):
        idx = data.dates()
    z = pd.Series(0.0, idx)
    return StrategyResult(z, z.copy(), z.copy(), z.copy(), z.copy(), 0, weights=pd.DataFrame(index=idx),
                          notes={"flat_reason": reason, "time_in_market": 0.0})


def fill_short_holes(df: pd.DataFrame, limit: int = FFILL_LIMIT, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Calendar-daily bars with the first ``limit`` days of every hole filled by the
    last close (flat bar, zero volume); later days of a longer hole stay missing.

    Causal: whether day t is filled depends only on bars <= t. The fill therefore
    runs past the coin's own last bar up to ``end`` (the last date of the crypto
    feed, i.e. "now"); stopping at the coin's last bar would fill a day only when
    the coin is known to print again LATER - look-ahead (a decision on a day
    inside a trailing hole would differ between the truncated and the full data)."""
    if df.empty:
        return df
    df = df.sort_index()
    last = df.index.max() if end is None else max(df.index.max(), pd.Timestamp(end))
    x = df.reindex(pd.date_range(df.index.min(), last, freq="D"))
    close = x["close"].ffill(limit=limit)
    filled = (x["close"].isna() & close.notna()).to_numpy(bool)
    x["close"] = close
    for col in ("open", "high", "low"):
        x[col] = x[col].mask(filled, close)
    if "volume" in x:
        x["volume"] = x["volume"].mask(filled, 0.0)
    return x[x["close"].notna()]


def prepare(data: ResearchData, wanted: list[str]) -> tuple[ResearchData, list[str], pd.DataFrame, pd.DataFrame]:
    """(hole-filled crypto view, coins present, close panel, count of REAL bars through each row)."""
    cv = data.crypto_view()
    coins = [s for s in wanted if s in cv.daily and len(cv.daily[s])]
    feed_end = max((df.index.max() for df in cv.daily.values() if len(df)), default=None)
    fv = ResearchData({s: fill_short_holes(cv.daily[s], end=feed_end) for s in coins}, {},
                      dict(cv.meta, filled_holes_max_days=FFILL_LIMIT))
    close = fv.panel("close", coins)
    hist = cv.panel("close", coins).reindex(close.index).notna().cumsum()
    return fv, coins, close, hist


def printed(hist: pd.DataFrame) -> pd.DataFrame:
    """True where the coin has a REAL bar (a printed trade) on that row - not a filled flat bar or a hole."""
    return hist.diff().fillna(hist).gt(0)


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #


def _hysteresis(enter: pd.DataFrame, exit_: pd.DataFrame) -> pd.DataFrame:
    """1 after an enter signal, 0 after an exit signal, previous state otherwise (causal ffill)."""
    state = pd.DataFrame(np.nan, index=enter.index, columns=enter.columns)
    state = state.mask(exit_.to_numpy(bool), 0.0).mask(enter.to_numpy(bool), 1.0)
    return state.ffill().fillna(0.0)


def trend_state(close: pd.DataFrame, rule: str, n: int) -> pd.DataFrame:
    """Per-coin in-trend flag (1.0/0.0) from closes through each row.

    * "sma":      in while close > SMA(n)
    * "sma_band": enter when close > SMA(n)*(1+TREND_BAND), exit when close < SMA(n)*(1-TREND_BAND)
    * "donchian": enter when close > max of the PRIOR n closes, exit when close < min of the PRIOR n//2 closes
    A coin with no price (or no defined window) is out.
    """
    no_px = close.isna()
    if rule in ("sma", "sma_band"):
        sma = close.rolling(n, min_periods=n).mean()
        if rule == "sma":
            return ((close > sma) & sma.notna()).astype(float)
        enter = close > sma * (1.0 + TREND_BAND)
        exit_ = (close < sma * (1.0 - TREND_BAND)) | sma.isna() | no_px
        return _hysteresis(enter, exit_)
    if rule == "donchian":
        prior = close.shift(1)
        hi = prior.rolling(n, min_periods=n).max()
        m = max(n // 2, 1)
        lo = prior.rolling(m, min_periods=m).min()
        return _hysteresis(close > hi, (close < lo) | no_px)
    raise ValueError(f"unknown trend rule {rule}")


def momentum_score(close: pd.DataFrame, scheme: str) -> pd.DataFrame:
    """Average of trailing simple returns over the scheme's legs (backward shifts only).
    NaN until every leg has history."""
    total = None
    for lb in LOOKBACKS[scheme]:
        leg = close / close.shift(lb) - 1.0
        total = leg if total is None else total + leg
    return total / len(LOOKBACKS[scheme])


def top_n_mask(scores: pd.DataFrame, top_n: int) -> np.ndarray:
    """Boolean (rows x coins): the ``top_n`` largest FINITE scores per row (ties -> column order)."""
    s = scores.to_numpy(float)
    finite = np.isfinite(s)
    if s.shape[1] == 0:
        return finite
    order = np.argsort(np.where(finite, -s, np.inf), axis=1, kind="stable")
    ranks = np.argsort(order, axis=1, kind="stable")
    return finite & (ranks < top_n)


# --------------------------------------------------------------------------- #
# Decision schedule
# --------------------------------------------------------------------------- #


def schedule(target: pd.DataFrame, close: pd.DataFrame, freq: str,
             traded: pd.DataFrame | None = None) -> tuple[pd.DataFrame, np.ndarray]:
    """Decision-date weights: a row on decision dates, all-NaN (= hold, no trade) otherwise.

    A causal model of the book (last emitted row drifted with close-to-close
    returns through row t, a move across a missing bar booked when the coin
    prices again - as the engine does) decides whether row t trades:
    * "W": only on the first session of a new week, and only if the set of coins
      changes or some coin is >= REWEIGHT_BAND away from its target;
    * "D": the same weekly re-weighting PLUS a row whenever the target's set of
      coins differs from the book's (signals acted on the day they change), and,
      after a row that a frozen coin cut short, on the first day the remainder
      can be traded (drift >= REWEIGHT_BAND);
    ``traded`` (default: close is known) marks coins that PRINTED a trade on row t.
    A coin that did not (feed hole, or a filled flat bar) is frozen: it may not be
    tradable at the next open either (a hole longer than FFILL_LIMIT), so it keeps
    its book weight - a held coin is neither sold nor topped up, an unheld one is
    not bought at a stale price - and the other targets are scaled into the
    remaining capital. Selling a frozen coin while buying the others would leave
    the book above 100% (borrowed) whenever the coin then could not trade.
    An emitted row never sums above 1. Uses rows <= t only."""
    if freq not in ("D", "W"):
        raise ValueError(f"unknown rebalance {freq}")
    weekly = rebalance_mask(target.index, "W").to_numpy(bool)
    tgt = target.to_numpy(float)
    px_df = close.reindex(index=target.index, columns=target.columns)
    px = px_df.to_numpy(float)
    n, k = tgt.shape
    live = np.isfinite(px)
    if traded is not None:
        live &= traded.reindex(index=target.index, columns=target.columns, fill_value=False).to_numpy(bool)
    growth = np.ones((n, k))
    if n > 1:
        prev = px_df.ffill().to_numpy(float)[:-1]  # last KNOWN close before row t
        with np.errstate(divide="ignore", invalid="ignore"):
            g = px[1:] / prev
        growth[1:] = np.where(np.isfinite(g) & (g > 0), g, 1.0)
    out = np.full((n, k), np.nan)
    mask = np.zeros(n, dtype=bool)
    book = np.zeros(k)
    pending = False  # "D": the last emitted row was cut short by a frozen coin -> finish it once it can trade
    for i in range(n):
        if i:
            grown = book * growth[i]
            value = 1.0 - book.sum() + grown.sum()
            book = grown / value if value > 0 else grown * 0.0
        row = tgt[i]
        frozen = ~live[i]
        constrained = False
        if frozen.any():
            row = row.copy()
            row[frozen] = np.where(book[frozen] > 1e-12, book[frozen], 0.0)
            free = max(0.0, 1.0 - float(row[frozen].sum()))
            rest = float(row[~frozen].sum())
            if rest > free:
                row[~frozen] *= free / rest
            constrained = bool(np.abs(row - tgt[i]).max() > 1e-12)
        held_now, held_book = row > 1e-12, book > 1e-12
        set_diff = bool((held_now != held_book).any())
        drift = bool(np.abs(row - book).max() >= REWEIGHT_BAND) if k else False
        if (freq == "D" and (set_diff or (pending and drift))) or (weekly[i] and (set_diff or drift)):
            mask[i] = True
            out[i] = row
            book = row.copy()
            pending = constrained
        elif not constrained:
            pending = False  # the target is reachable today and within the band: nothing left to finish
    return pd.DataFrame(out, index=target.index, columns=target.columns), mask


def _diagnostics(res: StrategyResult, w: pd.DataFrame, live: np.ndarray, mask: np.ndarray, coins: list[str]) -> dict:
    """Time in market etc. over the LIVE window (rows after the strategy's warm-up).
    The engine's exposure on row i is the book decided on row i-1; the book's
    composition is the last emitted row (decision weights forward-filled)."""
    index = w.index
    n = len(live)
    exec_live = np.zeros(n, dtype=bool)
    exec_live[1:] = live[:-1]
    expo = res.exposure.reindex(index).fillna(0.0).to_numpy(float)
    n_live = int(exec_live.sum())
    book = (w.ffill().fillna(0.0).to_numpy(float) > 1e-12)[live]
    changes = int((book[1:] != book[:-1]).any(axis=1).sum()) if len(book) > 1 else 0
    return {
        "universe": list(coins), "band": ENGINE_BAND, "reweight_band": REWEIGHT_BAND,
        "live_from": str(index[int(np.argmax(live))].date()) if live.any() else None,
        "live_days": n_live,
        "time_in_market": float((expo[exec_live] > 1e-9).mean()) if n_live else 0.0,
        "avg_gross_exposure": float(expo[exec_live].mean()) if n_live else 0.0,
        "share_of_live_days_held": {c: float(book[:, j].mean()) if len(book) else 0.0 for j, c in enumerate(coins)},
        "decision_rows": int((mask & live).sum()),
        "book_changes": changes,
    }


# --------------------------------------------------------------------------- #
# (a) crypto_trend
# --------------------------------------------------------------------------- #


def trend_weights(data: ResearchData, p: dict) -> tuple[ResearchData, pd.DataFrame, dict]:
    """(engine view, decision-date weights with all-NaN hold rows, internals for diagnostics/tests)."""
    fv, coins, close, hist = prepare(data, TREND_COINS[p["coins"]])
    eligible = (hist >= TREND_MIN_HISTORY) & close.notna()
    state = trend_state(close, p["rule"], int(p["n"])).where(eligible, 0.0)
    held = state.to_numpy(float) > 0
    if p["sizing"] == "inv_vol":
        vol = np.log(close).diff().rolling(VOL_DAYS, min_periods=(2 * VOL_DAYS) // 3).std().to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = np.where(np.isfinite(vol) & (vol > 0), 1.0 / vol, np.nan)
        bad = (held & ~np.isfinite(inv)).any(axis=1)  # an in-trend coin without a vol estimate -> equal weight that row
        size = np.where(bad[:, None], 1.0, np.nan_to_num(inv, nan=0.0))
    elif p["sizing"] == "equal":
        size = np.ones(held.shape)
    else:
        raise ValueError(f"unknown sizing {p['sizing']}")
    raw = np.where(held, size, 0.0)
    tot = raw.sum(axis=1, keepdims=True)
    target = pd.DataFrame(np.divide(raw, tot, out=np.zeros_like(raw), where=tot > 0), index=close.index, columns=coins)
    w, mask = schedule(target, close, p["rebalance"], traded=printed(hist))
    live = eligible.any(axis=1).to_numpy(bool)
    return fv, w, {"coins": coins, "held": held, "mask": mask, "live": live, "target": target}


def run_trend(data: ResearchData, p: dict, costs) -> StrategyResult:
    cv = data.crypto_view()
    if not any(s in cv.daily and len(cv.daily[s]) for s in TREND_COINS[p["coins"]]):
        return _flat(data, cv, "no trend coin in crypto data")
    fv, w, info = trend_weights(data, p)
    res = run_weights(fv, w, costs, band=ENGINE_BAND)
    res.notes.update(_diagnostics(res, w, info["live"], info["mask"], info["coins"]))
    return res


# --------------------------------------------------------------------------- #
# (b) crypto_momentum_rotation
# --------------------------------------------------------------------------- #


def rotation_weights(data: ResearchData, p: dict) -> tuple[ResearchData, pd.DataFrame, dict]:
    fv, coins, close, hist = prepare(data, CRYPTO)
    top_n = int(p["top_n"])
    score = momentum_score(close, p["lookback"])
    eligible = (hist >= COIN_MIN_HISTORY) & close.notna() & score.notna()
    score = score.where(eligible)
    btc = close[BTC]
    n = int(p["regime_n"])
    sma = btc.rolling(n, min_periods=n).mean()
    regime_ready = (hist[BTC] >= REGIME_MIN_HISTORY).to_numpy(bool)
    risk_on = ((btc > sma) & sma.notna()).to_numpy(bool) & regime_ready
    held = top_n_mask(score, top_n) & risk_on[:, None]
    target = pd.DataFrame(held.astype(float) / float(top_n), index=close.index, columns=coins)  # unfilled slots = cash
    w, mask = schedule(target, close, p["rebalance"], traded=printed(hist))
    return fv, w, {"coins": coins, "held": held, "mask": mask, "live": regime_ready, "risk_on": risk_on, "target": target}


def run_rotation(data: ResearchData, p: dict, costs) -> StrategyResult:
    cv = data.crypto_view()
    if BTC not in cv.daily or not len(cv.daily[BTC]):
        return _flat(data, cv, "BTC/USD (regime filter) not in crypto data")
    fv, w, info = rotation_weights(data, p)
    res = run_weights(fv, w, costs, band=ENGINE_BAND)
    res.notes.update(_diagnostics(res, w, info["live"], info["mask"], info["coins"]))
    live = info["live"]
    res.notes["share_of_live_days_risk_on"] = float(info["risk_on"][live].mean()) if live.any() else 0.0
    return res


# --------------------------------------------------------------------------- #
# Registration (grids are PRE-REGISTERED; every combination is a trial)
# --------------------------------------------------------------------------- #

# Splits: both specs list only BTC/USD + ETH/USD, so the adaptive 55/20/25% split
# covers the longest common history of the core coins; SOL and the other pairs
# join each strategy causally once they have enough bars of their own.

TREND_SPEC = register(StrategySpec(
    name="crypto_trend",
    family="crypto_trend_following",
    hypothesis=("Holding BTC/USD and ETH/USD spot (optionally SOL/USD) only while each coin's own trend rule is on - close above "
                "its n-day SMA (plain or with a 3% hysteresis band) or a Donchian n-day-high entry / n/2-day-low exit - with the "
                "coins in trend sharing the book equally or by inverse volatility and cash otherwise, earns a higher after-cost "
                "Sharpe and a much smaller max drawdown than buy-and-hold BTC, because crypto returns have strong time-series "
                "momentum and crypto crashes unfold as persistent downtrends."),
    # 2 x 3 x 4 x 2 x 2 = 96 trials (lists ordered so sensitivity neighbours are adjacent)
    param_grid={"coins": ["btc_eth", "btc_eth_sol"], "rule": ["sma", "sma_band", "donchian"], "n": [20, 50, 100, 200],
                "sizing": ["equal", "inv_vol"], "rebalance": ["D", "W"]},
    default_params={"coins": "btc_eth", "rule": "sma_band", "n": 50, "sizing": "equal", "rebalance": "D"},
    run_fn=run_trend,
    symbols=("BTC/USD", "ETH/USD"),
    split_mode="adaptive",
))

ROTATION_SPEC = register(StrategySpec(
    name="crypto_momentum_rotation",
    family="crypto_cross_sectional_momentum",
    hypothesis=("Holding the top-N (1-3) of the Alpaca crypto pairs by trailing 7-60 day return, equal weight, rebalanced weekly "
                "(or on any change of the selection), and only while BTC/USD closes above its n-day SMA (cash otherwise), earns a "
                "positive after-cost Sharpe above buy-and-hold BTC, because cross-sectional crypto momentum persists over 1-8 "
                "weeks and the BTC regime filter sidesteps the market-wide bear phases in which alt-coins lose 70-95%."),
    # 5 x 3 x 3 x 2 = 90 trials; "blend" (mean of 7/14/30/60-day returns, mean lag ~21 days) sits between r30 and r60
    param_grid={"lookback": ["r7", "r14", "r30", "blend", "r60"], "top_n": [1, 2, 3], "regime_n": [50, 100, 200],
                "rebalance": ["D", "W"]},
    default_params={"lookback": "blend", "top_n": 2, "regime_n": 100, "rebalance": "W"},
    run_fn=run_rotation,
    symbols=("BTC/USD", "ETH/USD"),
    split_mode="adaptive",
))
