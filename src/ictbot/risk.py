"""Hard-coded risk engine.

* Config values are clamped by HARD ceilings below; a config above a ceiling
  refuses to start.
* The ONLY way to obtain an :class:`ApprovedOrder` - the only object the
  execution layer will submit - is :meth:`RiskEngine.approve`. Strategy code
  cannot construct one (guarded by a private issuance token).
* Every approved order carries a stop on the correct side of the entry.
* No averaging down / pyramiding: one position or working entry per symbol.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from .config import BotConfig, RiskConfig
from .data import Quote
from .models import Direction, Setup

# Absolute ceilings - deliberately NOT configurable.
HARD_MAX_RISK_PER_TRADE_PCT = 2.0
HARD_MAX_POSITION_NOTIONAL_PCT = 50.0
HARD_MAX_TOTAL_NOTIONAL_PCT = 100.0
HARD_MAX_DAILY_LOSS_PCT = 5.0
HARD_MAX_WEEKLY_LOSS_PCT = 10.0
HARD_MAX_DRAWDOWN_PCT = 20.0
HARD_MAX_TRADES_PER_DAY = 10
HARD_MAX_CONSECUTIVE_LOSSES = 10
HARD_MAX_BUCKET_RISK_MULTIPLE = 3.0
PDT_EQUITY_THRESHOLD = 25_000.0

_ISSUE_TOKEN = object()


class RiskConfigError(ValueError):
    pass


def validate_risk_config(cfg: BotConfig) -> None:
    r = cfg.risk
    checks = [
        (0 < r.risk_per_trade_pct <= HARD_MAX_RISK_PER_TRADE_PCT, "risk_per_trade_pct", HARD_MAX_RISK_PER_TRADE_PCT),
        (0 < r.max_position_notional_pct <= HARD_MAX_POSITION_NOTIONAL_PCT, "max_position_notional_pct", HARD_MAX_POSITION_NOTIONAL_PCT),
        (0 < r.max_total_notional_pct <= HARD_MAX_TOTAL_NOTIONAL_PCT, "max_total_notional_pct", HARD_MAX_TOTAL_NOTIONAL_PCT),
        (0 < r.daily_loss_limit_pct <= HARD_MAX_DAILY_LOSS_PCT, "daily_loss_limit_pct", HARD_MAX_DAILY_LOSS_PCT),
        (0 < r.weekly_loss_limit_pct <= HARD_MAX_WEEKLY_LOSS_PCT, "weekly_loss_limit_pct", HARD_MAX_WEEKLY_LOSS_PCT),
        (0 < r.max_drawdown_pct <= HARD_MAX_DRAWDOWN_PCT, "max_drawdown_pct", HARD_MAX_DRAWDOWN_PCT),
        (0 < r.max_trades_per_day <= HARD_MAX_TRADES_PER_DAY, "max_trades_per_day", HARD_MAX_TRADES_PER_DAY),
        (0 < r.max_consecutive_losses <= HARD_MAX_CONSECUTIVE_LOSSES, "max_consecutive_losses", HARD_MAX_CONSECUTIVE_LOSSES),
        (r.vol_scaling.max_scale <= 1.0, "vol_scaling.max_scale", 1.0),
    ]
    for ok, name, ceiling in checks:
        if not ok:
            raise RiskConfigError(f"risk.{name} must be in (0, {ceiling}] - hard ceiling in risk.py")
    for b in cfg.portfolio.buckets:
        if not 0 < b.max_open_risk_multiple <= HARD_MAX_BUCKET_RISK_MULTIPLE:
            raise RiskConfigError(f"bucket {b.name}: max_open_risk_multiple must be in (0, {HARD_MAX_BUCKET_RISK_MULTIPLE}]")
    if r.max_position_notional_pct > r.max_total_notional_pct:
        raise RiskConfigError("max_position_notional_pct cannot exceed max_total_notional_pct")


# --------------------------------------------------------------------------- #
# Inputs (all derived from the BROKER each cycle, never from local memory)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    last_equity: float
    buying_power: float
    shorting_enabled: bool = True
    trading_blocked: bool = False
    account_blocked: bool = False
    pattern_day_trader: bool = False


@dataclass(frozen=True)
class RiskState:
    now: dt.datetime
    day_pnl_pct: float
    week_pnl_pct: float
    drawdown_pct: float
    trades_today: int  # filled entries + working entry orders today
    consecutive_losses: int  # today, most recent first
    last_loss_exit: dt.datetime | None = None
    manual_disable: bool = False


@dataclass(frozen=True)
class Exposure:
    symbol: str
    direction: Direction
    qty: float
    entry: float
    stop: float | None  # None = UNPROTECTED (should never happen)
    pending: bool  # working entry order, not yet filled

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.entry

    @property
    def risk_dollars(self) -> float:
        if self.stop is None:
            return math.inf
        return abs(self.entry - self.stop) * abs(self.qty)


@dataclass(frozen=True)
class MarketCheck:
    now: dt.datetime
    session_close: dt.datetime
    quote: Quote | None
    bar_volume: float
    rvol: float | None
    newest_bar_age_s: float | None
    tradable: bool = True
    shortable: bool = True
    easy_to_borrow: bool = True


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HaltStatus:
    can_open: bool
    reasons: tuple[str, ...]
    flatten: bool = False
    kill_switch: bool = False


@dataclass(frozen=True)
class Rejection:
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ApprovedOrder:
    symbol: str
    direction: Direction
    qty: int
    entry: float
    stop: float
    target: float
    risk_dollars: float
    setup_id: str
    setup_tag: str
    score: float
    notes: tuple[str, ...] = ()
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _ISSUE_TOKEN:
            raise PermissionError("ApprovedOrder can only be issued by RiskEngine.approve()")
        assert_order_invariants(self.direction, self.qty, self.entry, self.stop, self.target)


def assert_order_invariants(direction: Direction, qty: float, entry: float, stop: float | None, target: float) -> None:
    if stop is None or not math.isfinite(stop) or stop <= 0:
        raise ValueError("every order must carry a stop")
    if not float(qty).is_integer() or qty < 1:
        raise ValueError("quantity must be a positive whole number of shares")
    if direction is Direction.LONG and not (stop < entry < target):
        raise ValueError(f"long requires stop < entry < target, got {stop} / {entry} / {target}")
    if direction is Direction.SHORT and not (target < entry < stop):
        raise ValueError(f"short requires target < entry < stop, got {target} / {entry} / {stop}")


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class RiskEngine:
    def __init__(self, cfg: BotConfig) -> None:
        validate_risk_config(cfg)
        self._cfg = cfg
        self._r: RiskConfig = cfg.risk

    # -- account-level halts -------------------------------------------------

    def status(self, account: AccountSnapshot, state: RiskState) -> HaltStatus:
        r = self._r
        reasons: list[str] = []
        flatten = kill = False
        if account.account_blocked or account.trading_blocked:
            reasons.append("account_blocked")
        if state.manual_disable:
            reasons.append("manually_disabled")
        if account.equity < r.min_equity:
            reasons.append("equity_below_minimum")
        if account.pattern_day_trader and account.equity < PDT_EQUITY_THRESHOLD:
            reasons.append("pdt_flagged_under_25k")
        if state.drawdown_pct >= r.max_drawdown_pct:
            reasons.append("max_drawdown_kill_switch")
            flatten = kill = True
        if state.week_pnl_pct <= -r.weekly_loss_limit_pct:
            reasons.append("weekly_loss_limit")
            flatten = True
        if state.day_pnl_pct <= -r.daily_loss_limit_pct:
            reasons.append("daily_loss_limit")
            flatten = flatten or r.flatten_on_daily_limit
        if state.consecutive_losses >= r.max_consecutive_losses:
            reasons.append("max_consecutive_losses")
        if state.trades_today >= r.max_trades_per_day:
            reasons.append("max_trades_per_day")
        if state.last_loss_exit is not None:
            if state.now - state.last_loss_exit < dt.timedelta(minutes=r.cooldown_minutes_after_loss):
                reasons.append("cooldown_after_loss")
        return HaltStatus(not reasons, tuple(reasons), flatten, kill)

    # -- trade-level ---------------------------------------------------------

    def base_risk_dollars(self, equity: float) -> float:
        return equity * self._r.risk_per_trade_pct / 100.0

    def vol_scale(self, atr_value: float, price: float) -> float:
        vs = self._r.vol_scaling
        if not vs.enabled or atr_value <= 0 or price <= 0:
            return 1.0
        atr_pct = atr_value / price * 100.0
        return float(min(vs.max_scale, max(vs.min_scale, vs.target_atr_pct / atr_pct)))

    def pre_trade_checks(self, setup: Setup, market: MarketCheck) -> Rejection | None:
        r, ex = self._r, self._cfg.execution
        cutoff = market.session_close - dt.timedelta(minutes=self._cfg.session.no_new_entries_minutes_before_close)
        if market.now >= cutoff:
            return Rejection("too_close_to_close")
        if not market.tradable:
            return Rejection("asset_not_tradable")
        if setup.direction is Direction.SHORT:
            if not ex.allow_short:
                return Rejection("shorts_disabled")
            if not (market.shortable and market.easy_to_borrow):
                return Rejection("not_shortable_or_htb")
        if market.newest_bar_age_s is None or market.newest_bar_age_s > self._cfg.data.max_data_staleness_seconds:
            return Rejection("stale_or_missing_bars", f"age={market.newest_bar_age_s}")
        q = market.quote
        if q is None:
            return Rejection("missing_quote")
        age = (market.now - q.timestamp).total_seconds()
        if age > r.max_quote_age_seconds:
            return Rejection("stale_quote", f"age_s={age:.0f}")
        if q.bid <= 0 or q.ask <= 0 or q.ask < q.bid:
            return Rejection("crossed_or_invalid_quote")
        if q.spread_bps > r.max_spread_bps:
            return Rejection("spread_too_wide_bps", f"{q.spread_bps:.2f}bps")
        if q.spread > r.max_spread_atr_fraction * setup.atr:
            return Rejection("spread_too_wide_vs_atr", f"{q.spread:.4f}")
        if market.bar_volume < r.min_bar_volume:
            return Rejection("bar_volume_too_low", f"{market.bar_volume:.0f}")
        if market.rvol is not None and market.rvol < r.min_relative_volume:
            return Rejection("relative_volume_too_low", f"{market.rvol:.2f}")
        return None

    def approve(
        self,
        setup: Setup,
        account: AccountSnapshot,
        state: RiskState,
        exposures: list[Exposure],
        market: MarketCheck,
        bucket_symbols: tuple[str, ...],
        bucket_risk_multiple: float,
        risk_fraction: float = 1.0,
    ) -> ApprovedOrder | Rejection:
        halt = self.status(account, state)
        if not halt.can_open:
            return Rejection("halted", ",".join(halt.reasons))
        if any(e.symbol == setup.symbol for e in exposures):
            return Rejection("position_or_order_exists", "no averaging down / pyramiding")
        if any(e.stop is None for e in exposures):
            return Rejection("unprotected_exposure_present")
        if state.trades_today + 1 > self._r.max_trades_per_day:
            return Rejection("max_trades_per_day")
        bad = self.pre_trade_checks(setup, market)
        if bad is not None:
            return bad
        try:
            assert_order_invariants(setup.direction, 1, setup.entry, setup.stop, setup.target)
        except ValueError as exc:
            return Rejection("invalid_prices", str(exc))

        equity = account.equity
        rps = setup.risk_per_share
        if rps <= 0:
            return Rejection("zero_stop_distance")
        notes: list[str] = []
        scale = self.vol_scale(setup.atr, setup.entry)
        if scale < 1.0:
            notes.append(f"vol_scale={scale:.2f}")
        risk_budget = self.base_risk_dollars(equity) * scale * max(0.0, min(1.0, risk_fraction))
        qty = math.floor(risk_budget / rps)

        # notional caps
        max_pos = equity * self._r.max_position_notional_pct / 100.0
        qty = min(qty, math.floor(max_pos / setup.entry))
        used = sum(e.notional for e in exposures)
        max_total = equity * self._r.max_total_notional_pct / 100.0
        qty = min(qty, math.floor(max(0.0, max_total - used) / setup.entry))
        qty = min(qty, math.floor(max(0.0, account.buying_power) / setup.entry))

        # correlated bucket: aggregate open risk cap
        bucket_open = sum(e.risk_dollars for e in exposures if e.symbol in bucket_symbols)
        bucket_cap = self.base_risk_dollars(equity) * bucket_risk_multiple
        if setup.symbol in bucket_symbols:
            room = bucket_cap - bucket_open
            if room <= 0:
                return Rejection("bucket_risk_cap_reached", f"open={bucket_open:.2f} cap={bucket_cap:.2f}")
            qty_bucket = math.floor(room / rps)
            if qty_bucket < qty:
                notes.append("reduced_by_bucket_cap")
                qty = qty_bucket
        if qty < 1:
            return Rejection("size_below_one_share", f"budget={risk_budget:.2f} rps={rps:.2f}")
        return ApprovedOrder(
            symbol=setup.symbol,
            direction=setup.direction,
            qty=int(qty),
            entry=setup.entry,
            stop=setup.stop,
            target=setup.target,
            risk_dollars=round(qty * rps, 2),
            setup_id=setup.setup_id,
            setup_tag=setup.setup_tag,
            score=setup.score,
            notes=tuple(notes),
            _token=_ISSUE_TOKEN,
        )
