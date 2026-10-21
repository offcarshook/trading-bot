"""Live PAPER trading loop.

One process per trading day (GitHub Actions job). Sequence:
  1. time / calendar gates (DST-safe, holidays, early closes, event days)
  2. reconcile from the broker (cancel stale orders, flatten overnight / naked positions)
  3. warm up history, then wake shortly after every 5-minute boundary and
     process the newest COMPLETED bar: risk state -> manage working orders ->
     new entries -> logging
  4. flatten at the configured time (default 15:55 ET) or exit early when idle;
     a separate scheduled job also flattens in case this one dies.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from .alerts import Notifier
from .config import BotConfig, parse_hhmm
from .data import DataQuality, Quote, assess_quality
from .execution import AlpacaBroker, BrokerOrder, ExecutionEngine, parse_client_order_id
from .indicators import relative_volume
from .models import Direction, SignalRecord, TradeRecord
from .portfolio import bucket_for, correlation_report, select_setups
from .reporting import Recorder, compute_metrics, mae_mfe, write_journal
from .risk import AccountSnapshot, ApprovedOrder, MarketCheck, Rejection, RiskEngine
from .state import PlanCache, reconstruct_trades, risk_state_from_broker, snapshot
from .strategy import EntryPlan, PriorFrames, SymbolFrames, build_frames, build_prior, entry_window_open, find_setups, last_window_end, pending_entry_action, round_to_tick
from .timeutils import NY, TradingSession, next_bar_boundary, now_ny, ny_dt

log = logging.getLogger(__name__)
MAX_CONSECUTIVE_CYCLE_ERRORS = 5
MANUAL_MAX_WAIT_MINUTES = 30  # manual runs started earlier than this before the open just exit
STATE_DIR = "state"


def load_event_days(path: str | Path) -> dict[dt.date, str]:
    p = Path(path)
    if not p.exists():
        log.warning("event days file missing - no event-day filter", extra={"path": str(p)})
        return {}
    raw = yaml.safe_load(p.read_text()) or {}
    return {dt.date.fromisoformat(str(e["date"])): str(e.get("name", "event")) for e in raw.get("events", [])}


def manual_disable_flag() -> bool:
    """GitHub repo variable ICTBOT_TRADING_ENABLED=false disables new entries."""
    return os.environ.get("ICTBOT_TRADING_ENABLED", "true").strip().lower() in ("0", "false", "no", "off")


@dataclass
class DayContext:
    session: TradingSession
    sessions: list[TradingSession]
    trading_allowed: bool
    skip_reason: str
    events: dict[dt.date, str] = field(default_factory=dict)


class LiveBot:
    def __init__(
        self,
        cfg: BotConfig,
        broker: Any,
        data: Any,
        notifier: Notifier,
        *,
        clock: Callable[[], dt.datetime] = now_ny,
        sleep: Callable[[float], None] = time.sleep,
        state_dir: str = STATE_DIR,
    ) -> None:
        self.cfg = cfg
        self.broker = broker
        self.data = data
        self.notify = notifier
        self.clock = clock
        self.sleep = sleep
        self.risk = RiskEngine(cfg)
        self.exec = ExecutionEngine(broker, cfg, dry_run=cfg.mode.dry_run, sleep=sleep)
        self.state_dir = state_dir
        self.minutes: dict[str, pd.DataFrame] = {}
        self.prior: dict[str, PriorFrames] = {}
        self.assets: dict[str, Any] = {}
        self.halt_alerted: set[str] = set()
        self.kill_switch = False
        self.day_halted = False
        self.dry_placed: set[str] = set()

    # ------------------------------------------------------------------ setup

    def day_context(self, now: dt.datetime) -> DayContext | None:
        today = now.date()
        start = today - dt.timedelta(days=self.cfg.data.history_days)
        sessions = [s for s in self.broker.sessions(start, today) if s.day <= today]
        if not sessions or sessions[-1].day != today:
            return None
        sess = sessions[-1]
        events = load_event_days(self.cfg.session.event_days_file)
        if sess.is_early_close and self.cfg.session.skip_early_close_days:
            return DayContext(sess, sessions, False, "early_close_day", events)
        if self.cfg.session.skip_event_days and today in events:
            return DayContext(sess, sessions, False, f"event_day:{events[today]}", events)
        return DayContext(sess, sessions, True, "", events)

    def start_gate(self, now: dt.datetime) -> tuple[bool, str]:
        """GitHub cron runs at two UTC times to cover EST/EDT; exactly one of
        them lands inside this NY-time window, the other exits immediately."""
        t = now.time()
        if t < parse_hhmm(self.cfg.session.earliest_start):
            return False, f"too_early_ny_{t:%H:%M}"
        if t > parse_hhmm(self.cfg.session.latest_start):
            return False, f"too_late_ny_{t:%H:%M}"
        return True, "ok"

    def load_history(self, ctx: DayContext) -> None:
        start = ny_dt(ctx.sessions[0].day, dt.time(4, 0))
        end = ny_dt(ctx.session.day, dt.time(0, 0))
        hist = self.data.minute_bars(list(self.cfg.symbols), start, end)
        for sym in self.cfg.symbols:
            self.minutes[sym] = hist.get(sym, pd.DataFrame())
            self.prior[sym] = build_prior(self.minutes[sym], ctx.sessions[:-1], self.cfg)
            self.assets[sym] = self.broker.asset(sym)
            log.info("history loaded", extra={"symbol": sym, "minute_bars": len(self.minutes[sym]), "prior_5m": len(self.prior[sym].bars5)})

    def refresh_today(self, ctx: DayContext, now: dt.datetime) -> None:
        start = ny_dt(ctx.session.day, dt.time(4, 0))
        fresh = self.data.minute_bars(list(self.cfg.symbols), start, now)
        for sym in self.cfg.symbols:
            old = self.minutes.get(sym, pd.DataFrame())
            old = old[old.index < start] if not old.empty else old
            new = fresh.get(sym, pd.DataFrame())
            self.minutes[sym] = pd.concat([old, new]).sort_index() if not new.empty else old

    # ----------------------------------------------------------- reconcile

    def reconcile(self, ctx: DayContext, now: dt.datetime, rec: Recorder) -> None:
        today = ctx.session.day
        st = snapshot(self.broker.positions(), self.broker.orders("open"), self.cfg, today)
        for o in st.stale_orders:
            self.exec.cancel(o, "stale_from_previous_day")
            rec.event("cancel_stale", order=o.client_order_id)
        if st.foreign_orders:
            log.warning("open orders not placed by this bot", extra={"count": len(st.foreign_orders)})
        todays = reconstruct_trades(self.broker.orders("all", after=ny_dt(today, dt.time(0))), self.cfg.execution.client_order_id_prefix)
        today_syms = {t.symbol for t in todays if t.exit_time is None}
        overnight = [p.symbol for p in st.positions if p.qty != 0 and p.symbol not in today_syms]
        if (overnight or st.unprotected) and ctx.session.contains(now):
            reason = "overnight_position" if overnight else "unprotected_position"
            self.notify.send("halt", f"{reason}: {overnight or st.unprotected} - flattening")
            rec.event("flatten", reason=reason, actions=self.exec.flatten_all(today, reason, set(overnight) | set(st.unprotected)))
        elif overnight:
            log.warning("overnight positions found before the open - will flatten at the open", extra={"symbols": overnight})

    # ---------------------------------------------------------------- cycle

    def account_snapshot(self) -> AccountSnapshot:
        a = self.broker.account()
        return AccountSnapshot(
            equity=float(a.equity), last_equity=float(a.last_equity), buying_power=float(a.buying_power),
            shorting_enabled=bool(getattr(a, "shorting_enabled", True)), trading_blocked=bool(getattr(a, "trading_blocked", False)),
            account_blocked=bool(getattr(a, "account_blocked", False)), pattern_day_trader=bool(getattr(a, "pattern_day_trader", False)),
        )

    def frames(self, ctx: DayContext, now: dt.datetime) -> tuple[dict[str, SymbolFrames], dict[str, DataQuality]]:
        out, quality = {}, {}
        for sym in self.cfg.symbols:
            fr = build_frames(sym, self.minutes.get(sym, pd.DataFrame()), ctx.sessions, now, self.cfg, prior=self.prior[sym])
            out[sym] = fr
            today5 = fr.bars5.iloc[fr.today_start :]
            q = assess_quality(sym, self.minutes.get(sym, pd.DataFrame()), today5, ctx.session, now, self.cfg.data.min_minutes_per_5m_bar)
            quality[sym] = q
            if q.expected_minutes >= 15 and q.coverage < self.cfg.data.sparse_warn_ratio:
                log.warning("sparse 1-minute data", extra={"symbol": sym, "coverage": round(q.coverage, 3), "sparse_5m_bars": q.sparse_5m_bars,
                                                           "hint": "thin IEX prints; consider QQQ instead of QQQM"})
        return out, quality

    def manage_working(self, frames: dict[str, SymbolFrames], st, cache: PlanCache, rec: Recorder) -> None:
        for order, meta in st.working_entries:
            fr = frames.get(order.symbol)
            if fr is None or fr.bars5.empty:
                continue
            plan = cache.get(meta["setup"]) or _plan_from_order(order, meta)
            today5 = fr.bars5.iloc[fr.today_start :]
            after = today5[today5.index > plan.placed_at]
            if after.empty:
                continue
            if order.filled_qty > 0 and order.status == "partially_filled":
                # bracket legs stay "held" until the entry is COMPLETELY filled; cancel the rest
                # so the reconcile step flattens the partial instead of leaving it unprotected.
                self.exec.cancel(order, "partial_fill_timeout")
                rec.event("cancel", order=order.client_order_id, reason="partial_fill_timeout")
                continue
            reason = pending_entry_action(plan, after.iloc[-1], len(after), self.cfg)
            if reason:
                self.exec.cancel(order, reason)
                rec.event("cancel", order=order.client_order_id, reason=reason)
                rec.signal(SignalRecord(after.index[-1], order.symbol, "order", "cancelled", reason, plan.setup_id, plan.direction.value, plan.score, plan.entry, plan.stop, plan.target), dedupe=False)

    def manage_break_even(self, frames: dict[str, SymbolFrames], orders_today: list[BrokerOrder], cache: PlanCache) -> None:
        """Uses ALL of today's orders: a filled bracket parent is no longer
        'open' even though its stop leg is, so the open list may omit it."""
        be = self.cfg.execution.break_even
        if not be.enabled:
            return
        for o in orders_today:
            if o.filled_qty <= 0 or o.order_class != "bracket":
                continue
            stop_leg = next((leg for leg in o.legs if leg.type == "stop" and leg.is_open), None)
            if stop_leg is None or stop_leg.stop_price is None or o.filled_avg_price is None:
                continue
            meta = parse_client_order_id(o.client_order_id)
            meta_plan = cache.get(meta["setup"]) if meta else None
            stop0 = meta_plan.stop if meta_plan else stop_leg.stop_price
            entry = o.filled_avg_price
            r = abs(entry - stop0)
            fr = frames.get(o.symbol)
            if r <= 0 or fr is None or o.filled_at is None:
                continue
            since = fr.bars5[fr.bars5.index >= o.filled_at.astimezone(NY).replace(second=0, microsecond=0)]
            if since.empty:
                continue
            long = o.side == "buy"
            fav = (since["high"].max() - entry) if long else (entry - since["low"].min())
            new_stop = round_to_tick(entry + (be.offset if long else -be.offset), self.cfg.execution.tick_size, "up" if long else "down")
            better = new_stop > stop_leg.stop_price if long else new_stop < stop_leg.stop_price
            if fav >= be.trigger_r * r and better:
                try:
                    self.exec.move_stop(stop_leg, new_stop)
                except Exception as exc:  # noqa: BLE001 - original stop remains in force
                    log.warning("break-even replace failed; original stop still active", extra={"error": str(exc)[:200]})

    def market_check(self, sym: str, fr: SymbolFrames, quality: DataQuality, now: dt.datetime, session: TradingSession) -> MarketCheck:
        quote: Quote | None
        try:
            quote = self.data.latest_quote(sym)
        except Exception as exc:  # noqa: BLE001
            log.warning("quote fetch failed", extra={"symbol": sym, "error": str(exc)[:200]})
            quote = None
        vol = fr.bars5["volume"].to_numpy(float)
        rv = relative_volume(vol)
        a = self.assets.get(sym)
        return MarketCheck(
            now=now, session_close=session.close, quote=quote, bar_volume=float(vol[-1]) if len(vol) else 0.0,
            rvol=float(rv[-1]) if len(rv) and math.isfinite(rv[-1]) else None, newest_bar_age_s=quality.newest_bar_age_s,
            tradable=bool(getattr(a, "tradable", True)), shortable=bool(getattr(a, "shortable", True)), easy_to_borrow=bool(getattr(a, "easy_to_borrow", True)),
        )

    def cycle(self, ctx: DayContext, now: dt.datetime, cache: PlanCache, rec: Recorder) -> dict[str, Any]:
        today = ctx.session.day
        self.refresh_today(ctx, now)
        frames, quality = self.frames(ctx, now)

        orders_today = self.broker.orders("all", after=ny_dt(today, dt.time(0)))
        st = snapshot(self.broker.positions(), self.broker.orders("open"), self.cfg, today)
        trades = reconstruct_trades(orders_today, self.cfg.execution.client_order_id_prefix, cache.all())
        account = self.account_snapshot()
        working_ids = {meta["setup"] for o, meta in st.working_entries if o.filled_qty == 0}
        rstate = risk_state_from_broker(
            now=now, equity=account.equity, last_equity=account.last_equity, equity_history=self.broker.equity_history(),
            trades=trades, working_setup_ids=working_ids, cfg=self.cfg, manual_disable=manual_disable_flag(),
        )
        halt = self.risk.status(account, rstate)
        info = {"equity": account.equity, "day_pnl_pct": round(rstate.day_pnl_pct, 3), "week_pnl_pct": round(rstate.week_pnl_pct, 3),
                "drawdown_pct": round(rstate.drawdown_pct, 3), "trades_today": rstate.trades_today, "halt": list(halt.reasons)}

        # --- safety first --------------------------------------------------
        if st.unprotected:
            self.notify.send("halt", f"UNPROTECTED position(s) {st.unprotected} - flattening")
            rec.event("flatten", reason="unprotected", actions=self.exec.flatten_all(today, "unprotected", set(st.unprotected)))
            return info
        if halt.flatten and (st.positions or st.working_entries):
            rec.event("flatten", reason=",".join(halt.reasons), actions=self.exec.flatten_all(today, "risk_halt"))
        for reason in halt.reasons:
            if reason not in self.halt_alerted and reason not in ("max_trades_per_day", "cooldown_after_loss"):
                self.halt_alerted.add(reason)
                self.notify.send("halt", f"{reason} | {info}")
                rec.event("halt", reason=reason, **info)
        if halt.kill_switch:
            self.kill_switch = True
        if halt.flatten:
            self.day_halted = True

        self.manage_working(frames, st, cache, rec)
        self.manage_break_even(frames, orders_today, cache)
        self._alert_new_fills(orders_today, rec)

        # --- entries -------------------------------------------------------
        window_ok, window_reason = entry_window_open(now, ctx.session, self.cfg)
        candidates = []
        for sym, fr in frames.items():
            sparse = quality[sym].coverage < self.cfg.data.sparse_warn_ratio
            res = find_setups(fr, self.cfg, data_sparse=sparse)
            for r in res.records:
                rec.signal(r)
            if res.setups:
                best = next((s for s in res.setups if not _already_used(s.setup_id, orders_today) and s.setup_id not in self.dry_placed), None)
                if best:
                    candidates.append(best)
            info[f"bias_{sym}"] = res.bias.get("combined")
        blocker = None
        if not ctx.trading_allowed:
            blocker = ctx.skip_reason
        elif not window_ok:
            blocker = window_reason
        elif not halt.can_open:
            blocker = "halted:" + ",".join(halt.reasons)
        if blocker:
            for s in candidates:
                rec.signal(_record(s, "skipped", blocker))
            return info

        selections, skipped = select_setups(candidates, st.exposures, self.cfg)
        for s, why in skipped:
            rec.signal(_record(s, "skipped", why))
        exposures = list(st.exposures)
        for sel in selections:
            s = sel.setup
            fr = frames[s.symbol]
            mk = self.market_check(s.symbol, fr, quality[s.symbol], now, ctx.session)
            bucket = bucket_for(s.symbol, self.cfg)
            if s.direction is Direction.SHORT and not account.shorting_enabled:
                rec.signal(_record(s, "rejected", "account_shorting_disabled"))
                continue
            decision = self.risk.approve(s, account, rstate, exposures, mk, bucket.symbols, bucket.max_open_risk_multiple, sel.risk_fraction)
            if isinstance(decision, Rejection):
                rec.signal(_record(s, "rejected", f"{decision.reason}:{decision.detail}" if decision.detail else decision.reason))
                continue
            assert isinstance(decision, ApprovedOrder)
            placed = self.exec.place_entry(decision, today)
            if placed.dry_run:
                self.dry_placed.add(s.setup_id)
            cache.put(EntryPlan.from_setup(s))
            exposures.append(_pending_exposure(decision))
            rec.signal(_record(s, "taken", f"qty={decision.qty} risk=${decision.risk_dollars} {sel.note} {' '.join(decision.notes)}".strip()), dedupe=False)
            rec.event("entry", setup_id=s.setup_id, symbol=s.symbol, qty=decision.qty, entry=s.entry, stop=s.stop, target=s.target,
                      score=s.score, coids=placed.client_order_ids, dry_run=placed.dry_run, duplicate=placed.duplicate)
            self.notify.send("fill", f"ENTRY ORDER {s.symbol} {s.direction.value} {decision.qty} @ {s.entry} stop {s.stop} target {s.target} (score {s.score})")
        return info

    def _alert_new_fills(self, orders: list[BrokerOrder], rec: Recorder) -> None:
        seen = getattr(self, "_fill_ids", set())
        for o in orders:
            for x in [o, *o.legs]:
                if x.filled_qty > 0 and x.id not in seen and x.status == "filled":
                    seen.add(x.id)
                    rec.event("fill", symbol=x.symbol, side=x.side, qty=x.filled_qty, price=x.filled_avg_price, coid=x.client_order_id)
                    self.notify.send("fill", f"FILL {x.symbol} {x.side} {x.filled_qty} @ {x.filled_avg_price}")
        self._fill_ids = seen

    # ------------------------------------------------------------------ run

    def run(self, respect_start_window: bool = True) -> int:
        now = self.clock()
        if respect_start_window:
            ok, why = self.start_gate(now)
            if not ok:
                log.info("start gate closed - exiting (expected for the off-DST cron trigger)", extra={"reason": why})
                return 0
        ctx = self.day_context(now)
        if ctx is None:
            log.info("market closed today per Alpaca calendar - exiting")
            return 0
        rec = Recorder(self.cfg.reporting.reports_dir, ctx.session.day)
        cache = PlanCache(self.state_dir, ctx.session.day)
        log.info("session", extra={"open": ctx.session.open.isoformat(), "close": ctx.session.close.isoformat(),
                                   "trading_allowed": ctx.trading_allowed, "skip_reason": ctx.skip_reason, "dry_run": self.cfg.mode.dry_run})
        rec.event("start", trading_allowed=ctx.trading_allowed, skip_reason=ctx.skip_reason, alerts=self.notify.channels)

        if now < ctx.session.open:
            if not respect_start_window and ctx.session.open - now > dt.timedelta(minutes=MANUAL_MAX_WAIT_MINUTES):
                log.info("manual run long before the open: connection + paper checks passed, exiting instead of waiting",
                         extra={"open": ctx.session.open.isoformat()})
                rec.event("manual_check_ok", open=ctx.session.open)
                return 0
            self._sleep_until(ctx.session.open + dt.timedelta(seconds=5))
        self.reconcile(ctx, self.clock(), rec)
        self.load_history(ctx)

        flatten_at = ny_dt(ctx.session.day, parse_hhmm(self.cfg.session.flatten_time))
        flatten_at = min(flatten_at, ctx.session.close - dt.timedelta(minutes=5))
        deadline = now + dt.timedelta(minutes=self.cfg.session.max_runtime_minutes)
        windows_end = last_window_end(ctx.session, self.cfg)
        errors = 0
        info: dict[str, Any] = {}
        exit_code = 0
        while True:
            wake = next_bar_boundary(self.clock(), ctx.session.open) + dt.timedelta(seconds=self.cfg.data.poll_offset_seconds)
            wake = min(wake, flatten_at, deadline)
            self._sleep_until(wake)
            now = self.clock()
            if now >= flatten_at:
                rec.event("flatten", reason="end_of_day", actions=self.exec.flatten_all(ctx.session.day, "end_of_day"))
                break
            if now >= deadline:
                log.warning("max runtime reached - exiting; server-side brackets stay in force and the flatten job closes positions")
                break
            try:
                info = self.cycle(ctx, now, cache, rec)
                errors = 0
                log.info("cycle", extra=info)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.exception("cycle failed", extra={"consecutive": errors})
                self.notify.send("error", f"cycle error #{errors}: {str(exc)[:300]}")
                if errors >= MAX_CONSECUTIVE_CYCLE_ERRORS:
                    self.notify.send("halt", "too many consecutive errors - flattening and exiting")
                    try:
                        self.exec.flatten_all(ctx.session.day, "error_storm")
                    finally:
                        exit_code = 2
                    break
            nothing_left = now >= windows_end or not ctx.trading_allowed or self.day_halted
            if self.cfg.session.exit_when_idle_after_windows and nothing_left:
                if not self.broker.positions() and not self.broker.orders("open"):
                    log.info("flat, no working orders and no further entries possible today - exiting early")
                    break
        self.finish(ctx, rec, cache, info)
        return exit_code

    def _sleep_until(self, when: dt.datetime) -> None:
        while True:
            remaining = (when - self.clock()).total_seconds()
            if remaining <= 0:
                return
            self.sleep(min(remaining, 60.0))

    def finish(self, ctx: DayContext, rec: Recorder, cache: PlanCache, info: dict[str, Any]) -> None:
        today = ctx.session.day
        try:
            orders = self.broker.orders("all", after=ny_dt(today, dt.time(0)))
            trades = reconstruct_trades(orders, self.cfg.execution.client_order_id_prefix, cache.all())
            trades = [_with_excursions(t, self.minutes.get(t.symbol)) for t in trades]
            rec.write_trades(trades)
            closes = {s: f.bars5["close"] for s, f in self.frames(ctx, self.clock())[0].items() if not f.bars5.empty}
            context = {**info, "session": {"open": ctx.session.open, "close": ctx.session.close}, "trading_allowed": ctx.trading_allowed,
                       "skip_reason": ctx.skip_reason, "correlation_5m": correlation_report(closes, self.cfg.indicators.correlation_window_bars),
                       "dry_run": self.cfg.mode.dry_run}
            write_journal(rec, today, trades, context=context, metrics=compute_metrics(trades))
            log.info("journal written", extra={"dir": str(rec.day_dir)})
        except Exception:  # noqa: BLE001
            log.exception("failed to write end-of-day journal")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _plan_from_order(order: BrokerOrder, meta: dict[str, str]) -> EntryPlan:
    from .state import _plan_from_order as f

    return f(order, meta)


def _already_used(setup_id: str, orders: list[BrokerOrder]) -> bool:
    return any(f"-{setup_id}-" in o.client_order_id for o in orders)


def _record(s, decision: str, reason: str) -> SignalRecord:
    return SignalRecord(s.signal_time, s.symbol, "decision", decision, reason, s.setup_id, s.direction.value, s.score, s.entry, s.stop, s.target, round(s.reward_risk, 3))


def _pending_exposure(o: ApprovedOrder):
    from .risk import Exposure

    return Exposure(o.symbol, o.direction, o.qty, o.entry, o.stop, pending=True)


def _with_excursions(t: TradeRecord, bars: pd.DataFrame | None) -> TradeRecord:
    import dataclasses

    mae, mfe = mae_mfe(t, bars) if bars is not None else (None, None)
    return dataclasses.replace(t, mae_r=mae, mfe_r=mfe)


def build_live_bot(cfg: BotConfig) -> LiveBot:
    from .data import AlpacaMarketData
    from .safety import load_paper_credentials

    creds = load_paper_credentials()
    broker = AlpacaBroker(creds.key_id, creds.secret_key)
    data = AlpacaMarketData(creds.key_id, creds.secret_key, cfg.data.feed)
    return LiveBot(cfg, broker, data, Notifier(cfg.alerts))
