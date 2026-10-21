"""Cross-sectional / dual momentum rotation (asset classes and SPDR sectors).

Hypotheses
* xsmom_asset_rotation - relative strength persists across asset classes
  (Asness, Moskowitz & Pedersen 2013 "Value and Momentum Everywhere"; Faber
  2010 GTAA relative-strength rotation), and an absolute-momentum switch to
  T-bill-like SHY for assets that do not beat SHY's own trailing return
  (Antonacci 2014 "dual momentum") avoids most of the long bear markets.
* xsmom_sector_rotation - industry momentum (Moskowitz & Grinblatt 1999) at
  the sector-ETF level, optionally gated by a market trend filter (SPY above
  its 200-day SMA, Faber 2007) that moves the whole book to SHY when off.

Mechanics (both strategies)
* score(t) = trailing return measured through the CLOSE of t with one of three
  pre-registered schemes: "ret_6" (126 sessions), "blend_1_3_6_12" (equal
  average of the 21/63/126/252-session returns) or "ret_12_1" (252 sessions,
  skipping the most recent 21 - the standard 12-1 momentum).
* on the first session of each new week/month (``common.rebalance_mask``, no
  future-calendar knowledge) the top ``top_n`` scores get 1/top_n each. A slot
  that is unfilled (fewer scored assets than top_n), fails the absolute filter
  (score <= SHY's score over the same window) or is switched off by the market
  filter goes to SHY - or stays in cash when SHY is not in the data.
* between rebalances the book is buy-and-hold: decision weights drift with
  prices, so the engine does not trade back to equal weight every day; the
  no-trade ``band`` absorbs the residual overnight-gap drift.
* the engine executes decision-date weights at the NEXT open (gap included).
* every scheme waits WARMUP = 252 sessions before the first decision, so all
  trials are evaluated over the same live window (fair trial comparison).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ResearchData, StrategyResult, StrategySpec, register
from ..engine import run_weights
from .common import available, rebalance_mask

ASSET_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD", "DBC", "VNQ"]
SECTOR_UNIVERSE = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
DEFENSIVE = "SHY"  # absolute-momentum hurdle AND the parking asset for failed / risk-off slots
MARKET = "SPY"
SMA_DAYS = 200
WARMUP = 252  # sessions of history before the first decision (longest scheme needs 252)
FFILL_LIMIT = 5  # tolerate short data holes in a symbol, never stale prices for long

# scheme -> legs of (skip, lookback): return from close[t - lookback] to close[t - skip]
SCHEMES: dict[str, tuple[tuple[int, int], ...]] = {
    "ret_6": ((0, 126),),
    "blend_1_3_6_12": ((0, 21), (0, 63), (0, 126), (0, 252)),
    "ret_12_1": ((21, 252),),
}


def momentum_score(close: pd.DataFrame, scheme: str) -> pd.DataFrame:
    """Trailing return score through the close of each row (backward shifts only).
    NaN until every leg of the scheme has enough history."""
    legs = SCHEMES[scheme]
    total = None
    for skip, lookback in legs:
        leg = close.shift(skip) / close.shift(lookback) - 1.0
        total = leg if total is None else total + leg
    return total / len(legs)


def rotation_weights(scores: pd.DataFrame, top_n: int, hurdle: pd.Series | None = None, defensive: str | None = DEFENSIVE,
                     risk_off: pd.Series | None = None) -> pd.DataFrame:
    """Target weights on EVERY row (the caller samples them on rebalance dates).

    * top ``top_n`` finite scores get 1/top_n each (ties -> column order, deterministic);
    * ``hurdle`` (absolute momentum): a selected asset whose score is not strictly
      above the hurdle gives its slot away; a missing hurdle value counts as 0;
    * ``risk_off`` True -> no risky asset at all on that row;
    * every slot given away goes to ``defensive`` (None -> cash, weights sum < 1).
    """
    s = scores.to_numpy(float)
    n, k = s.shape
    finite = np.isfinite(s)
    if k:
        order = np.argsort(np.where(finite, -s, np.inf), axis=1, kind="stable")
        ranks = np.argsort(order, axis=1, kind="stable")
        chosen = finite & (ranks < top_n)
    else:
        chosen = np.zeros((n, 0), dtype=bool)
    if hurdle is not None:
        h = hurdle.reindex(scores.index).to_numpy(float)
        h = np.where(np.isfinite(h), h, 0.0)
        chosen &= s > h[:, None]
    if risk_off is not None:
        off = risk_off.reindex(scores.index).fillna(False).to_numpy(bool)
        chosen[off] = False
    w = pd.DataFrame(chosen.astype(float) / float(top_n), index=scores.index, columns=scores.columns)
    if defensive is not None:
        spare = 1.0 - w.sum(axis=1)
        w[defensive] = (w[defensive] if defensive in w.columns else 0.0) + spare.clip(lower=0.0)
    return w


def drift_between_rebalances(target: pd.DataFrame, mask: pd.Series | np.ndarray, open_: pd.DataFrame,
                             close: pd.DataFrame) -> pd.DataFrame:
    """Buy-and-hold between rebalances, expressed as decision-date weights.

    On a rebalance row r the weight is ``target[r]``. The engine fills it at the
    open of r+1; for every later decision row t of the same holding period the
    weight is target[r] grown by close[t] / open[r+1] (cash does not grow) and
    renormalized - exactly what the engine holds after the close of t, so it
    sees no rebalancing trade until the next rebalance row. Only rows <= t are
    used (open[r+1] with r+1 <= t), so this is causal.
    """
    tgt = target.to_numpy(float)
    n, k = tgt.shape
    m = np.asarray(mask, dtype=bool)
    pos = np.arange(n)
    last = np.maximum.accumulate(np.where(m, pos, -1)) if n else pos
    has = last >= 0
    base = np.where(has[:, None], tgt[np.maximum(last, 0)], 0.0)
    c = close.reindex(index=target.index, columns=target.columns).to_numpy(float)
    o = open_.reindex(index=target.index, columns=target.columns).to_numpy(float)
    anchor = o[np.minimum(np.maximum(last, 0) + 1, max(n - 1, 0))]
    fallback = c[np.maximum(last, 0)]
    anchor = np.where(np.isfinite(anchor) & (anchor > 0), anchor, fallback)
    with np.errstate(divide="ignore", invalid="ignore"):
        growth = c / anchor
    growth = np.where((pos > last)[:, None] & has[:, None] & np.isfinite(growth), growth, 1.0)
    grown = base * growth
    value = 1.0 - base.sum(axis=1) + grown.sum(axis=1)
    value = np.where(value > 0, value, 1.0)
    return pd.DataFrame(grown / value[:, None], index=target.index, columns=target.columns)


def _flat(data: ResearchData, reason: str) -> StrategyResult:
    idx = data.dates()
    z = pd.Series(0.0, idx)
    return StrategyResult(z, z.copy(), z.copy(), z.copy(), z.copy(), 0, weights=pd.DataFrame(index=idx),
                          notes={"flat_reason": reason})


def run_rotation(data: ResearchData, p: dict, costs, universe: list[str], use_market_filter: bool) -> StrategyResult:
    risky = [s for s in available(data, universe) if s != DEFENSIVE]
    defensive = DEFENSIVE if DEFENSIVE in data.daily else None
    cols = risky + ([defensive] if defensive else [])
    if not cols:
        return _flat(data, "no universe symbol in data")
    market = MARKET if use_market_filter and MARKET in data.daily else None
    need = cols + ([market] if market and market not in cols else [])
    close = data.panel("close", need).ffill(limit=FFILL_LIMIT)
    open_ = data.panel("open", need).reindex(close.index)
    n = len(close)

    scheme = p["lookback"]
    scores = momentum_score(close[risky], scheme)
    hurdle = None
    if p["abs_filter"]:
        hurdle = momentum_score(close[[defensive]], scheme)[defensive] if defensive else pd.Series(0.0, close.index)
    risk_off = None
    if market:
        spx = close[market]
        risk_off = spx < spx.rolling(SMA_DAYS, min_periods=SMA_DAYS).mean()

    target = rotation_weights(scores, int(p["top_n"]), hurdle, defensive, risk_off)[cols]
    live = np.arange(n) >= WARMUP
    target.iloc[:WARMUP] = 0.0
    mask = rebalance_mask(close.index, p["rebalance"]).to_numpy(bool) | (np.arange(n) == WARMUP)
    w = drift_between_rebalances(target, mask, open_[cols], close[cols])
    res = run_weights(data, w, costs, band=float(p["band"]))

    reb = mask & live
    risky_share = target.loc[reb, risky].sum(axis=1) if risky else pd.Series(0.0, target.index[reb])
    res.notes.update({
        "risky_universe": risky, "defensive": defensive or "cash", "market_filter": bool(market),
        "rebalances": int(reb.sum()),
        "avg_risky_share_at_rebalance": float(risky_share.mean()) if len(risky_share) else None,
    })
    return res


def run_asset(data, p, costs):
    return run_rotation(data, p, costs, ASSET_UNIVERSE, use_market_filter=False)


def run_sector(data, p, costs):
    return run_rotation(data, p, costs, SECTOR_UNIVERSE, use_market_filter=bool(p["market_filter"]))


_LOOKBACKS = ["ret_6", "blend_1_3_6_12", "ret_12_1"]  # ordered by horizon (sensitivity neighbours)

ASSET_SPEC = register(StrategySpec(
    name="xsmom_asset_rotation",
    family="cross_sectional_momentum",
    hypothesis=("Holding the top-N of 12 asset-class ETFs by trailing return (equal weight, rebalanced weekly/monthly, "
                "slots that fail to beat SHY's own trailing return parked in SHY) earns a positive after-cost Sharpe that "
                "a random re-timing of the same holdings does not, because relative and absolute momentum persist across "
                "asset classes."),
    # 3 x 3 x 2 x 2 = 36 trials. top_n 1/3/6 ~ Antonacci single-asset, Faber GTAA AGG3 / AGG6.
    param_grid={"lookback": list(_LOOKBACKS), "top_n": [1, 3, 6], "rebalance": ["W", "M"], "abs_filter": [False, True],
                "band": [0.01]},
    default_params={"lookback": "blend_1_3_6_12", "top_n": 3, "rebalance": "M", "abs_filter": True, "band": 0.01},
    run_fn=run_asset,
    symbols=tuple(ASSET_UNIVERSE + [DEFENSIVE]),
))

SECTOR_SPEC = register(StrategySpec(
    name="xsmom_sector_rotation",
    family="cross_sectional_momentum",
    hypothesis=("Holding the top-N of the 9 SPDR sector ETFs by trailing return (equal weight, rebalanced weekly/monthly, "
                "optional SHY switch for sectors that fail to beat SHY and for the whole book when SPY is below its 200-day "
                "SMA) earns a positive after-cost Sharpe that a random re-timing of the same holdings does not, because "
                "industry momentum persists at the sector level."),
    # 3 x 3 x 2 x 2 x 2 = 72 trials. top_n 2/3/4 brackets the top third of 9 sectors (Faber 2010 used top-3).
    param_grid={"lookback": list(_LOOKBACKS), "top_n": [2, 3, 4], "rebalance": ["W", "M"], "abs_filter": [False, True],
                "market_filter": [False, True], "band": [0.01]},
    default_params={"lookback": "blend_1_3_6_12", "top_n": 3, "rebalance": "M", "abs_filter": True, "market_filter": True,
                    "band": 0.01},
    run_fn=run_sector,
    symbols=tuple(SECTOR_UNIVERSE + [DEFENSIVE, MARKET]),
))
