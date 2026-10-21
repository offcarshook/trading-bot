"""In-memory broker double with Alpaca-like semantics needed by the tests."""

from __future__ import annotations

import datetime as dt
import itertools
from types import SimpleNamespace

from ictbot.execution import AssetInfo, BrokerOrder, BrokerPosition
from ictbot.timeutils import NY


class DuplicateClientOrderId(Exception):
    status_code = 422


class FakeBroker:
    def __init__(self, equity: float = 100_000.0) -> None:
        self._ids = itertools.count(1)
        self.orders_by_id: dict[str, BrokerOrder] = {}
        self.pos: dict[str, BrokerPosition] = {}
        self.submits = 0
        self.fail_after_submit_once = False
        self.acct = SimpleNamespace(equity=str(equity), last_equity=str(equity), buying_power=str(equity * 2),
                                    account_number="PA123", shorting_enabled=True, trading_blocked=False,
                                    account_blocked=False, pattern_day_trader=False)

    # -- Broker protocol -----------------------------------------------------
    def account(self):
        return self.acct

    def positions(self):
        return list(self.pos.values())

    def orders(self, status="open", after=None):
        tops = list(self.orders_by_id.values())
        if status == "open":
            return [o for o in tops if o.is_open or any(leg.is_open for leg in o.legs)]
        return tops

    def order_by_client_id(self, coid):
        return next((o for o in self.orders_by_id.values() if o.client_order_id == coid), None)

    def submit_bracket(self, *, symbol, side, qty, limit_price, take_profit, stop_loss, tif, client_order_id):
        if self.order_by_client_id(client_order_id):
            raise DuplicateClientOrderId("client_order_id must be unique")
        self.submits += 1
        now = dt.datetime.now(tz=NY)
        exit_side = "sell" if side == "buy" else "buy"
        legs = [
            BrokerOrder(str(next(self._ids)), f"leg-tp-{client_order_id}", symbol, exit_side, "limit", "held", qty, 0, None, take_profit, None, "bracket", now, None),
            BrokerOrder(str(next(self._ids)), f"leg-sl-{client_order_id}", symbol, exit_side, "stop", "held", qty, 0, None, None, stop_loss, "bracket", now, None),
        ]
        o = BrokerOrder(str(next(self._ids)), client_order_id, symbol, side, "limit", "new", qty, 0, None, limit_price, None, "bracket", now, None, legs)
        self.orders_by_id[o.id] = o
        if self.fail_after_submit_once:
            self.fail_after_submit_once = False
            raise TimeoutError("network timeout after the order landed")
        return o

    marks: dict = {}
    reject_buys = False

    def submit_market(self, *, symbol, side, qty, client_order_id):
        """Fills immediately at the position's mark (or self.marks); applies side and qty."""
        if self.reject_buys and side == "buy":
            raise DuplicateClientOrderId("403 insufficient buying power")
        now = dt.datetime.now(tz=NY)
        p = self.pos.get(symbol)
        px = (p.current_price if p else None) or self.marks.get(symbol, 100.0)
        signed = qty if side == "buy" else -qty
        new_qty = (p.qty if p else 0.0) + signed
        if abs(new_qty) < 1e-9:
            self.pos.pop(symbol, None)
        else:
            self.pos[symbol] = BrokerPosition(symbol, new_qty, p.avg_entry_price if p else px, px)
        o = BrokerOrder(str(next(self._ids)), client_order_id, symbol, side, "market", "filled", qty, qty, px, None, None, "simple", now, now)
        self.orders_by_id[o.id] = o
        return o

    def cancel(self, order_id):
        """Alpaca semantics: cancelling any member of a bracket cancels the rest of the group."""
        for o in self.orders_by_id.values():
            if o.id == order_id or any(leg.id == order_id for leg in o.legs):
                if o.is_open:
                    o.status = "canceled"
                for leg in o.legs:
                    if leg.is_open:
                        leg.status = "canceled"

    def replace_stop(self, order_id, stop_price):
        for o in self.orders_by_id.values():
            for leg in o.legs:
                if leg.id == order_id:
                    leg.stop_price = stop_price
                    return leg
        raise KeyError(order_id)

    def asset(self, symbol):
        return AssetInfo(symbol, True, True, True, True)

    sessions_list: list = []

    def sessions(self, start, end):
        return [x for x in self.sessions_list if start <= x.day <= end]

    def equity_history(self):
        return []

    # -- test helpers --------------------------------------------------------
    def fill_entry(self, order_id: str, price: float, when: dt.datetime | None = None) -> None:
        o = self.orders_by_id[order_id]
        when = when or dt.datetime.now(tz=NY)
        o.status, o.filled_qty, o.filled_avg_price, o.filled_at = "filled", o.qty, price, when
        for leg in o.legs:
            leg.status = "new"
        sign = 1 if o.side == "buy" else -1
        self.pos[o.symbol] = BrokerPosition(o.symbol, sign * o.qty, price, price)

    def fill_leg(self, order_id: str, kind: str, price: float, when: dt.datetime | None = None) -> None:
        o = self.orders_by_id[order_id]
        when = when or dt.datetime.now(tz=NY)
        for leg in o.legs:
            if (kind == "tp" and leg.type == "limit") or (kind == "sl" and leg.type == "stop"):
                leg.status, leg.filled_qty, leg.filled_avg_price, leg.filled_at = "filled", leg.qty, price, when
            else:
                leg.status = "canceled"
        self.pos.pop(o.symbol, None)
