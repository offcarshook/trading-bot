"""Causal, cost-aware backtest engines.

1) ``run_weights`` - daily target-weight strategies.
   Target weights ``W`` are indexed by DECISION date d (computed with data up to
   and including the close of d). They are executed at the OPEN of the next
   session. Day-by-day accounting for session i:
     overnight:  held weights earn  open_i / close_{i-1} - 1   (gap risk included)
     rebalance:  trade to target at open_i, paying spread + slippage + fees
     intraday:   new weights earn   close_i / open_i - 1
     financing:  margin interest on borrowed cash, borrow fee on shorts
   Weights drift with prices between rebalances; an optional no-trade band
   suppresses tiny rebalances.

2) ``run_trades`` - intraday trade lists (flat overnight). Each trade carries
   its own entry/exit prices and size (notional / equity); costs are charged
   on both sides using the order-type-specific slippage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ResearchData, StrategyResult
from .costs import CostModel


def run_weights(
    data: ResearchData,
    weights: pd.DataFrame,
    costs: CostModel,
    *,
    band: float = 0.0,
    entry_kind: str = "open",
) -> StrategyResult:
    syms = [s for s in weights.columns if s in data.daily]
    if not syms:
        raise ValueError("weights reference no known symbols")
    O = data.panel("open", syms)
    C = data.panel("close", syms)
    dates = O.index.union(C.index)
    O, C = O.reindex(dates), C.reindex(dates)
    # A row that is entirely NaN means "no decision today": hold the drifted
    # position (no trade). A row with numbers is a target; NaN cells in it = 0.
    W_raw = weights[syms].reindex(dates)
    hold_row = W_raw.isna().all(axis=1).to_numpy()
    W = W_raw.ffill().fillna(0.0)  # for reporting / null tests
    o, c, w_target_by_decision = O.to_numpy(float), C.to_numpy(float), W_raw.fillna(0.0).to_numpy(float)
    n, k = o.shape
    cost_bps = np.array([costs.trade_cost_bps(s, entry_kind) for s in syms]) / 1e4

    ret = np.zeros(n)
    gross = np.zeros(n)
    expo = np.zeros(n)
    turn = np.zeros(n)
    cost_arr = np.zeros(n)
    trades = 0
    w_hold = np.zeros(k)
    for i in range(1, n):
        prev_c = c[i - 1]
        tradable = np.isfinite(o[i]) & np.isfinite(c[i]) & np.isfinite(prev_c)
        # overnight leg with held weights (missing prices -> no move, cannot trade)
        r_on = np.where(tradable, o[i] / np.where(tradable, prev_c, 1.0) - 1.0, 0.0)
        port_on = float(np.dot(w_hold, r_on))
        denom = 1.0 + port_on
        w_after_gap = w_hold * (1.0 + r_on) / denom if denom > 0 else w_hold * 0.0
        if hold_row[i - 1]:
            target = w_after_gap.copy()
        else:
            target = np.where(tradable, w_target_by_decision[i - 1], w_after_gap)
        delta = target - w_after_gap
        if band > 0:
            small = np.abs(delta) < band
            target = np.where(small, w_after_gap, target)
            delta = np.where(small, 0.0, delta)
        traded = np.abs(delta)
        sold = np.where(delta < 0, -delta, 0.0)
        c_trade = float(np.dot(traded, cost_bps) + sold.sum() * costs.sec_fee_rate * costs.cost_multiplier)
        trades += int((traded > 1e-9).sum())
        r_id = np.where(tradable, c[i] / np.where(tradable, o[i], 1.0) - 1.0, 0.0)
        port_id = float(np.dot(target, r_id))
        long_gross = float(target[target > 0].sum())
        short = float(-target[target < 0].sum())
        fin = costs.daily_financing(long_gross, short, 1.0 - float(target.sum()))
        g = (1.0 + port_on) * (1.0 + port_id) - 1.0
        net = (1.0 + port_on) * (1.0 - c_trade) * (1.0 + port_id) - 1.0 - fin
        ret[i], gross[i], turn[i], cost_arr[i] = net, g, traded.sum(), c_trade + fin
        expo[i] = float(np.abs(target).sum())
        d2 = 1.0 + port_id
        w_hold = target * (1.0 + r_id) / d2 if d2 > 0 else target * 0.0
    idx = dates
    return StrategyResult(
        returns=pd.Series(ret, idx), gross_returns=pd.Series(gross, idx), exposure=pd.Series(expo, idx),
        turnover=pd.Series(turn, idx), costs=pd.Series(cost_arr, idx), n_trades=trades, weights=W,
    )


TRADE_COLUMNS = ["date", "symbol", "direction", "entry_time", "entry_price", "exit_time", "exit_price", "size", "entry_kind", "exit_kind", "exit_reason"]


def run_trades(trades: pd.DataFrame, dates: pd.DatetimeIndex, costs: CostModel, max_gross: float = 4.0) -> StrategyResult:
    """``trades`` columns: TRADE_COLUMNS. ``size`` = notional / equity at the start
    of the day (e.g. 1.0 = fully invested, 2.0 = 2x intraday leverage). Same-day
    trades compound additively on start-of-day equity (intraday only)."""
    idx = pd.DatetimeIndex(dates)
    ret = pd.Series(0.0, idx)
    gross = pd.Series(0.0, idx)
    expo = pd.Series(0.0, idx)
    turn = pd.Series(0.0, idx)
    cost_s = pd.Series(0.0, idx)
    if trades is None or trades.empty:
        return StrategyResult(ret, gross, expo, turn, cost_s, 0, trades=pd.DataFrame(columns=TRADE_COLUMNS))
    t = trades.copy()
    t["date"] = pd.to_datetime(t["date"]).dt.normalize()
    if (t["size"].abs() > max_gross + 1e-9).any():
        raise ValueError(f"trade size above max_gross={max_gross}")
    sign = np.where(t["direction"] == "long", 1.0, -1.0)
    raw = sign * (t["exit_price"] / t["entry_price"] - 1.0)
    entry_bps = np.array([costs.trade_cost_bps(s, k) for s, k in zip(t["symbol"], t["entry_kind"])]) / 1e4
    exit_bps = np.array([costs.trade_cost_bps(s, k) for s, k in zip(t["symbol"], t["exit_kind"])]) / 1e4
    size = t["size"].abs().to_numpy(float)
    exit_notional = size * (t["exit_price"] / t["entry_price"]).to_numpy(float)
    sold = np.where(sign > 0, exit_notional, size)
    tcost = size * entry_bps + exit_notional * exit_bps + sold * costs.sec_fee_rate * costs.cost_multiplier
    short_fin = np.where(sign < 0, size * costs.short_borrow_rate / 252, 0.0)
    t["gross_pnl"] = size * raw
    t["cost"] = tcost + short_fin
    t["net_pnl"] = t["gross_pnl"] - t["cost"]
    by_day = t.groupby("date")
    g = by_day["gross_pnl"].sum()
    cst = by_day["cost"].sum()
    gross = gross.add(g, fill_value=0.0).reindex(idx, fill_value=0.0)
    cost_s = cost_s.add(cst, fill_value=0.0).reindex(idx, fill_value=0.0)
    ret = gross - cost_s
    expo = expo.add(by_day["size"].apply(lambda s: s.abs().max()), fill_value=0.0).reindex(idx, fill_value=0.0)
    turn = turn.add(by_day["size"].apply(lambda s: 2 * s.abs().sum()), fill_value=0.0).reindex(idx, fill_value=0.0)
    return StrategyResult(ret, gross, expo, turn, cost_s, int(len(t)), trades=t)
