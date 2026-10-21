"""Broad / leveraged ETF momentum rotation ("trade everything Alpaca has" for growth).

Hypotheses
* letf_momentum_rotation - relative strength persists among daily-reset
  leveraged ETFs (the 20 funds in universe.LEVERAGED + LEVERAGED_EXT: index,
  sector, country, gold-miner and treasury 2x/3x funds). Holding the top-N by
  trailing (optionally risk-adjusted) momentum, rebalanced weekly and stepping
  aside when SPY is below its 200-day SMA, compounds faster than buy-and-hold
  of a single leveraged ETF while avoiding the long bear markets in which
  volatility decay destroys them (cf. Gayed & Bilello 2016; Faber 2007).
* broad_etf_momentum - dual momentum (Antonacci 2014; Faber 2010) over the
  whole unlevered ETF list (CORE_DAILY + SECTORS + EXTENDED, 39 risky funds):
  the top-N by blended trailing return that also beat SHY's trailing return
  over the same window earn a positive after-cost Sharpe; failed slots are
  parked in SHY. Optional margin scales the risky slots.

SURVIVORSHIP-BIAS CAVEAT (read before believing any backtest of these)
  Only leveraged ETFs that STILL TRADE TODAY are in the universe. Many
  leveraged products were closed or delisted after crashes (e.g. the 3x oil /
  natural-gas products UWT, DWT, UGAZ, DGAZ in 2019-2020), and some survivors
  cut their leverage after drawdowns (NUGT and ERX went from 3x to 2x in 2020;
  universe.INSTRUMENTS records today's 2x factor - this module models their
  margin requirement as 3x before LEVERAGE_CUTS, but their pre-cut 3x price
  history is still the history of a survivor). A rotation that can only ever pick today's
  survivors never holds a fund on its way to zero, so backtests are biased
  UPWARD - possibly by a lot for a momentum rule that chases the most volatile
  funds. The unlevered EXTENDED list (ARKK, TAN, KWEB, URA, ...) was also
  picked with hindsight of popularity. Treat results as an upper bound.

Mechanics (both strategies)
* scores use closes through the decision close only (backward shifts):
    "blend"         mean of the 21/63/126-session returns (1/3/6 months)
    "blend_skip1w"  same legs, each ending 5 sessions ago (skip the last week)
    "riskadj"       "blend" / annualized 63-session realized vol (return per risk)
    "blend_1_3_6", "blend_1_3_6_12"  (broad) 1/3/6(/12)-month blends
* letf: at most ONE fund per underlying index is ranked (SSO/UPRO/SPXL track
  the S&P 500, QLD/TQQQ the Nasdaq-100), otherwise top-N would often be N
  copies of one index. Ties -> universe order.
* the top ``top_n`` funds get ``margin / top_n`` each: ``margin`` is the
  REQUESTED gross. The final decision frame is always margin-capped like
  ``common.cap_to_margin`` (sum |w_i| x requirement_i <= 97%): FINRA 4210
  requires 25% x leverage maintenance on leveraged ETFs, so a 3x book is cut
  to ~1.29x gross whatever is requested, a 2x book to ~1.94x, a 1x book to
  ~1.94x. The requirement is per SESSION: funds whose leverage was later cut
  (LEVERAGE_CUTS: NUGT, ERX 3x -> 2x on 2020-04-01) carry the 3x requirement
  before the cut. The effective gross is reported in ``notes``.
* maintenance calls (fixed mechanic, not a parameter): the book is held
  between rebalances, and a margined 3x book at ~1.29x breaches its 75%
  maintenance after a ~10% fall in the fund. On any session whose CLOSE
  shows equity below the maintenance requirement (max(30%, 25% x leverage)
  of each position) the strategy de-levers to the margin cap of the held
  book at the next open, like a broker liquidation, selling at least 1.5 x
  ``band`` of every held fund so the engine's no-trade band cannot swallow
  the forced sale. Only possible when margin > 1; counted in
  ``notes["margin_calls"]``. The held book is an exact replay of the
  engine's accounting (overnight gap, band-suppressed trades, intraday move;
  costs excluded) using only bars through the close being checked.
* letf regime filter (evaluated on rebalance sessions only): SPY close above
  its 200-session SMA = risk on. Risk off -> "cash" (all zero), "IEF" or "TMF"
  (weight 1.0; the defensive sleeve is NEVER margined); "off" = no filter.
  An undefined SMA counts as risk off.
* broad absolute filter: a selected fund whose blended return is not strictly
  above SHY's over the same legs gives its slot away. Failed slots are parked
  in SHY only out of UNBORROWED equity: SHY = max(0, min(1 - slot share,
  1 - risky gross)). With margin > 1 the risky slots may already borrow, and
  buying SHY on top would pay margin interest (7%) to earn the T-bill rate.
  No SHY in the data -> hurdle 0 and failed slots stay in cash.
* rebalance on the FIRST session of each week/month (common.rebalance_mask)
  plus a forced first decision right after the warm-up. Every other row sent to
  the engine is all-NaN (= hold the drifted position, no trade), so nothing
  trades except after a rebalance or a maintenance call. ``res.weights`` holds
  the decision on decision rows and, on every other row, the weights the
  engine actually holds at that close (the replayed book), for the null test.
* the engine executes decision-date weights at the NEXT open (gap included)
  and charges margin interest on gross above 1.
* warm-up is fixed per strategy (letf 200 sessions for SMA200, broad 252 for
  the 12-month leg), so every trial is evaluated over the same live window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ResearchData, StrategyResult, StrategySpec, register
from ..engine import run_weights
from ..universe import CORE_DAILY, EXTENDED, INSTRUMENTS, LEVERAGED, LEVERAGED_EXT, SECTORS
from .common import LETF_MAINT_PER_X, MARGIN_BUFFER, REG_T_INITIAL, available, margin_requirement, rebalance_mask
from .xsmom import rotation_weights

LETF_UNIVERSE = list(dict.fromkeys(LEVERAGED + LEVERAGED_EXT))
BROAD_UNIVERSE = list(dict.fromkeys(CORE_DAILY + SECTORS + EXTENDED))
MARKET = "SPY"
HURDLE = "SHY"  # broad: absolute-momentum hurdle AND parking asset
LETF_DEFENSIVE = ("IEF", "TMF")
# funds tracking the same underlying index: only the best-scored one is ranked
SAME_UNDERLYING = {"SP500": ["SSO", "UPRO", "SPXL"], "NDX100": ["QLD", "TQQQ"]}
SMA_DAYS = 200
VOL_DAYS = 63
MAX_MARGIN = 1.95  # just under Alpaca's ~2x overnight buying power
MAINT_LONG = 0.30  # maintenance on an ordinary long ETF (FINRA minimum 25%; brokers use ~30%)
# Surviving funds whose daily leverage was CUT; universe.INSTRUMENTS records today's factor. Before the first
# session at the new factor the fund was 3x, so FINRA 4210 required 25% x 3 = 75% (initial and maintenance)
# instead of today's 50%. Direxion moved NUGT and ERX from 3x to 2x effective 2020-04-01 (approximate date -
# check the prospectus supplement before relying on April 2020 exactly).
LEVERAGE_CUTS: dict[str, tuple[str, float]] = {"NUGT": ("2020-04-01", 3.0), "ERX": ("2020-04-01", 3.0)}
CALL_MIN_SELL_BANDS = 1.5  # a maintenance call sells >= 1.5 x band of each held fund (beats the engine's no-trade band)
FFILL_LIMIT = 5
LETF_WARMUP = 200
BROAD_WARMUP = 252

_M136 = ((0, 21), (0, 63), (0, 126))
# scheme -> legs of (skip, lookback): return from close[t - lookback] to close[t - skip]
LEGS: dict[str, tuple[tuple[int, int], ...]] = {
    "blend": _M136,
    "blend_skip1w": ((5, 21), (5, 63), (5, 126)),
    "riskadj": _M136,
    "blend_1_3_6": _M136,
    "blend_1_3_6_12": _M136 + ((0, 252),),
}

SURVIVORSHIP = ("universe = ETFs that still trade today; leveraged funds closed after crashes (UWT/UGAZ...) are absent "
                "and NUGT/ERX are survivors that cut leverage 3x->2x in 2020 (margined as 3x before the cut) "
                "-> backtest biased upward")


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #


def blended_return(close: pd.DataFrame, legs: tuple[tuple[int, int], ...]) -> pd.DataFrame:
    """Equal average of trailing leg returns through the close of each row (NaN until all legs exist)."""
    total = None
    for skip, lookback in legs:
        leg = close.shift(skip) / close.shift(lookback) - 1.0
        total = leg if total is None else total + leg
    return total / len(legs)


def realized_vol(close: pd.DataFrame, n: int = VOL_DAYS) -> pd.DataFrame:
    """Annualized std of daily log returns over the trailing ``n`` sessions (zero vol -> NaN)."""
    vol = np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(252)
    return vol.where(vol > 1e-12)


def momentum_score(close: pd.DataFrame, scheme: str) -> pd.DataFrame:
    if scheme not in LEGS:
        raise ValueError(f"unknown score {scheme}")
    ret = blended_return(close, LEGS[scheme])
    return ret / realized_vol(close) if scheme == "riskadj" else ret


def one_per_underlying(scores: pd.DataFrame, groups: dict[str, list[str]] = SAME_UNDERLYING) -> pd.DataFrame:
    """Keep only the best finite score of each same-underlying group per row (ties -> group order)."""
    out = scores.copy()
    for members in groups.values():
        m = [s for s in members if s in scores.columns]
        if len(m) < 2:
            continue
        a = scores[m].to_numpy(float)
        fin = np.isfinite(a)
        best = np.argmax(np.where(fin, a, -np.inf), axis=1)
        keep = np.zeros_like(fin)
        keep[np.arange(len(a)), best] = True
        out[m] = np.where(keep & fin, a, np.nan)
    return out


def market_risk_on(data: ResearchData, index: pd.DatetimeIndex) -> pd.Series:
    """SPY close > SMA200 on SPY's own sessions, carried onto ``index`` (short holes only)."""
    spy = data.daily[MARKET]["close"].sort_index()
    sma = spy.rolling(SMA_DAYS, min_periods=SMA_DAYS).mean()
    on = pd.Series(np.where(sma.notna(), (spy > sma).astype(float), np.nan), index=spy.index)
    on = on.reindex(on.index.union(index)).ffill(limit=FFILL_LIMIT).reindex(index)
    return on.fillna(0.0).astype(bool)


# --------------------------------------------------------------------------- #
# Holding the book: drift, maintenance calls, margin cap
# --------------------------------------------------------------------------- #


def _requirement(leverage: float, floor: float) -> float:
    return min(1.0, max(floor, LETF_MAINT_PER_X * leverage))


def maintenance_requirement(symbol: str) -> float:
    """Today's maintenance margin of a long position: 25% x leverage for leveraged ETFs (FINRA 4210), >= MAINT_LONG."""
    inst = INSTRUMENTS.get(symbol)
    return _requirement(inst.leverage_factor if inst else 1.0, MAINT_LONG)


def requirements(index: pd.DatetimeIndex, cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(initial, maintenance) margin requirement per (session, symbol). Equal to common.margin_requirement /
    maintenance_requirement except for LEVERAGE_CUTS funds, which carry their old (3x) requirement before the cut."""
    n = len(index)
    init = np.tile(np.array([margin_requirement(s) for s in cols], float), (n, 1))
    maint = np.tile(np.array([maintenance_requirement(s) for s in cols], float), (n, 1))
    for j, s in enumerate(cols):
        if s in LEVERAGE_CUTS:
            first_new, old_leverage = LEVERAGE_CUTS[s]
            before = np.asarray(index < pd.Timestamp(first_new))
            init[before, j] = _requirement(old_leverage, REG_T_INITIAL)
            maint[before, j] = _requirement(old_leverage, MAINT_LONG)
    return init, maint


def cap_rows(w: pd.DataFrame, init_req: np.ndarray) -> pd.DataFrame:
    """``common.cap_to_margin`` with a per-session requirement: scale each row so sum |w_i| x req_i <= 1 - buffer.
    All-NaN rows (= hold) stay all-NaN."""
    a = w.to_numpy(float)
    used = np.nansum(np.abs(a) * init_req, axis=1)
    scale = np.ones(len(a))
    over = used > 1.0 - MARGIN_BUFFER
    scale[over] = (1.0 - MARGIN_BUFFER) / used[over]
    return pd.DataFrame(a * scale[:, None], index=w.index, columns=w.columns)


def hold_with_margin_calls(target: pd.DataFrame, mask: np.ndarray, open_raw: pd.DataFrame, close_raw: pd.DataFrame,
                           init_req: np.ndarray, maint_req: np.ndarray,
                           band: float) -> tuple[pd.DataFrame, pd.DataFrame, list[int]]:
    """Decision frame for the engine plus the held book, with maintenance calls.

    ``target`` rows on ``mask`` sessions are new (already margin-capped) targets; every other row holds.
    The held book replays engine.run_weights' accounting without costs, on the same raw bars: at the open
    of session i it drifts by the overnight gap (from the last known close), trades to the decision of row
    i-1 for tradable funds unless the change is smaller than ``band`` (the engine's no-trade band), then
    drifts to the close of i. So it is exactly what the engine holds after the close of i, and it uses only
    bars through that close (causal). If its maintenance requirement exceeds equity at the close of a
    non-rebalance row i, row i becomes a de-lever decision: the margin cap of the held book, selling at
    least CALL_MIN_SELL_BANDS x band of every held fund (all of a smaller one) so the band cannot suppress
    the forced sale.

    Returns (decisions: all-NaN rows = hold, book: the decision on decision rows and the held weights on
    every other row, indices of the maintenance-call rows).
    """
    tgt = target.to_numpy(float)
    n, k = tgt.shape
    o = open_raw.to_numpy(float)
    c = close_raw.to_numpy(float)
    c_last = close_raw.ffill().to_numpy(float)  # the engine books a gap across a missing bar from the last close
    m = np.asarray(mask, dtype=bool)
    decisions = np.full((n, k), np.nan)
    book = np.zeros((n, k))
    calls: list[int] = []
    held = np.zeros(k)
    pending = None  # decision of row i-1, executed at the open of row i
    min_sell = CALL_MIN_SELL_BANDS * band
    for i in range(n):
        if i > 0:
            tradable = np.isfinite(o[i]) & np.isfinite(c[i]) & np.isfinite(c_last[i - 1])
            r_on = np.where(tradable, o[i] / np.where(tradable, c_last[i - 1], 1.0) - 1.0, 0.0)
            denom = 1.0 + float(held @ r_on)
            held = held * (1.0 + r_on) / denom if denom > 0 else held * 0.0
            if pending is not None:
                new = np.where(tradable, pending, held)
                if band > 0:
                    new = np.where(np.abs(new - held) < band, held, new)
                held = new
            r_id = np.where(tradable, c[i] / np.where(tradable, o[i], 1.0) - 1.0, 0.0)
            d2 = 1.0 + float(held @ r_id)
            held = held * (1.0 + r_id) / d2 if d2 > 0 else held * 0.0
        pending = None
        if m[i]:
            pending = tgt[i].copy()
        elif float(np.abs(held) @ maint_req[i]) > 1.0 + 1e-12:
            cut = held * min(1.0, (1.0 - MARGIN_BUFFER) / float(np.abs(held) @ init_req[i]))
            if min_sell > 0:
                cut = np.where(held > 0, np.minimum(cut, np.maximum(held - min_sell, 0.0)), cut)
            pending = cut
            calls.append(i)
        if pending is None:
            book[i] = held
        else:
            decisions[i] = book[i] = pending
    idx, cols = target.index, target.columns
    return pd.DataFrame(decisions, index=idx, columns=cols), pd.DataFrame(book, index=idx, columns=cols), calls


def _execute(data: ResearchData, requested: pd.DataFrame, warmup: int, freq: str, band: float,
             costs) -> tuple[StrategyResult, pd.DataFrame, np.ndarray, list[int]]:
    """Margin-cap the requested targets, trade them only on rebalance sessions after the warm-up, hold otherwise."""
    n = len(requested)
    pos = np.arange(n)
    mask = (rebalance_mask(requested.index, freq).to_numpy(bool) | (pos == warmup)) & (pos >= warmup)
    cols = list(requested.columns)
    init_req, maint_req = requirements(requested.index, cols)
    capped = cap_rows(requested, init_req)
    open_raw = data.panel("open", cols).reindex(requested.index)  # the engine's own (un-filled) bars
    close_raw = data.panel("close", cols).reindex(requested.index)
    decisions, book, calls = hold_with_margin_calls(capped, mask, open_raw, close_raw, init_req, maint_req, band)
    decisions = cap_rows(decisions, init_req)  # the frame the engine sees is ALWAYS broker-feasible
    res = run_weights(data, decisions, costs, band=band)
    res.weights = book.reindex(res.returns.index)
    return res, capped, mask, calls


def _gross_notes(requested: pd.DataFrame, capped: pd.DataFrame, mask: np.ndarray, risky: list[str], margin: float,
                 band: float, calls: list[int], res: StrategyResult, warmup: int) -> dict:
    req_g = requested[mask].abs().sum(axis=1)
    eff_g = capped[mask].abs().sum(axis=1)
    eff_risky = capped.loc[mask, risky].abs().sum(axis=1)
    invested = eff_risky[eff_risky > 1e-9]
    live_expo = res.exposure.iloc[warmup + 1:]
    any_reb = bool(mask.any())
    idx = capped.index
    return {
        "universe": list(risky), "rebalances": int(mask.sum()), "band": band,
        "requested_gross": margin,
        "effective_gross_mean": float(eff_g.mean()) if any_reb else None,
        "effective_gross_max": float(eff_g.max()) if any_reb else None,
        "effective_risky_gross_mean": float(eff_risky.mean()) if any_reb else None,
        "effective_risky_gross_when_invested_mean": float(invested.mean()) if len(invested) else None,
        "cap_binding_share": float((eff_g < req_g - 1e-9).mean()) if any_reb else None,
        "held_gross_mean": float(live_expo.mean()) if len(live_expo) else None,
        "held_gross_max": float(live_expo.max()) if len(live_expo) else None,
        "margin_calls": len(calls), "margin_call_dates": [str(idx[i].date()) for i in calls[:20]],
        "survivorship_caveat": SURVIVORSHIP,
    }


def _flat(data: ResearchData, reason: str) -> StrategyResult:
    idx = data.dates()
    z = pd.Series(0.0, idx)
    return StrategyResult(z, z.copy(), z.copy(), z.copy(), z.copy(), 0, weights=pd.DataFrame(index=idx),
                          notes={"flat_reason": reason, "survivorship_caveat": SURVIVORSHIP})


def _scoring_close(data: ResearchData, cols: list[str]) -> pd.DataFrame:
    """Closes for SCORING only (short holes bridged, never stale for long); holding/execution use raw bars."""
    return data.panel("close", cols).ffill(limit=FFILL_LIMIT)


# --------------------------------------------------------------------------- #
# (a) leveraged ETF rotation
# --------------------------------------------------------------------------- #


def run_letf(data: ResearchData, p: dict, costs) -> StrategyResult:
    risky = available(data, LETF_UNIVERSE)
    if not risky:
        return _flat(data, "no leveraged ETF in data")
    regime = p["regime"]
    if regime not in ("off", "cash") + LETF_DEFENSIVE:
        raise ValueError(f"unknown regime option {regime}")
    use_filter = regime != "off" and MARKET in data.daily
    defensive = regime if use_filter and regime in LETF_DEFENSIVE and regime in data.daily else None
    cols = risky + ([defensive] if defensive and defensive not in risky else [])
    close = _scoring_close(data, cols)
    margin = min(float(p["margin"]), MAX_MARGIN)

    scores = one_per_underlying(momentum_score(close[risky], p["score"]))
    risk_off = ~market_risk_on(data, close.index) if use_filter else None
    slots = rotation_weights(scores, int(p["top_n"]), None, None, risk_off)  # 1/top_n per selected fund
    requested = (slots * margin).reindex(columns=cols, fill_value=0.0)
    if defensive is not None:
        off = risk_off.to_numpy(bool)
        requested.loc[off, :] = 0.0
        requested.loc[off, defensive] = 1.0  # risk-off book = the defensive fund, unmargined
    band = float(p["band"])
    res, capped, mask, calls = _execute(data, requested, LETF_WARMUP, p["rebalance"], band, costs)
    res.notes.update(_gross_notes(requested, capped, mask, risky, margin, band, calls, res, LETF_WARMUP))
    res.notes.update({
        "market_filter": bool(use_filter), "market_filter_requested": regime != "off",
        "risk_off_target": defensive or ("cash" if use_filter else None),
        "risk_off_share_of_rebalances": float(risk_off.to_numpy(bool)[mask].mean()) if use_filter and mask.any() else 0.0,
    })
    return res


# --------------------------------------------------------------------------- #
# (b) broad unlevered ETF dual momentum
# --------------------------------------------------------------------------- #


def run_broad(data: ResearchData, p: dict, costs) -> StrategyResult:
    risky = [s for s in available(data, BROAD_UNIVERSE) if s != HURDLE]
    if not risky:
        return _flat(data, "no broad-universe ETF in data")
    park = HURDLE if HURDLE in data.daily else None
    cols = risky + ([park] if park else [])
    close = _scoring_close(data, cols)
    margin = min(float(p["margin"]), MAX_MARGIN)
    if p["score"] not in ("blend_1_3_6", "blend_1_3_6_12"):
        raise ValueError(f"unknown score {p['score']}")
    legs = LEGS[p["score"]]

    scores = blended_return(close[risky], legs)
    hurdle = blended_return(close[[park]], legs)[park] if park else pd.Series(0.0, index=close.index)
    slots = rotation_weights(scores, int(p["top_n"]), hurdle, None, None)
    requested = (slots * margin).reindex(columns=cols, fill_value=0.0)
    slot_share = slots.sum(axis=1)
    if park:
        # failed / unfilled slots go to SHY only out of UNBORROWED equity (never pay margin interest to hold T-bills)
        requested[park] = np.minimum(1.0 - slot_share, 1.0 - slot_share * margin).clip(lower=0.0)
    band = float(p["band"])
    res, capped, mask, calls = _execute(data, requested, BROAD_WARMUP, p["rebalance"], band, costs)
    res.notes.update(_gross_notes(requested, capped, mask, risky, margin, band, calls, res, BROAD_WARMUP))
    res.notes.update({"park": park or "cash",
                      "share_slots_failed": float(1.0 - slot_share[mask].mean()) if mask.any() else None,
                      "park_weight_mean": float(requested.loc[mask, park].mean()) if park and mask.any() else 0.0})
    return res


LETF_SPEC = register(StrategySpec(
    name="letf_momentum_rotation",
    family="leveraged_momentum",
    hypothesis=("Holding the top-N (1-3) of 20 daily-reset 2x/3x leveraged ETFs by trailing 1/3/6-month (optionally "
                "last-week-skipped or volatility-adjusted) momentum, at most one fund per underlying index, equal weight "
                "with requested gross = margin capped to the FINRA leveraged-ETF maintenance limit (3x book <= ~1.29x), "
                "rebalanced on the first session of each week and moved to cash/IEF/TMF when SPY is below its 200-day "
                "SMA, earns a positive after-cost Sharpe that a random re-timing of the same holdings does not. "
                "SURVIVORSHIP CAVEAT: only leveraged ETFs that still exist today are in the universe (many closed after "
                "crashes; NUGT/ERX cut leverage in 2020), so the backtest is biased UPWARD."),
    # 3 x 3 x 4 x 3 = 108 trials. regime ordered by risk taken while SPY < SMA200 (off > TMF > IEF > cash).
    param_grid={"score": ["blend", "blend_skip1w", "riskadj"], "top_n": [1, 2, 3], "regime": ["off", "TMF", "IEF", "cash"],
                "margin": [1.0, 1.5, 1.95], "rebalance": ["W"], "band": [0.02]},
    default_params={"score": "riskadj", "top_n": 2, "regime": "cash", "margin": 1.0, "rebalance": "W", "band": 0.02},
    run_fn=run_letf,
    symbols=tuple(LETF_UNIVERSE + ["IEF", MARKET]),
))

BROAD_SPEC = register(StrategySpec(
    name="broad_etf_momentum",
    family="cross_sectional_momentum",
    hypothesis=("Holding the top-N (3/5) of 39 unlevered ETFs (core asset classes, SPDR sectors and the extended "
                "thematic/country list) by blended 1/3/6(/12)-month return, each slot kept only if it beats SHY's "
                "return over the same window (else parked in SHY out of unborrowed equity only), with requested "
                "risky gross = margin capped to Reg-T buying power (<= ~1.94x), rebalanced on the first session of "
                "each week or month, earns a positive after-cost Sharpe that a random re-timing does not. "
                "SURVIVORSHIP CAVEAT: the extended list "
                "was picked with hindsight of which ETFs are popular and still trade today, so the backtest is biased "
                "UPWARD."),
    # 2 x 2 x 3 x 2 = 24 trials.
    param_grid={"score": ["blend_1_3_6", "blend_1_3_6_12"], "top_n": [3, 5], "margin": [1.0, 1.5, 1.95],
                "rebalance": ["W", "M"], "band": [0.01]},
    default_params={"score": "blend_1_3_6_12", "top_n": 5, "margin": 1.5, "rebalance": "M", "band": 0.01},
    run_fn=run_broad,
    symbols=tuple(BROAD_UNIVERSE),
))
