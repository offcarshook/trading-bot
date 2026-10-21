"""Transaction-cost and financing model.

cost of a trade (fraction of equity) =
    |traded notional| * (half_spread_bps + slippage_bps) * cost_multiplier / 1e4
  + sold notional * sec_fee_rate
financing per day (fraction of equity) =
    max(0, gross_long - 1) * margin_rate / 252          (borrowed cash)
  + short_notional * short_borrow_rate / 252
Cash earns ``cash_rate`` (default 0 - conservative; Alpaca paper pays nothing).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .universe import half_spread_bps

TRADING_DAYS = 252


@dataclass(frozen=True)
class CostModel:
    open_slippage_bps: float = 1.0  # market-on-open / marketable order at the open
    stop_slippage_bps: float = 3.0  # stop orders / breakouts (adverse selection)
    close_slippage_bps: float = 1.0  # market-on-close / end-of-day exit
    sec_fee_rate: float = 0.0000278  # $ per $ sold (Section 31). CHECK current rate.
    margin_rate: float = 0.07  # annual, on borrowed cash (leverage > 1)
    short_borrow_rate: float = 0.005  # annual, easy-to-borrow ETFs
    cash_rate: float = 0.0
    cost_multiplier: float = 1.0  # stress-test knob (e.g. 2.0 = double all frictions)

    def stressed(self, mult: float) -> "CostModel":
        return replace(self, cost_multiplier=self.cost_multiplier * mult)

    def trade_cost_bps(self, symbol: str, kind: str = "open") -> float:
        slip = {"open": self.open_slippage_bps, "stop": self.stop_slippage_bps, "close": self.close_slippage_bps}[kind]
        return (half_spread_bps(symbol) + slip) * self.cost_multiplier

    def trade_cost(self, symbol: str, notional_frac: float, sold_frac: float, kind: str = "open") -> float:
        return abs(notional_frac) * self.trade_cost_bps(symbol, kind) / 1e4 + abs(sold_frac) * self.sec_fee_rate * self.cost_multiplier

    def daily_financing(self, gross_long: float, short: float, net_cash: float) -> float:
        """Positive number = cost. ``net_cash`` = 1 - net invested (negative = borrowed)."""
        borrowed = max(0.0, gross_long - 1.0)
        cost = borrowed * self.margin_rate / TRADING_DAYS + abs(short) * self.short_borrow_rate / TRADING_DAYS
        if net_cash > 0:
            cost -= net_cash * self.cash_rate / TRADING_DAYS
        return cost
