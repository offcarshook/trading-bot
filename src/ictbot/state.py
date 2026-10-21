"""State reconstruction and reconciliation - the BROKER is the source of truth.

On every start and every cycle the bot rebuilds positions, working orders,
today's trades, losses and P&L from Alpaca. The local JSON cache only adds
metadata Alpaca cannot hold (FVG bounds, sweep extreme, original stop); losing
it degrades management slightly but never safety.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from .config import BotConfig
from .execution import BrokerOrder, BrokerPosition, parse_client_order_id
from .models import Direction, TradeRecord
from .risk import Exposure, RiskState
from .strategy import EntryPlan
from .timeutils import NY, week_start

log = logging.getLogger(__name__)
ENTRY_LEGS = ("e", "a", "b")


# --------------------------------------------------------------------------- #
# Local metadata cache (non-authoritative)
# --------------------------------------------------------------------------- #


class PlanCache:
    def __init__(self, state_dir: str | Path, day: dt.date) -> None:
        self._path = Path(state_dir) / f"plans-{day.isoformat()}.json"
        self._plans: dict[str, EntryPlan] = {}
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                self._plans = {k: EntryPlan.from_dict(v) for k, v in raw.items()}
            except (ValueError, KeyError, TypeError) as exc:
                log.warning("plan cache unreadable - continuing from broker state only", extra={"error": str(exc)})

    def get(self, setup_id: str) -> EntryPlan | None:
        return self._plans.get(setup_id)

    def put(self, plan: EntryPlan) -> None:
        self._plans[plan.setup_id] = plan
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({k: v.to_dict() for k, v in self._plans.items()}, indent=1))

    def all(self) -> dict[str, EntryPlan]:
        return dict(self._plans)


# --------------------------------------------------------------------------- #
# Trade reconstruction from orders
# --------------------------------------------------------------------------- #


def _tp_and_sl(order: BrokerOrder) -> tuple[BrokerOrder | None, BrokerOrder | None]:
    tp = next((leg for leg in order.legs if leg.type == "limit"), None)
    sl = next((leg for leg in order.legs if leg.type in ("stop", "stop_limit", "trailing_stop")), None)
    return tp, sl


def _plan_from_order(order: BrokerOrder, meta: dict[str, str]) -> EntryPlan:
    tp, sl = _tp_and_sl(order)
    direction = Direction.LONG if order.side == "buy" else Direction.SHORT
    return EntryPlan(
        setup_id=meta["setup"], symbol=order.symbol, direction=direction,
        entry=order.limit_price or 0.0, stop=(sl.stop_price if sl else math.nan) or math.nan,
        target=(tp.limit_price if tp else math.nan) or math.nan,
        placed_at=(order.submitted_at or dt.datetime.now(tz=NY)).astimezone(NY),
    )


def our_entry_orders(orders: list[BrokerOrder], prefix: str) -> list[tuple[BrokerOrder, dict[str, str]]]:
    out = []
    for o in orders:
        meta = parse_client_order_id(o.client_order_id)
        if meta and meta["prefix"] == prefix and meta["leg"] in ENTRY_LEGS:
            out.append((o, meta))
    return out


def reconstruct_trades(orders: list[BrokerOrder], prefix: str, plans: dict[str, EntryPlan] | None = None) -> list[TradeRecord]:
    """Round trips from bracket parents, their filled legs, and the bot's
    flatten orders (allocated FIFO per symbol). Partial-TP twin brackets with
    the same setup id are merged into one trade."""
    plans = plans or {}
    flats = sorted(
        (o for o in orders if (m := parse_client_order_id(o.client_order_id)) and m["prefix"] == prefix and m["leg"] == "f" and o.filled_qty > 0),
        key=lambda o: o.filled_at or o.submitted_at,
    )
    flat_left = {o.id: o.filled_qty for o in flats}
    groups: dict[str, dict] = {}
    for o, meta in sorted(our_entry_orders(orders, prefix), key=lambda x: x[0].filled_at or x[0].submitted_at or dt.datetime.min.replace(tzinfo=NY)):
        if o.filled_qty <= 0 or o.filled_avg_price is None:
            continue
        key = f"{meta['day']}-{o.symbol}-{meta['setup']}"
        g = groups.setdefault(key, {"entry_val": 0.0, "qty": 0.0, "exit_val": 0.0, "exit_qty": 0.0, "reasons": set(),
                                    "entry_time": o.filled_at, "exit_time": None, "order": o, "meta": meta, "targets": []})
        g["entry_val"] += o.filled_qty * o.filled_avg_price
        g["qty"] += o.filled_qty
        tp, sl = _tp_and_sl(o)
        if tp and tp.limit_price:
            g["targets"].append(tp.limit_price)
        remaining = o.filled_qty
        for leg, reason in ((tp, "take_profit"), (sl, "stop_loss")):
            if leg and leg.filled_qty > 0 and leg.filled_avg_price is not None:
                g["exit_val"] += leg.filled_qty * leg.filled_avg_price
                g["exit_qty"] += leg.filled_qty
                remaining -= leg.filled_qty
                g["reasons"].add(reason)
                g["exit_time"] = max(filter(None, [g["exit_time"], leg.filled_at]), default=None)
        # allocate flatten fills for any residual quantity
        for f in flats:
            if remaining <= 1e-9:
                break
            if f.symbol != o.symbol or flat_left[f.id] <= 0 or (o.filled_at and f.filled_at and f.filled_at < o.filled_at):
                continue
            take = min(remaining, flat_left[f.id])
            flat_left[f.id] -= take
            remaining -= take
            g["exit_val"] += take * (f.filled_avg_price or 0.0)
            g["exit_qty"] += take
            g["reasons"].add("flatten")
            g["exit_time"] = max(filter(None, [g["exit_time"], f.filled_at]), default=None)

    trades = []
    for key, g in groups.items():
        o, meta = g["order"], g["meta"]
        direction = Direction.LONG if o.side == "buy" else Direction.SHORT
        entry = g["entry_val"] / g["qty"]
        plan = plans.get(meta["setup"]) or _plan_from_order(o, meta)
        stop = plan.stop
        closed = g["exit_qty"] >= g["qty"] - 1e-9
        exit_px = g["exit_val"] / g["exit_qty"] if g["exit_qty"] > 0 else None
        pnl = direction.sign * (g["exit_val"] - entry * g["exit_qty"]) if g["exit_qty"] > 0 else 0.0
        risk = abs(entry - stop) * g["qty"] if stop and math.isfinite(stop) else math.nan
        r_mult = pnl / risk if risk and math.isfinite(risk) and risk > 0 else math.nan
        reasons = g["reasons"]
        reason = "open" if not closed else ("+".join(sorted(reasons)) if reasons else "unknown")
        trades.append(
            TradeRecord(
                trade_id=key, symbol=o.symbol, direction=direction.value, setup_tag=plan.tag or "unknown",
                entry_time=g["entry_time"], entry_price=round(entry, 4), qty=g["qty"], stop_price=stop,
                target_price=max(g["targets"]) if direction is Direction.LONG and g["targets"] else (min(g["targets"]) if g["targets"] else plan.target),
                exit_time=g["exit_time"] if closed else None, exit_price=round(exit_px, 4) if exit_px else None,
                exit_reason=reason, pnl=round(pnl, 2), fees=0.0, r_multiple=round(r_mult, 3) if math.isfinite(r_mult) else math.nan,
                score=plan.score,
            )
        )
    return sorted(trades, key=lambda t: t.entry_time)


# --------------------------------------------------------------------------- #
# Snapshot of broker state
# --------------------------------------------------------------------------- #


@dataclass
class BrokerState:
    positions: list[BrokerPosition]
    open_orders: list[BrokerOrder]
    working_entries: list[tuple[BrokerOrder, dict[str, str]]]  # our open bracket parents
    exposures: list[Exposure]
    unprotected: list[str] = field(default_factory=list)  # symbols needing emergency flatten
    stale_orders: list[BrokerOrder] = field(default_factory=list)  # ours, from previous days
    foreign_orders: list[BrokerOrder] = field(default_factory=list)  # not placed by this bot


def snapshot(positions: list[BrokerPosition], open_orders: list[BrokerOrder], cfg: BotConfig, today: dt.date) -> BrokerState:
    prefix = cfg.execution.client_order_id_prefix
    working, stale, foreign = [], [], []
    for o in open_orders:
        meta = parse_client_order_id(o.client_order_id)
        if not meta or meta["prefix"] != prefix:
            foreign.append(o)
            continue
        if meta["day"] != f"{today:%y%m%d}":
            stale.append(o)
        elif meta["leg"] in ENTRY_LEGS:
            working.append((o, meta))

    exposures: list[Exposure] = []
    unprotected: list[str] = []
    for p in positions:
        if p.qty == 0:
            continue
        direction = Direction.LONG if p.qty > 0 else Direction.SHORT
        exit_side = "sell" if direction is Direction.LONG else "buy"
        stops = []
        for o in open_orders:
            for cand in [o, *o.legs]:
                if cand.symbol == p.symbol and cand.side == exit_side and cand.type in ("stop", "stop_limit", "trailing_stop") and cand.is_open:
                    stops.append(cand)
        covered = sum(s.qty - s.filled_qty for s in stops)
        if covered + 1e-9 < abs(p.qty):
            unprotected.append(p.symbol)
            exposures.append(Exposure(p.symbol, direction, abs(p.qty), p.avg_entry_price, None, pending=False))
            continue
        # worst (farthest) stop bounds the risk
        worst = min(s.stop_price for s in stops) if direction is Direction.LONG else max(s.stop_price for s in stops)
        exposures.append(Exposure(p.symbol, direction, abs(p.qty), p.avg_entry_price, worst, pending=False))

    for o, _meta in working:
        remaining = o.qty - o.filled_qty
        if remaining <= 0:
            continue
        _, sl = _tp_and_sl(o)
        direction = Direction.LONG if o.side == "buy" else Direction.SHORT
        exposures.append(Exposure(o.symbol, direction, remaining, o.limit_price or 0.0, sl.stop_price if sl else None, pending=True))
    return BrokerState(positions, open_orders, working, exposures, unprotected, stale, foreign)


# --------------------------------------------------------------------------- #
# Risk state from broker data
# --------------------------------------------------------------------------- #


def risk_state_from_broker(
    *,
    now: dt.datetime,
    equity: float,
    last_equity: float,
    equity_history: list[tuple[dt.date, float]],
    trades: list[TradeRecord],
    working_setup_ids: set[str],
    cfg: BotConfig,
    manual_disable: bool = False,
) -> RiskState:
    today = now.astimezone(NY).date()
    day_pnl = (equity - last_equity) / last_equity * 100.0 if last_equity > 0 else 0.0

    prior = [(d, e) for d, e in equity_history if d < today and e > 0]
    wk0 = week_start(today)
    before_week = [e for d, e in prior if d < wk0]
    week_base = before_week[-1] if before_week else (prior[0][1] if prior else last_equity)
    week_pnl = (equity - week_base) / week_base * 100.0 if week_base > 0 else 0.0

    reset = dt.date.fromisoformat(cfg.risk.drawdown_reset_date) if cfg.risk.drawdown_reset_date else None
    peak_pool = [e for d, e in prior if reset is None or d >= reset] + [equity]
    peak = max(peak_pool)
    dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0

    todays = [t for t in trades if t.entry_time and t.entry_time.astimezone(NY).date() == today]
    closed = sorted((t for t in todays if t.exit_time is not None), key=lambda t: t.exit_time, reverse=True)
    consecutive = 0
    for t in closed:
        if t.pnl < 0:
            consecutive += 1
        else:
            break
    losses = [t for t in closed if t.pnl < 0]
    last_loss = losses[0].exit_time if losses else None
    return RiskState(
        now=now, day_pnl_pct=day_pnl, week_pnl_pct=week_pnl, drawdown_pct=dd,
        trades_today=len({t.trade_id.rsplit('-', 1)[-1] for t in todays} | set(working_setup_ids)), consecutive_losses=consecutive,
        last_loss_exit=last_loss, manual_disable=manual_disable,
    )
