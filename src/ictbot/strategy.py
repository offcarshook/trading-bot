"""ICT setup finder - the SINGLE source of truth for signal logic.

Live trading and the backtest both call :func:`build_frames` +
:func:`find_setups` + :func:`pending_entry_action` + :func:`entry_window_open`.
Nothing here performs I/O or reads the clock; the caller passes ``asof``.

Pipeline at each completed 5-minute bar ``t``:
  liquidity pools -> sweeps (today) -> MSS with displacement -> FVG in the
  displacement leg -> entry/stop/target -> filters (HTF bias, premium/discount,
  reward:risk) -> confluence score.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import ict_detectors as det
from .config import BotConfig, parse_hhmm
from .data import _between, aggregate_sessions, completed_only, daily_from_minutes, window_high_low
from .indicators import atr as atr_fn
from .indicators import ema as ema_fn
from .indicators import relative_volume
from .models import (
    Bias,
    Direction,
    LiquidityPool,
    PoolSide,
    Setup,
    SignalRecord,
)
from .timeutils import TradingSession, in_window, week_start


# --------------------------------------------------------------------------- #
# Frames
# --------------------------------------------------------------------------- #


@dataclass
class SymbolFrames:
    """All completed bars for one symbol as of ``asof`` (no look-ahead)."""

    symbol: str
    session: TradingSession  # today's session
    bars5: pd.DataFrame  # multi-session RTH 5m bars, completed only
    bars1h: pd.DataFrame  # multi-session RTH 1h bars, completed only
    daily: pd.DataFrame  # completed PRIOR sessions only (today excluded)
    premarket: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    today_start: int = 0  # index of today's first 5m bar in bars5 (len(bars5) if none yet)


@dataclass(frozen=True)
class PriorFrames:
    """Bars of the sessions BEFORE today. Immutable during the day, so live
    trading and the backtest compute this once per day and reuse it."""

    bars5: pd.DataFrame
    bars1h: pd.DataFrame
    daily: pd.DataFrame


def build_prior(bars_1m: pd.DataFrame, prior_sessions: list[TradingSession], cfg: BotConfig) -> PriorFrames:
    intraday = prior_sessions[-cfg.data.intraday_lookback_sessions :] if cfg.data.intraday_lookback_sessions else []
    return PriorFrames(
        aggregate_sessions(bars_1m, intraday, 5),
        aggregate_sessions(bars_1m, intraday, 60),
        daily_from_minutes(bars_1m, prior_sessions),
    )


def build_frames(
    symbol: str,
    bars_1m: pd.DataFrame,
    sessions: list[TradingSession],
    asof: dt.datetime,
    cfg: BotConfig,
    delay_s: int | None = None,
    prior: PriorFrames | None = None,
    today_full: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> SymbolFrames:
    """``sessions`` must be sorted and end with today's session. Only 1m bars
    that START before ``asof`` are visible and only completed buckets are kept.

    ``today_full`` (backtest only) = today's 5m / 1h bars aggregated over the
    whole session; they are cut to the buckets completed at ``asof``, which is
    identical to aggregating only the 1m bars known at ``asof`` (a completed
    bucket never contains a minute at or after ``asof``)."""
    delay = cfg.data.bar_completion_delay_seconds if delay_s is None else delay_s
    today = sessions[-1]
    if prior is None:
        prior = build_prior(bars_1m, sessions[:-1], cfg)
    day_lo = dt.datetime.combine(today.day, dt.time(0), tzinfo=today.open.tzinfo)
    known = _between(bars_1m, day_lo, asof)
    if today_full is not None:
        today5 = completed_only(today_full[0], 5, today, asof, delay)
        today1h = completed_only(today_full[1], 60, today, asof, delay)
    else:
        today5 = aggregate_sessions(known, [today], 5, asof, delay)
        today1h = aggregate_sessions(known, [today], 60, asof, delay)
    bars5 = _stack(prior.bars5, today5)
    bars1h = _stack(prior.bars1h, today1h)
    premarket: dict[str, tuple[float | None, float | None]] = {}
    if cfg.data.include_premarket_for_levels:
        for win in cfg.session.level_sessions:
            if win.enabled and win.end_time() <= today.open.timetz().replace(tzinfo=None):
                premarket[win.name] = window_high_low(known, today.day, win.start_time(), win.end_time())
    return SymbolFrames(symbol, today, bars5, bars1h, prior.daily, premarket, len(prior.bars5))


def _stack(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    if b.empty:
        return a
    if a.empty:
        return b
    return pd.concat([a, b])


# --------------------------------------------------------------------------- #
# Time filters
# --------------------------------------------------------------------------- #


def entry_window_open(ts: dt.datetime, session: TradingSession, cfg: BotConfig) -> tuple[bool, str]:
    """May a NEW entry order be placed at ``ts``?"""
    if not session.contains(ts):
        return False, "outside_regular_session"
    if session.is_early_close and cfg.session.skip_early_close_days:
        return False, "early_close_day"
    cutoff = session.close - dt.timedelta(minutes=cfg.session.no_new_entries_minutes_before_close)
    flatten = dt.datetime.combine(session.day, parse_hhmm(cfg.session.flatten_time), tzinfo=session.open.tzinfo)
    if ts >= min(cutoff, flatten):
        return False, "too_close_to_close"
    zones = [z for z in cfg.session.kill_zones if z.enabled]
    if not any(in_window(ts, z.start_time(), z.end_time()) for z in zones):
        return False, "outside_kill_zones"
    return True, "ok"


def last_window_end(session: TradingSession, cfg: BotConfig) -> dt.datetime:
    ends = [z.end_time() for z in cfg.session.kill_zones if z.enabled]
    latest = max(ends) if ends else session.open.time()
    return dt.datetime.combine(session.day, latest, tzinfo=session.open.tzinfo)


# --------------------------------------------------------------------------- #
# Pools and bias
# --------------------------------------------------------------------------- #


def liquidity_pools(frames: SymbolFrames, bars: det.Bars, atr: np.ndarray, swings: list, t: int, cfg: BotConfig) -> list[LiquidityPool]:
    lq = cfg.ict.liquidity
    pools: list[LiquidityPool] = []
    ts = frames.today_start
    daily = frames.daily
    if lq.use_prev_day and not daily.empty:
        prev = daily.iloc[-1]
        pools += det.level_pair_pools("PD", "prev_day", prev["high"], prev["low"], ts)
    if lq.use_prev_week and not daily.empty:
        this_week = week_start(frames.session.day)
        prev_week = daily[[week_start(d) == this_week - dt.timedelta(days=7) for d in daily.index]]
        if not prev_week.empty:
            pools += det.level_pair_pools("PW", "prev_week", prev_week["high"].max(), prev_week["low"].min(), ts)
    if lq.use_level_sessions:
        for name, (hi, lo) in frames.premarket.items():
            pools += det.level_pair_pools(name, "level_session", hi, lo, ts)
    if lq.use_opening_range and cfg.session.opening_range_minutes > 0:
        n_or = max(1, cfg.session.opening_range_minutes // 5)
        or_end = ts + n_or  # first bar AFTER the opening range completes
        if or_end - 1 <= t:
            pools += det.level_pair_pools(
                "OR", "opening_range", float(bars.high[ts:or_end].max()), float(bars.low[ts:or_end].min()), or_end
            )
    a = atr[t]
    if lq.use_swings:
        pools += det.swing_pools(swings, t, lq.swing_pool_lookback_bars)
    if lq.use_equal_levels and np.isfinite(a):
        pools += det.equal_level_pools(
            swings, t, lq.swing_pool_lookback_bars, lq.equal_level_atr_tolerance * a, lq.equal_level_min_touches
        )
    return pools


def htf_bias(frames: SymbolFrames, cfg: BotConfig) -> tuple[Bias, Bias, Bias]:
    hb = cfg.ict.htf_bias
    if not hb.enabled:
        return Bias.NEUTRAL, Bias.NEUTRAL, Bias.NEUTRAL
    d, h = frames.daily, frames.bars1h
    if hb.method == "ema":
        daily = det.ema_bias(d["close"].to_numpy(float), ema_fn(d["close"].to_numpy(float), hb.ema_period)) if len(d) else Bias.NEUTRAL
        hourly = det.ema_bias(h["close"].to_numpy(float), ema_fn(h["close"].to_numpy(float), hb.ema_period)) if len(h) else Bias.NEUTRAL
    else:
        daily = det.structure_bias(d["high"].to_numpy(float), d["low"].to_numpy(float), hb.daily_swing_lookback) if len(d) else Bias.NEUTRAL
        hourly = det.structure_bias(h["high"].to_numpy(float), h["low"].to_numpy(float), hb.hourly_swing_lookback) if len(h) else Bias.NEUTRAL
    return daily, hourly, det.combine_bias(daily, hourly, hb.combine)


def pool_intact(bars: det.Bars, pool: LiquidityPool, end: int) -> bool:
    """True if price has not traded through ``pool`` between its availability and ``end``."""
    lo = pool.available_from
    if lo > end:
        return False
    if pool.side is PoolSide.BUY_SIDE:
        return bool(bars.high[lo : end + 1].max() < pool.price)
    return bool(bars.low[lo : end + 1].min() > pool.price)


def choose_target(direction: Direction, entry: float, pools: list[LiquidityPool], bars: det.Bars, t: int) -> LiquidityPool | None:
    """Nearest intact OPPOSING pool beyond the entry."""
    if direction is Direction.LONG:
        cands = [p for p in pools if p.side is PoolSide.BUY_SIDE and p.price > entry and p.available_from <= t]
        cands = [p for p in cands if pool_intact(bars, p, t)]
        return min(cands, key=lambda p: p.price) if cands else None
    cands = [p for p in pools if p.side is PoolSide.SELL_SIDE and p.price < entry and p.available_from <= t]
    cands = [p for p in cands if pool_intact(bars, p, t)]
    return max(cands, key=lambda p: p.price) if cands else None


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #


def round_to_tick(price: float, tick: float, mode: str) -> float:
    steps = price / tick
    if mode == "down":
        steps = np.floor(steps + 1e-9)
    elif mode == "up":
        steps = np.ceil(steps - 1e-9)
    else:
        steps = np.round(steps)
    return round(float(steps * tick), 6)


def make_setup_id(symbol: str, direction: Direction, *times: pd.Timestamp) -> str:
    raw = "|".join([symbol, direction.value, *(t.isoformat() for t in times)])
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


# --------------------------------------------------------------------------- #
# Setup search
# --------------------------------------------------------------------------- #


@dataclass
class EvaluationResult:
    setups: list[Setup]
    records: list[SignalRecord]
    bias: dict[str, str]


def find_setups(frames: SymbolFrames, cfg: BotConfig, data_sparse: bool = False) -> EvaluationResult:
    """Evaluate the latest completed 5m bar of ``frames``. Returns fresh,
    fully specified setups (sorted best first) plus a record for every
    candidate that was filtered out and why."""
    b5 = frames.bars5
    records: list[SignalRecord] = []
    if b5.empty or frames.today_start >= len(b5):
        return EvaluationResult([], records, {})
    t = len(b5) - 1
    bar_time = b5.index[t]
    bars = det.Bars.from_df(b5)
    atr = atr_fn(bars.high, bars.low, bars.close, cfg.indicators.atr_period)
    if not np.isfinite(atr[t]):
        records.append(SignalRecord(bar_time, frames.symbol, "warmup", "skipped", "atr_not_ready"))
        return EvaluationResult([], records, {})

    swings = det.find_swings(bars.high, bars.low, cfg.indicators.swing_lookback, end=t)
    pools = liquidity_pools(frames, bars, atr, swings, t, cfg)
    daily_b, hourly_b, bias = htf_bias(frames, cfg)
    bias_info = {"daily": daily_b.value, "hourly": hourly_b.value, "combined": bias.value}
    fvgs = det.find_fvgs(bars, atr, cfg.ict.fvg.min_size_atr, frames.today_start, t)
    rvol = relative_volume(bars.volume)

    ic, ex, sc = cfg.ict, cfg.execution, cfg.ict.scoring
    setups: list[Setup] = []
    seen: set[str] = set()
    for pool in pools:
        sweep = det.detect_sweep(
            bars, pool, atr,
            min_buffer_atr=ic.sweep.min_buffer_atr, min_buffer_abs=ic.sweep.min_buffer_abs,
            reclaim_within=ic.sweep.reclaim_within_bars, start=pool.available_from, end=t,
        )
        if sweep is None or sweep.sweep_index < frames.today_start:
            continue
        direction = sweep.trade_direction
        mss = det.detect_mss(
            bars, sweep, swings, atr,
            min_body_atr=ic.displacement.min_body_atr, max_wick_fraction=ic.displacement.max_wick_fraction,
            max_bars_after_sweep=ic.mss.max_bars_after_sweep, end=t,
        )
        if mss is None:
            continue
        leg = [g for g in fvgs if g.direction is direction and sweep.sweep_index + 1 <= g.index <= min(mss.index + 1, t)]
        if not leg:
            continue
        fvg = max(leg, key=lambda g: g.index)
        confirm = max(mss.index, fvg.index)
        if t - confirm > ic.fvg.max_setup_age_bars:
            continue
        sid = make_setup_id(frames.symbol, direction, b5.index[sweep.sweep_index], b5.index[mss.index], b5.index[fvg.index])
        if sid in seen:
            continue
        seen.add(sid)
        a = float(atr[confirm])
        rec = dict(time=bar_time, symbol=frames.symbol, setup_id=sid, direction=direction.value)
        details = {"pool": pool.name, "pool_price": pool.price, "sweep_extreme": sweep.extreme, "fvg": [fvg.bottom, fvg.top], "bias": bias_info}

        state = det.fvg_state(bars, fvg, t)
        if state.invalidated:
            records.append(SignalRecord(**rec, stage="fvg", decision="skipped", reason="fvg_invalidated", details=details))
            continue
        raw_entry = fvg.midpoint if ic.fvg.entry_mode == "midpoint" else fvg.entry_edge()
        already = state.reached_midpoint if ic.fvg.entry_mode == "midpoint" else state.touched
        if already:
            records.append(SignalRecord(**rec, stage="fvg", decision="skipped", reason="entry_already_traded", details=details))
            continue

        tick = ex.tick_size
        if direction is Direction.LONG:
            entry = round_to_tick(raw_entry, tick, "down")
            stop = round_to_tick(sweep.extreme - ex.stop_buffer_atr * a, tick, "down")
        else:
            entry = round_to_tick(raw_entry, tick, "up")
            stop = round_to_tick(sweep.extreme + ex.stop_buffer_atr * a, tick, "up")
        risk_ps = abs(entry - stop)
        if risk_ps <= 0 or risk_ps < cfg.risk.min_stop_distance_atr * a:
            records.append(SignalRecord(**rec, stage="stop", decision="skipped", reason="stop_too_tight", entry=entry, stop=stop, details=details))
            continue

        tgt_pool = choose_target(direction, entry, pools, bars, t)
        if tgt_pool is None:
            records.append(SignalRecord(**rec, stage="target", decision="skipped", reason="no_opposing_pool", entry=entry, stop=stop, details=details))
            continue
        offset = ex.target_buffer_atr * a
        if direction is Direction.LONG:
            target = round_to_tick(tgt_pool.price - offset, tick, "down")
        else:
            target = round_to_tick(tgt_pool.price + offset, tick, "up")
        rr = abs(target - entry) / risk_ps
        base = dict(**rec, entry=entry, stop=stop, target=target, reward_risk=round(rr, 3))
        details["target_pool"] = tgt_pool.name
        if rr < ex.min_reward_risk:
            records.append(SignalRecord(**base, stage="target", decision="skipped", reason="reward_risk_below_min", details=details))
            continue

        # ---- filters -------------------------------------------------------
        htf_pool = pool.kind in ic.htf_bias.htf_pool_kinds
        aligned = det.bias_allows(bias, direction, allow_neutral=False)
        if ic.htf_bias.enabled and not det.bias_allows(bias, direction, ic.htf_bias.allow_neutral):
            if not (ic.htf_bias.counter_bias_requires_htf_sweep and htf_pool):
                records.append(SignalRecord(**base, stage="bias", decision="skipped", reason="counter_bias_without_htf_sweep", details=details))
                continue
        if ic.htf_bias.enabled and bias is Bias.NEUTRAL and not ic.htf_bias.allow_neutral and not htf_pool:
            records.append(SignalRecord(**base, stage="bias", decision="skipped", reason="neutral_bias", details=details))
            continue

        pd_ok = True
        if ic.premium_discount.enabled:
            if ic.premium_discount.range_source == "session":
                rng_hi = float(bars.high[frames.today_start : t + 1].max())
                rng_lo = float(bars.low[frames.today_start : t + 1].min())
            else:
                leg_slice = slice(sweep.sweep_index, t + 1)
                rng_hi = sweep.extreme if direction is Direction.SHORT else float(bars.high[leg_slice].max())
                rng_lo = sweep.extreme if direction is Direction.LONG else float(bars.low[leg_slice].min())
            pd_ok = det.in_premium_discount(direction, entry, rng_lo, rng_hi)
            details["dealing_range"] = [rng_lo, rng_hi]
            if ic.premium_discount.required and not pd_ok:
                records.append(SignalRecord(**base, stage="premium_discount", decision="skipped", reason="entry_not_in_premium_discount", details=details))
                continue

        ob = det.find_order_block(bars, mss) if ic.order_block.enabled else None
        ob_conf = ob is not None and det.zones_overlap(ob.low, ob.high, fvg.bottom, fvg.top)
        if ic.order_block.enabled and ic.order_block.required and not ob_conf:
            records.append(SignalRecord(**base, stage="order_block", decision="skipped", reason="no_order_block_confluence", details=details))
            continue

        # ---- score ---------------------------------------------------------
        sb = cfg.session.silver_bullet_window
        comps = {
            "base": sc.base,
            "htf_aligned": sc.htf_aligned if (ic.htf_bias.enabled and aligned) else 0.0,
            "htf_pool_swept": sc.htf_pool_swept if htf_pool else 0.0,
            "equal_levels_swept": sc.equal_levels_swept if pool.kind == "equal_levels" else 0.0,
            "order_block": sc.order_block if ob_conf else 0.0,
            "premium_discount": sc.premium_discount if (ic.premium_discount.enabled and pd_ok) else 0.0,
            "silver_bullet": sc.silver_bullet if (sb.enabled and in_window(bar_time + dt.timedelta(minutes=5), sb.start_time(), sb.end_time())) else 0.0,
            "displacement": min(sc.displacement_cap, sc.displacement_per_atr * mss.displacement.body_atr),
            "reward_risk": min(sc.reward_risk_cap, sc.reward_risk_per_r * (rr - ex.min_reward_risk)),
            "sparse_data": -sc.sparse_data_penalty if data_sparse else 0.0,
        }
        score = round(sum(comps.values()), 4)
        details["components"] = comps
        details["rvol"] = float(rvol[t]) if np.isfinite(rvol[t]) else None
        if score < sc.min_score:
            records.append(SignalRecord(**base, score=score, stage="score", decision="skipped", reason="score_below_min", details=details))
            continue
        tags = tuple(k for k, v in comps.items() if v > 0 and k != "base")
        setup = Setup(
            setup_id=sid, symbol=frames.symbol, direction=direction, signal_time=bar_time, confirm_index=confirm,
            entry=entry, stop=stop, target=target, target_pool=tgt_pool.name, sweep=sweep, mss=mss, fvg=fvg,
            score=score, atr=a, tags=tags, components=comps, order_block=ob,
        )
        setups.append(setup)
        records.append(SignalRecord(**base, score=score, stage="setup", decision="candidate", reason="all_filters_passed", details=details))
    setups.sort(key=lambda s: s.score, reverse=True)
    return EvaluationResult(setups, records, bias_info)


# --------------------------------------------------------------------------- #
# Pending entry management (shared by live + backtest)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntryPlan:
    """Serializable description of a working entry order. Rebuildable after a
    restart from the local setup cache, or (degraded) from the broker order."""

    setup_id: str
    symbol: str
    direction: Direction
    entry: float
    stop: float
    target: float
    placed_at: dt.datetime  # START time of the 5m bar the order was placed after
    fvg_bottom: float | None = None
    fvg_top: float | None = None
    sweep_extreme: float | None = None
    score: float = 0.0
    tag: str = ""

    @classmethod
    def from_setup(cls, s: Setup) -> "EntryPlan":
        return cls(s.setup_id, s.symbol, s.direction, s.entry, s.stop, s.target, s.signal_time,
                   s.fvg.bottom, s.fvg.top, s.sweep.extreme, s.score, s.setup_tag)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["direction"] = self.direction.value
        d["placed_at"] = self.placed_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EntryPlan":
        d = dict(d)
        d["direction"] = Direction(d["direction"])
        d["placed_at"] = dt.datetime.fromisoformat(d["placed_at"])
        return cls(**d)


def pending_entry_action(plan: EntryPlan, bar: pd.Series, bars_since_placement: int, cfg: BotConfig) -> str | None:
    """Evaluate an UNFILLED entry order against a newly completed 5m bar.
    Returns a cancel reason, or None to keep the order working. If the FVG /
    sweep metadata is unknown (restart without cache) the stop price stands in
    for the sweep extreme, which is strictly more permissive -> expiry and the
    server-side bracket still bound the risk."""
    extreme = plan.sweep_extreme if plan.sweep_extreme is not None else plan.stop
    if plan.direction is Direction.LONG:
        if plan.fvg_bottom is not None and bar["close"] < plan.fvg_bottom:
            return "fvg_invalidated"
        if bar["low"] < extreme:
            return "beyond_sweep_extreme"
        if cfg.execution.cancel_if_target_hit_before_fill and bar["high"] >= plan.target:
            return "target_hit_before_fill"
    else:
        if plan.fvg_top is not None and bar["close"] > plan.fvg_top:
            return "fvg_invalidated"
        if bar["high"] > extreme:
            return "beyond_sweep_extreme"
        if cfg.execution.cancel_if_target_hit_before_fill and bar["low"] <= plan.target:
            return "target_hit_before_fill"
    if bars_since_placement >= cfg.ict.fvg.order_expiry_bars:
        return "expired"
    return None
