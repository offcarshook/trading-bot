"""Optional event-driven backtest / walk-forward evaluation.

Uses the SAME functions as live trading: build_frames, find_setups,
entry_window_open, pending_entry_action, select_setups and RiskEngine.approve.
Decisions happen at each 5m bar close; fills and exits are simulated on the
1-minute bars that follow (never on the bar that produced the signal).

Fill model (deliberately conservative):
  * limit entry fills only if price trades THROUGH the limit (configurable),
    at the limit or the better opening price on a gap;
  * if one 1m bar touches both stop and target the STOP wins;
  * the bar that fills the entry can stop the trade out but never take profit;
  * stops/flatten pay slippage; sells pay SEC + FINRA TAF; commission optional.
It is still a model: queue position, partial fills, IEX-vs-SIP price
differences and latency are not captured. Treat results as rough diagnostics.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BotConfig, parse_hhmm
from .data import Quote, aggregate_session, daily_from_minutes
from .indicators import relative_volume
from .models import Direction, Setup, TradeRecord
from .portfolio import bucket_for, select_setups
from .reporting import compute_metrics, mae_mfe, write_summary
from .risk import AccountSnapshot, ApprovedOrder, Exposure, MarketCheck, RiskEngine, RiskState
from .strategy import EntryPlan, build_frames, build_prior, entry_window_open, find_setups, pending_entry_action, round_to_tick
from .timeutils import TradingSession, ny_dt, week_start

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Fill model (pure)
# --------------------------------------------------------------------------- #


def limit_fill_price(direction: Direction, limit: float, bar: tuple[float, float, float, float], trade_through: bool) -> float | None:
    o, h, l, _c = bar
    if direction is Direction.LONG:
        hit = l < limit if trade_through else l <= limit
        return min(o, limit) if hit else None
    hit = h > limit if trade_through else h >= limit
    return max(o, limit) if hit else None


def exit_on_bar(direction: Direction, stop: float, target: float | None, bar: tuple[float, float, float, float], stop_slip_bps: float, allow_target: bool) -> tuple[float, str] | None:
    """Stop first (conservative), including gaps through the stop."""
    o, h, l, _c = bar
    slip = stop_slip_bps / 1e4
    if direction is Direction.LONG:
        if o <= stop:
            return o * (1 - slip), "stop_loss"
        if l <= stop:
            return stop * (1 - slip), "stop_loss"
        if allow_target and target is not None and h > target:
            return max(o, target), "take_profit"
    else:
        if o >= stop:
            return o * (1 + slip), "stop_loss"
        if h >= stop:
            return stop * (1 + slip), "stop_loss"
        if allow_target and target is not None and l < target:
            return min(o, target), "take_profit"
    return None


def trade_fees(cfg: BotConfig, direction: Direction, qty: float, entry: float, exit_px: float) -> float:
    bt = cfg.backtest
    sell_px = exit_px if direction is Direction.LONG else entry
    taf = min(bt.taf_per_share * qty, bt.taf_max_per_trade)
    return round(bt.commission_per_share * qty * 2 + bt.sec_fee_rate * sell_px * qty + taf, 4)


# --------------------------------------------------------------------------- #
# Simulator state
# --------------------------------------------------------------------------- #


@dataclass
class Lot:
    qty: int
    target: float


@dataclass
class SimPosition:
    plan: EntryPlan
    direction: Direction
    lots: list[Lot]
    stop: float
    initial_stop: float
    entry_price: float | None = None
    entry_time: dt.datetime | None = None
    placed_bars: int = 0
    exits: list[tuple[int, float, dt.datetime, str]] = field(default_factory=list)
    qty0: int = 0

    @property
    def filled(self) -> bool:
        return self.entry_price is not None

    @property
    def open_qty(self) -> int:
        return sum(lot.qty for lot in self.lots)


@dataclass
class BacktestResult:
    trades: list[TradeRecord]
    equity: pd.Series
    signals: int
    days: list[dt.date]


class Simulator:
    def __init__(self, cfg: BotConfig) -> None:
        self.cfg = cfg
        self.risk = RiskEngine(cfg)
        self.cash = cfg.backtest.initial_equity
        self.positions: dict[str, SimPosition] = {}
        self.trades: list[TradeRecord] = []
        self.equity_points: list[tuple[dt.datetime, float]] = []
        self.peak = self.cash
        self.day_start_equity = self.cash
        self.week_start_equity = self.cash
        self.used_setups: set[str] = set()
        self.signals = 0

    def equity(self, marks: dict[str, float]) -> float:
        eq = self.cash
        for sym, p in self.positions.items():
            if p.filled:
                eq += p.direction.sign * (marks.get(sym, p.entry_price) - p.entry_price) * p.open_qty
        return eq

    def _close_lots(self, sym: str, p: SimPosition, lots: list[Lot], price: float, when: dt.datetime, reason: str) -> None:
        for lot in lots:
            p.exits.append((lot.qty, price, when, reason))
            self.cash += p.direction.sign * (price - p.entry_price) * lot.qty
            p.lots.remove(lot)
        if not p.lots:
            self._finalize(sym, p)

    def _finalize(self, sym: str, p: SimPosition) -> None:
        qty = sum(q for q, *_ in p.exits)
        exit_px = sum(q * px for q, px, *_ in p.exits) / qty
        gross = p.direction.sign * (exit_px - p.entry_price) * qty
        fees = trade_fees(self.cfg, p.direction, qty, p.entry_price, exit_px)
        self.cash -= fees
        risk = abs(p.entry_price - p.initial_stop) * qty
        reasons = "+".join(sorted({r for *_, r in p.exits}))
        self.trades.append(
            TradeRecord(
                trade_id=f"{p.entry_time:%y%m%d}-{sym}-{p.plan.setup_id}", symbol=sym, direction=p.direction.value, setup_tag=p.plan.tag,
                entry_time=p.entry_time, entry_price=round(p.entry_price, 4), qty=qty, stop_price=p.initial_stop, target_price=p.plan.target,
                exit_time=max(t for *_, t, _r in p.exits), exit_price=round(exit_px, 4), exit_reason=reasons, pnl=round(gross, 2),
                fees=fees, r_multiple=round((gross - fees) / risk, 3) if risk > 0 else math.nan, score=p.plan.score,
            )
        )
        del self.positions[sym]

    def on_minute(self, sym: str, ts: dt.datetime, bar: tuple[float, float, float, float]) -> None:
        p = self.positions.get(sym)
        if p is None:
            return
        bt = self.cfg.backtest
        if not p.filled:
            px = limit_fill_price(p.direction, p.plan.entry, bar, bt.fill_requires_trade_through)
            if px is None:
                return
            p.entry_price = px * (1 + p.direction.sign * bt.entry_slippage_bps / 1e4)
            p.entry_time = ts
            hit = exit_on_bar(p.direction, p.stop, None, bar, bt.stop_slippage_bps, allow_target=False)
            if hit:
                self._close_lots(sym, p, list(p.lots), hit[0], ts, hit[1])
            return
        for lot in sorted(p.lots, key=lambda l: abs(l.target - p.entry_price)):
            hit = exit_on_bar(p.direction, p.stop, lot.target, bar, bt.stop_slippage_bps, allow_target=True)
            if hit is None:
                continue
            if hit[1] == "stop_loss":
                self._close_lots(sym, p, list(p.lots), hit[0], ts, hit[1])
                return
            self._close_lots(sym, p, [lot], hit[0], ts, hit[1])
            if sym not in self.positions:
                return

    def flatten(self, sym: str, price: float, when: dt.datetime, reason: str) -> None:
        p = self.positions.get(sym)
        if p is None:
            return
        if not p.filled:
            del self.positions[sym]
            return
        slip = self.cfg.backtest.market_slippage_bps / 1e4
        px = price * (1 - slip) if p.direction is Direction.LONG else price * (1 + slip)
        self._close_lots(sym, p, list(p.lots), px, when, reason)

    def exposures(self) -> list[Exposure]:
        out = []
        for sym, p in self.positions.items():
            entry = p.entry_price if p.filled else p.plan.entry
            out.append(Exposure(sym, p.direction, p.open_qty, entry, p.stop, pending=not p.filled))
        return out

    def risk_state(self, now: dt.datetime, equity: float) -> RiskState:
        today = now.date()
        todays = [t for t in self.trades if t.entry_time.date() == today]
        closed = sorted(todays, key=lambda t: t.exit_time, reverse=True)
        consec = 0
        for t in closed:
            if t.pnl - t.fees < 0:
                consec += 1
            else:
                break
        losses = [t for t in closed if t.pnl - t.fees < 0]
        working = sum(1 for p in self.positions.values() if p.plan.placed_at.date() == today and not p.filled)
        filled_open = sum(1 for p in self.positions.values() if p.filled and p.entry_time.date() == today)
        return RiskState(
            now=now, day_pnl_pct=(equity / self.day_start_equity - 1) * 100, week_pnl_pct=(equity / self.week_start_equity - 1) * 100,
            drawdown_pct=(self.peak - equity) / self.peak * 100, trades_today=len(todays) + working + filled_open,
            consecutive_losses=consec, last_loss_exit=losses[0].exit_time if losses else None,
        )

    def place(self, setup: Setup, order: ApprovedOrder, placed_at: dt.datetime) -> None:
        ex = self.cfg.execution
        lots = [Lot(order.qty, order.target)]
        pt = ex.partial_take_profit
        if pt.enabled:
            qa = math.floor(order.qty * pt.fraction)
            tp_a = round_to_tick(order.entry + order.direction.sign * pt.at_r * setup.risk_per_share, ex.tick_size, "down" if order.direction is Direction.LONG else "up")
            if qa >= 1 and order.qty - qa >= 1:
                lots = [Lot(qa, tp_a), Lot(order.qty - qa, order.target)]
        plan = dataclasses.replace(EntryPlan.from_setup(setup), placed_at=placed_at)
        self.positions[setup.symbol] = SimPosition(plan, order.direction, lots, order.stop, order.stop, qty0=order.qty)
        self.used_setups.add(setup.setup_id)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def run_backtest(
    cfg: BotConfig,
    minutes: dict[str, pd.DataFrame],
    sessions: list[TradingSession],
    start: dt.date,
    end: dt.date,
    events: dict[dt.date, str] | None = None,
) -> BacktestResult:
    events = events or {}
    sim = Simulator(cfg)
    days = [s for s in sessions if start <= s.day <= end]
    sym_list = list(cfg.symbols)
    last_week = None
    for di, sess in enumerate(days):
        hist = [s for s in sessions if s.day <= sess.day]
        hist = [s for s in hist if s.day >= sess.day - dt.timedelta(days=cfg.data.history_days)]
        prior = {s: build_prior(minutes[s], hist[:-1], cfg) for s in sym_list}
        m_today = {s: minutes[s][(minutes[s].index >= ny_dt(sess.day, dt.time(0))) & (minutes[s].index < ny_dt(sess.day, dt.time(23, 59)))] for s in sym_list}
        marks = {s: (float(m_today[s]["close"].iloc[0]) if not m_today[s].empty else 0.0) for s in sym_list}
        eq = sim.equity(marks)
        sim.day_start_equity = eq
        wk = week_start(sess.day)
        if wk != last_week:
            sim.week_start_equity, last_week = eq, wk
        allowed = not ((sess.is_early_close and cfg.session.skip_early_close_days) or (cfg.session.skip_event_days and sess.day in events))
        flatten_at = min(ny_dt(sess.day, parse_hhmm(cfg.session.flatten_time)), sess.close - dt.timedelta(minutes=5))
        rth = {s: m_today[s][(m_today[s].index >= sess.open) & (m_today[s].index < sess.close)] for s in sym_list}
        full = {s: (aggregate_session(m_today[s], sess, 5), aggregate_session(m_today[s], sess, 60)) for s in sym_list}
        n_bars = int((sess.close - sess.open).total_seconds() // 300)
        for k in range(n_bars):
            bar_start = sess.open + dt.timedelta(minutes=5 * k)
            asof = bar_start + dt.timedelta(minutes=5)
            # 1) simulate fills/exits on the 1m bars of this bucket
            for s in sym_list:
                w = rth[s][(rth[s].index >= bar_start) & (rth[s].index < asof)]
                for ts, row in w.iterrows():
                    if ts >= flatten_at:
                        break
                    sim.on_minute(s, ts, (row.open, row.high, row.low, row.close))
                    marks[s] = float(row.close)
            eq = sim.equity(marks)
            sim.peak = max(sim.peak, eq)
            sim.equity_points.append((asof, eq))
            if asof > flatten_at:
                for s in list(sim.positions):
                    nxt = rth[s][rth[s].index >= flatten_at]
                    px = float(nxt["open"].iloc[0]) if not nxt.empty else marks[s]
                    sim.flatten(s, px, flatten_at, "flatten")
                break
            # 2) decisions at the bar close
            frames = {s: build_frames(s, m_today[s], hist, asof, cfg, delay_s=0, prior=prior[s], today_full=full[s]) for s in sym_list}
            for s, p in list(sim.positions.items()):
                if p.filled:
                    _break_even(sim, s, p, frames[s], cfg)
                    continue
                today5 = frames[s].bars5.iloc[frames[s].today_start :]
                after = today5[today5.index > p.plan.placed_at]
                if not after.empty and pending_entry_action(p.plan, after.iloc[-1], len(after), cfg):
                    del sim.positions[s]
            rstate = sim.risk_state(asof, eq)
            account = AccountSnapshot(eq, sim.day_start_equity, eq * 2)
            if sim.risk.status(account, rstate).flatten:
                for s in list(sim.positions):
                    sim.flatten(s, marks[s], asof, "risk_halt")
                continue
            ok, _ = entry_window_open(asof, sess, cfg)
            if not (ok and allowed):
                continue
            cands = []
            for s in sym_list:
                res = find_setups(frames[s], cfg)
                sim.signals += len(res.records)
                best = next((x for x in res.setups if x.setup_id not in sim.used_setups), None)
                if best:
                    cands.append(best)
            if not cands:
                continue
            selections, _ = select_setups(cands, sim.exposures(), cfg)
            for sel in selections:
                st = sel.setup
                fr = frames[st.symbol]
                vol = fr.bars5["volume"].to_numpy(float)
                rv = relative_volume(vol)
                px = float(fr.bars5["close"].iloc[-1])
                half = cfg.execution.tick_size / 2
                mk = MarketCheck(asof, sess.close, Quote(px - half, px + half, asof), float(vol[-1]),
                                 float(rv[-1]) if np.isfinite(rv[-1]) else None, 0.0)
                b = bucket_for(st.symbol, cfg)
                decision = sim.risk.approve(st, account, rstate, sim.exposures(), mk, b.symbols, b.max_open_risk_multiple, sel.risk_fraction)
                if isinstance(decision, ApprovedOrder):
                    sim.place(st, decision, bar_start)
        for s in list(sim.positions):  # safety: never carry overnight
            sim.flatten(s, marks[s], sess.close, "flatten")
        if di % 20 == 0:
            log.info("backtest progress", extra={"day": sess.day.isoformat(), "equity": round(sim.equity(marks), 2), "trades": len(sim.trades)})

    trades = [dataclasses.replace(t, **dict(zip(("mae_r", "mfe_r"), mae_mfe(t, minutes[t.symbol])))) for t in sim.trades]
    equity = pd.Series({t: v for t, v in sim.equity_points}, dtype=float)
    return BacktestResult(trades, equity, sim.signals, [s.day for s in days])


def _break_even(sim: Simulator, sym: str, p: SimPosition, fr, cfg: BotConfig) -> None:
    be = cfg.execution.break_even
    if not be.enabled or p.entry_time is None:
        return
    r = abs(p.entry_price - p.initial_stop)
    since = fr.bars5[fr.bars5.index >= p.entry_time.replace(second=0, microsecond=0)]
    if since.empty or r <= 0:
        return
    long = p.direction is Direction.LONG
    fav = since["high"].max() - p.entry_price if long else p.entry_price - since["low"].min()
    if fav >= be.trigger_r * r:
        new = p.entry_price + be.offset if long else p.entry_price - be.offset
        p.stop = max(p.stop, new) if long else min(p.stop, new)


# --------------------------------------------------------------------------- #
# Reports: held-out split + walk-forward folds
# --------------------------------------------------------------------------- #


def split_days(days: list[dt.date], holdout_fraction: float) -> tuple[list[dt.date], list[dt.date]]:
    n_oos = int(round(len(days) * holdout_fraction))
    return (days[: len(days) - n_oos], days[len(days) - n_oos :]) if n_oos else (days, [])


def fold_metrics(trades: list[TradeRecord], equity: pd.Series, days: list[dt.date]) -> dict:
    ds = set(days)
    t = [x for x in trades if x.entry_time.date() in ds]
    eq = equity[[ts.date() in ds for ts in equity.index]] if len(equity) else equity
    return compute_metrics(t, eq)


def report_backtest(cfg: BotConfig, result: BacktestResult, minutes: dict[str, pd.DataFrame], sessions: list[TradingSession], out_dir: Path) -> Path:
    ins, oos = split_days(result.days, cfg.backtest.holdout_fraction)
    sections = {
        "Held-out split (tune ONLY on in-sample; look at out-of-sample once)": _kv_table(
            {"in_sample_days": f"{ins[0]} -> {ins[-1]} ({len(ins)})" if ins else "none",
             "out_of_sample_days": f"{oos[0]} -> {oos[-1]} ({len(oos)})" if oos else "none"}
        ),
        "In-sample metrics": _kv_table(fold_metrics(result.trades, result.equity, ins)),
        "Out-of-sample metrics": _kv_table(fold_metrics(result.trades, result.equity, oos)) if oos else "_no hold-out_",
        "Cost model": _kv_table({k: getattr(cfg.backtest, k) for k in ("entry_slippage_bps", "stop_slippage_bps", "market_slippage_bps", "commission_per_share", "sec_fee_rate", "taf_per_share", "fill_requires_trade_through")}),
    }
    wf = cfg.backtest.walk_forward
    if wf.enabled and wf.folds > 1:
        chunks = np.array_split(np.array(result.days, dtype=object), wf.folds)
        rows = []
        for i, c in enumerate(chunks):
            m = fold_metrics(result.trades, result.equity, list(c))
            rows.append({"fold": i + 1, "from": c[0], "to": c[-1], **{k: m[k] for k in ("trades", "win_rate", "expectancy_r", "profit_factor", "max_drawdown_pct")}})
        sections["Walk-forward folds (fixed parameters, sequential)"] = _rows_table(rows)
    bench_sym = cfg.reporting.benchmark_symbol
    bench = None
    if bench_sym in minutes:
        daily = daily_from_minutes(minutes[bench_sym], [s for s in sessions if s.day in set(result.days)])
        if not daily.empty:
            bench = pd.Series(daily["close"].to_numpy(), index=[ny_dt(d, dt.time(16)) for d in daily.index])
    daily_eq = result.equity.groupby([ts.date() for ts in result.equity.index]).last() if len(result.equity) else result.equity
    if len(daily_eq):
        daily_eq.index = [ny_dt(d, dt.time(16)) for d in daily_eq.index]
    return write_summary(out_dir, result.trades, daily_eq, bench, f"Backtest {result.days[0]} -> {result.days[-1]} ({', '.join(cfg.symbols)})", sections)


def _kv_table(d: dict) -> str:
    return "\n".join(["| key | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in d.items()])


def _rows_table(rows: list[dict]) -> str:
    if not rows:
        return "_none_"
    cols = list(rows[0])
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows])
