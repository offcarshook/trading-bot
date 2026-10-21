"""Order execution against Alpaca PAPER.

Verified against alpaca-py 0.44.0 + Alpaca docs (Oct 2026):
* Bracket = entry + take-profit limit + stop-loss stop; TIF must be day/gtc;
  extended hours NOT supported; legs activate only after the entry fills;
  cancelling one leg cancels the rest; PATCH can change leg stop/limit.
* Stop price must be >= $0.01 away from the "base price" (entry limit).
* Fractional orders only support simple market/limit/stop/stop-limit DAY
  orders and can never be short, so brackets here always use WHOLE shares.
* client_order_id must be unique per account -> deterministic IDs make a
  restart unable to double-place the same setup.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import BotConfig
from .models import Direction
from .retry import call_with_retry
from .risk import ApprovedOrder, assert_order_invariants
from .safety import assert_paper_account
from .strategy import round_to_tick
from .timeutils import NY, TradingSession, session_from_calendar

log = logging.getLogger(__name__)

OPEN_STATUSES = frozenset(
    {"new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled", "held", "pending_replace", "pending_cancel", "calculated", "suspended"}
)
COID_RE = re.compile(r"^(?P<prefix>[a-z0-9]{1,8})-(?P<day>\d{6})-(?P<symbol>[A-Z.]{1,10})-(?P<setup>[0-9a-z]{6,12})-(?P<leg>[a-z]{1,2})$")


# --------------------------------------------------------------------------- #
# Broker-neutral views
# --------------------------------------------------------------------------- #


@dataclass
class BrokerOrder:
    id: str
    client_order_id: str
    symbol: str
    side: str  # "buy" | "sell"
    type: str  # market | limit | stop | stop_limit
    status: str
    qty: float
    filled_qty: float
    filled_avg_price: float | None
    limit_price: float | None
    stop_price: float | None
    order_class: str  # simple | bracket | oco | oto
    submitted_at: dt.datetime | None
    filled_at: dt.datetime | None
    legs: list["BrokerOrder"] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    qty: float  # signed: negative = short
    avg_entry_price: float
    current_price: float | None


@dataclass(frozen=True)
class AssetInfo:
    symbol: str
    tradable: bool
    shortable: bool
    easy_to_borrow: bool
    fractionable: bool


class Broker(Protocol):
    def account(self) -> Any: ...
    def positions(self) -> list[BrokerPosition]: ...
    def orders(self, status: str = "open", after: dt.datetime | None = None) -> list[BrokerOrder]: ...
    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None: ...
    def submit_bracket(self, *, symbol: str, side: str, qty: int, limit_price: float, take_profit: float, stop_loss: float, tif: str, client_order_id: str) -> BrokerOrder: ...
    def submit_market(self, *, symbol: str, side: str, qty: int, client_order_id: str) -> BrokerOrder: ...
    def cancel(self, order_id: str) -> None: ...
    def replace_stop(self, order_id: str, stop_price: float) -> BrokerOrder: ...
    def asset(self, symbol: str) -> AssetInfo: ...
    def sessions(self, start: dt.date, end: dt.date) -> list[TradingSession]: ...
    def equity_history(self) -> list[tuple[dt.date, float]]: ...


def make_client_order_id(prefix: str, day: dt.date, symbol: str, setup_id: str, leg: str) -> str:
    coid = f"{prefix}-{day:%y%m%d}-{symbol}-{setup_id}-{leg}"
    if len(coid) > 128:  # Alpaca limit
        raise ValueError("client_order_id too long")
    return coid


def parse_client_order_id(coid: str) -> dict[str, str] | None:
    m = COID_RE.match(coid or "")
    return m.groupdict() if m else None


# --------------------------------------------------------------------------- #
# Alpaca implementation
# --------------------------------------------------------------------------- #


def _f(x: Any) -> float | None:
    return None if x is None or x == "" else float(x)


def _enum(x: Any) -> str:
    return str(getattr(x, "value", x) or "")


def _order_view(o: Any) -> BrokerOrder:
    return BrokerOrder(
        id=str(o.id),
        client_order_id=o.client_order_id,
        symbol=o.symbol or "",
        side=_enum(o.side),
        type=_enum(o.type or o.order_type),
        status=_enum(o.status),
        qty=_f(o.qty) or 0.0,
        filled_qty=_f(o.filled_qty) or 0.0,
        filled_avg_price=_f(o.filled_avg_price),
        limit_price=_f(o.limit_price),
        stop_price=_f(o.stop_price),
        order_class=_enum(o.order_class) or "simple",
        submitted_at=o.submitted_at,
        filled_at=o.filled_at,
        legs=[_order_view(leg) for leg in (o.legs or [])],
    )


class AlpacaBroker:
    """Thin, retrying adapter. ``paper=True`` is hardcoded; no override URL."""

    def __init__(self, key_id: str, secret_key: str) -> None:
        from alpaca.trading.client import TradingClient

        self._c = TradingClient(key_id, secret_key, paper=True)
        base = getattr(self._c, "_base_url", "")
        self.base_url = str(getattr(base, "value", base))
        acct = self.account()
        assert_paper_account(acct.account_number, self.base_url)

    def account(self) -> Any:
        return call_with_retry(self._c.get_account, what="get_account")

    def account_configuration(self) -> Any:
        return call_with_retry(self._c.get_account_configurations, what="get_account_configurations")

    def positions(self) -> list[BrokerPosition]:
        rows = call_with_retry(self._c.get_all_positions, what="get_all_positions")
        out = []
        for p in rows:
            qty = float(p.qty)
            if _enum(p.side) == "short" and qty > 0:
                qty = -qty
            out.append(BrokerPosition(p.symbol, qty, float(p.avg_entry_price), _f(p.current_price)))
        return out

    def orders(self, status: str = "open", after: dt.datetime | None = None) -> list[BrokerOrder]:
        from alpaca.common.enums import Sort
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        out: list[BrokerOrder] = []
        cursor = after
        while True:
            req = GetOrdersRequest(status=QueryOrderStatus(status), after=cursor, nested=True, limit=500, direction=Sort.ASC)
            page = call_with_retry(lambda: self._c.get_orders(filter=req), what="get_orders")
            out += [_order_view(o) for o in page]
            if len(page) < 500:
                break
            cursor = page[-1].submitted_at
        seen: set[str] = set()
        return [o for o in out if not (o.id in seen or seen.add(o.id))]

    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        try:
            return _order_view(call_with_retry(lambda: self._c.get_order_by_client_id(client_order_id), what="get_order_by_client_id"))
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "status_code", None) == 404:
                return None
            raise

    def submit_bracket(self, *, symbol: str, side: str, qty: int, limit_price: float, take_profit: float, stop_loss: float, tif: str, client_order_id: str) -> BrokerOrder:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest

        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide(side),
            time_in_force=TimeInForce(tif),
            limit_price=limit_price,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=take_profit),
            stop_loss=StopLossRequest(stop_price=stop_loss),
            extended_hours=False,
            client_order_id=client_order_id,
        )
        return _order_view(call_with_retry(lambda: self._c.submit_order(order_data=req), what="submit_bracket"))

    def submit_market(self, *, symbol: str, side: str, qty: int, client_order_id: str) -> BrokerOrder:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide(side), time_in_force=TimeInForce.DAY, client_order_id=client_order_id)
        return _order_view(call_with_retry(lambda: self._c.submit_order(order_data=req), what="submit_market"))

    def cancel(self, order_id: str) -> None:
        try:
            call_with_retry(lambda: self._c.cancel_order_by_id(order_id), what="cancel_order")
        except Exception as exc:  # noqa: BLE001 - already filled/cancelled is fine
            if getattr(exc, "status_code", None) not in (404, 422):
                raise
            log.info("cancel no-op", extra={"order_id": order_id, "error": str(exc)[:200]})

    def replace_stop(self, order_id: str, stop_price: float) -> BrokerOrder:
        from alpaca.trading.requests import ReplaceOrderRequest

        req = ReplaceOrderRequest(stop_price=stop_price)
        return _order_view(call_with_retry(lambda: self._c.replace_order_by_id(order_id, req), what="replace_stop"))

    def asset(self, symbol: str) -> AssetInfo:
        a = call_with_retry(lambda: self._c.get_asset(symbol), what="get_asset")
        return AssetInfo(a.symbol, bool(a.tradable), bool(a.shortable), bool(a.easy_to_borrow), bool(a.fractionable))

    def sessions(self, start: dt.date, end: dt.date) -> list[TradingSession]:
        from alpaca.trading.requests import GetCalendarRequest

        rows = call_with_retry(lambda: self._c.get_calendar(GetCalendarRequest(start=start, end=end)), what="get_calendar")
        return [session_from_calendar(r.date, r.open, r.close) for r in rows]

    def clock(self) -> Any:
        return call_with_retry(self._c.get_clock, what="get_clock")

    def equity_history(self) -> list[tuple[dt.date, float]]:
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        req = GetPortfolioHistoryRequest(period="1A", timeframe="1D")
        h = call_with_retry(lambda: self._c.get_portfolio_history(req), what="get_portfolio_history")
        out = []
        for ts, eq in zip(h.timestamp, h.equity):
            if eq is None:
                continue
            out.append((dt.datetime.fromtimestamp(ts, tz=NY).date(), float(eq)))
        return out


# --------------------------------------------------------------------------- #
# Execution engine
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlacedEntry:
    client_order_ids: tuple[str, ...]
    orders: tuple[BrokerOrder, ...]
    duplicate: bool
    dry_run: bool


class ExecutionEngine:
    def __init__(self, broker: Broker, cfg: BotConfig, dry_run: bool = False, sleep=time.sleep) -> None:
        self._b = broker
        self._cfg = cfg
        self._dry = dry_run
        self._sleep = sleep

    @property
    def prefix(self) -> str:
        return self._cfg.execution.client_order_id_prefix

    def _legs(self, order: ApprovedOrder) -> list[tuple[str, int, float]]:
        """(leg_code, qty, take_profit) - one bracket, or two for partial TP."""
        ex = self._cfg.execution
        pt = ex.partial_take_profit
        if pt.enabled:
            qa = math.floor(order.qty * pt.fraction)
            qb = order.qty - qa
            rps = abs(order.entry - order.stop)
            tp_a_raw = order.entry + order.direction.sign * pt.at_r * rps
            tp_a = round_to_tick(tp_a_raw, ex.tick_size, "down" if order.direction is Direction.LONG else "up")
            closer = tp_a < order.target if order.direction is Direction.LONG else tp_a > order.target
            if qa >= 1 and qb >= 1 and closer and tp_a != order.entry:
                return [("a", qa, tp_a), ("b", qb, order.target)]
        return [("e", order.qty, order.target)]

    def place_entry(self, order: ApprovedOrder, day: dt.date) -> PlacedEntry:
        """Idempotent: an existing order with the same deterministic client_order_id
        is returned instead of being placed twice."""
        side = "buy" if order.direction is Direction.LONG else "sell"
        tif = self._cfg.execution.bracket_time_in_force
        coids, placed, dup = [], [], False
        for leg, qty, tp in self._legs(order):
            assert_order_invariants(order.direction, qty, order.entry, order.stop, tp)
            coid = make_client_order_id(self.prefix, day, order.symbol, order.setup_id, leg)
            coids.append(coid)
            if self._dry:
                log.info("DRY RUN - bracket not sent", extra={"coid": coid, "qty": qty, "entry": order.entry, "stop": order.stop, "tp": tp})
                continue
            existing = self._b.order_by_client_id(coid)
            if existing is not None:
                dup = True
                placed.append(existing)
                log.warning("order already exists - not re-submitting", extra={"coid": coid, "status": existing.status})
                continue
            try:
                o = self._b.submit_bracket(symbol=order.symbol, side=side, qty=qty, limit_price=order.entry, take_profit=tp, stop_loss=order.stop, tif=tif, client_order_id=coid)
            except Exception as exc:  # noqa: BLE001
                again = self._b.order_by_client_id(coid)  # a timed-out request may have landed
                if again is None:
                    raise
                log.warning("submit raised but order exists", extra={"coid": coid, "error": str(exc)[:200]})
                o, dup = again, True
            placed.append(o)
            log.info("bracket submitted", extra={"coid": coid, "id": o.id, "status": o.status, "qty": qty, "entry": order.entry, "stop": order.stop, "tp": tp})
        return PlacedEntry(tuple(coids), tuple(placed), dup, self._dry)

    def cancel(self, order: BrokerOrder, reason: str) -> None:
        if self._dry:
            log.info("DRY RUN - cancel skipped", extra={"id": order.id, "reason": reason})
            return
        log.info("cancelling order", extra={"id": order.id, "coid": order.client_order_id, "reason": reason})
        self._b.cancel(order.id)

    def move_stop(self, stop_leg: BrokerOrder, new_stop: float) -> BrokerOrder | None:
        if self._dry:
            return None
        log.info("moving stop", extra={"id": stop_leg.id, "from": stop_leg.stop_price, "to": new_stop})
        return self._b.replace_stop(stop_leg.id, new_stop)

    def _wait_symbol_orders_closed(self, symbol: str) -> bool:
        deadline = time.monotonic() + self._cfg.execution.order_status_timeout_seconds
        while time.monotonic() < deadline:
            if not [o for o in self._b.orders("open") if o.symbol == symbol and (o.is_open or any(leg.is_open for leg in o.legs))]:
                return True
            self._sleep(self._cfg.execution.order_status_poll_seconds)
        return False

    def flatten_all(self, day: dt.date, reason: str, symbols: set[str] | None = None) -> list[str]:
        """Cancel open orders, then close positions with tagged market orders.
        ``symbols=None`` means EVERYTHING - the paper account is assumed to be
        dedicated to the bot."""
        actions: list[str] = []
        open_orders = [o for o in self._b.orders("open") if symbols is None or o.symbol in symbols]
        for o in open_orders:
            # a FILLED bracket parent is no longer open but its exit legs are:
            # cancel every open node individually (duplicate cancels are no-ops)
            for node in [o, *o.legs]:
                if node.is_open:
                    self.cancel(node, f"flatten:{reason}")
                    actions.append(f"cancel {node.symbol} {node.client_order_id}")
        for p in self._b.positions():
            if p.qty == 0 or (symbols is not None and p.symbol not in symbols):
                continue
            if not self._dry and not self._wait_symbol_orders_closed(p.symbol):
                log.error("orders still open; closing anyway", extra={"symbol": p.symbol})
            side = "sell" if p.qty > 0 else "buy"
            qty = int(abs(p.qty)) if float(abs(p.qty)).is_integer() else abs(p.qty)
            stamp = dt.datetime.now(tz=NY).strftime("%H%M%S")
            coid = make_client_order_id(self.prefix, day, p.symbol, f"x{stamp}", "f")
            if self._dry:
                actions.append(f"DRY close {p.symbol} {p.qty}")
                continue
            o = self._b.submit_market(symbol=p.symbol, side=side, qty=qty, client_order_id=coid)
            actions.append(f"close {p.symbol} {p.qty} -> {o.id}")
            log.warning("flatten market order", extra={"symbol": p.symbol, "qty": p.qty, "reason": reason, "coid": coid})
        return actions
