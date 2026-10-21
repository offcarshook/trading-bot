"""Daily multi-strategy PAPER portfolio.

Once per trading day, shortly after the open:
  1. load adjusted RTH daily bars through YESTERDAY's close (SIP history)
  2. run each sleeve's research strategy (single source of truth with the
     backtests) and read its latest decision-date target weights
  3. combine sleeves (weight x sleeve targets), cap total gross exposure
  4. compare with current positions and send market orders (sells first)
     for any symbol whose weight differs by more than the rebalance band

This mirrors the research engine's timing: decision at close t, execution
at the next open (here: a few minutes after it). Long-only, no stops - the
same as the simulated strategies. A drawdown kill-switch liquidates the
portfolio. Orders carry a ``dpf-`` client_order_id so one run per day is
enforced (a second run the same day is a no-op unless forced).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .execution import BrokerPosition, make_client_order_id, parse_client_order_id
from .research.base import ResearchData, load_all_strategies
from .research.costs import CostModel
from .timeutils import NY, ny_dt

log = logging.getLogger(__name__)
REQUIRED_KEYS = {"profile", "sleeves", "gross_cap", "rebalance_band", "max_drawdown_kill", "drawdown_reset_date",
                 "history_calendar_days", "client_order_id_prefix", "window_start", "window_end"}
HARD_GROSS_CAP = 2.0


@dataclass(frozen=True)
class Sleeve:
    strategy: str
    weight: float
    params: dict


@dataclass(frozen=True)
class PortfolioConfig:
    profile: str
    sleeves: tuple[Sleeve, ...]
    gross_cap: float
    rebalance_band: float
    max_drawdown_kill: float | None
    drawdown_reset_date: str | None
    history_calendar_days: int
    client_order_id_prefix: str
    window_start: str
    window_end: str


def load_portfolio_config(path: str | Path) -> PortfolioConfig:
    raw = yaml.safe_load(Path(path).read_text())
    missing, unknown = REQUIRED_KEYS - set(raw), set(raw) - REQUIRED_KEYS
    if missing or unknown:
        raise ValueError(f"daily portfolio config: missing {sorted(missing)} unknown {sorted(unknown)}")
    sleeves = tuple(Sleeve(s["strategy"], float(s["weight"]), dict(s["params"])) for s in raw["sleeves"])
    kill = raw["max_drawdown_kill"]
    cfg = PortfolioConfig(raw["profile"], sleeves, float(raw["gross_cap"]), float(raw["rebalance_band"]), None if kill is None else float(kill),
                          raw["drawdown_reset_date"], int(raw["history_calendar_days"]), str(raw["client_order_id_prefix"]),
                          str(raw["window_start"]), str(raw["window_end"]))
    if not 0 < cfg.gross_cap <= HARD_GROSS_CAP:
        raise ValueError(f"gross_cap must be in (0, {HARD_GROSS_CAP}] - Alpaca rejects orders beyond ~2x overnight buying power")
    if cfg.max_drawdown_kill is not None and not 0 < cfg.max_drawdown_kill <= 1.0:
        raise ValueError("max_drawdown_kill must be in (0, 1] or null (disabled)")
    if any(s.weight < 0 for s in sleeves):
        raise ValueError("sleeve weights must be >= 0 (long-only portfolio)")
    specs = load_all_strategies()
    for s in sleeves:
        if s.strategy not in specs:
            raise ValueError(f"unknown strategy {s.strategy}")
        bad = set(s.params) - set(specs[s.strategy].param_grid)
        if bad:
            raise ValueError(f"{s.strategy}: unknown params {sorted(bad)}")
    return cfg


def required_symbols(cfg: PortfolioConfig) -> list[str]:
    specs = load_all_strategies()
    syms: set[str] = set()
    for s in cfg.sleeves:
        syms |= set(specs[s.strategy].symbols)
    return sorted(syms)


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #


@dataclass
class TargetResult:
    decision_date: str
    targets: dict[str, float]
    gross_before_cap: float
    scale: float
    sleeves: dict[str, dict[str, float]] = field(default_factory=dict)


def latest_weights(weights: pd.DataFrame) -> tuple[pd.Timestamp, pd.Series]:
    """Last decision row (rows that are entirely NaN mean 'hold' and are skipped)."""
    decided = weights.dropna(how="all")
    if decided.empty:
        return weights.index[-1], pd.Series(0.0, index=weights.columns)
    return decided.index[-1], decided.iloc[-1].fillna(0.0)


def compute_targets(data: ResearchData, cfg: PortfolioConfig, costs: CostModel | None = None) -> TargetResult:
    costs = costs or CostModel()
    specs = load_all_strategies()
    combined: dict[str, float] = {}
    sleeves_out: dict[str, dict[str, float]] = {}
    last_dates = []
    for s in cfg.sleeves:
        res = specs[s.strategy].run(data, s.params, costs)
        if res.weights is None:
            raise ValueError(f"{s.strategy} is not a weight strategy")
        d, w = latest_weights(res.weights)
        last_dates.append(d)
        w = w[w.abs() > 1e-9]
        sleeves_out[s.strategy] = {k: float(v) for k, v in w.items()}
        for sym, val in w.items():
            if val < 0:
                raise ValueError(f"{s.strategy} produced a short weight for {sym}; portfolio is long-only")
            combined[sym] = combined.get(sym, 0.0) + s.weight * float(val)
    gross = sum(abs(v) for v in combined.values())
    scale = min(1.0, cfg.gross_cap / gross) if gross > 0 else 1.0
    targets = {k: v * scale for k, v in combined.items()}
    return TargetResult(str(max(last_dates).date()) if last_dates else "", targets, gross, scale, sleeves_out)


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    side: str
    qty: int
    current_weight: float
    target_weight: float


def plan_orders(targets: dict[str, float], positions: list[BrokerPosition], prices: dict[str, float], equity: float,
                band: float) -> list[PlannedOrder]:
    held = {p.symbol: p for p in positions if p.qty != 0}
    orders: list[PlannedOrder] = []
    for sym in sorted(set(targets) | set(held)):
        px = prices.get(sym)
        if not px or px <= 0 or not math.isfinite(px):
            log.warning("no price - skipping", extra={"symbol": sym})
            continue
        qty_now = held[sym].qty if sym in held else 0.0
        if qty_now < 0:
            orders.append(PlannedOrder(sym, "buy", int(math.ceil(-qty_now)), qty_now * px / equity, 0.0))  # never short
            continue
        cur_w = qty_now * px / equity
        tgt_w = targets.get(sym, 0.0)
        exiting = tgt_w <= 1e-9 and qty_now > 0
        if not exiting and abs(tgt_w - cur_w) < band:
            continue
        tgt_qty = 0 if exiting else int(math.floor(tgt_w * equity / px))
        delta = tgt_qty - qty_now
        if exiting:
            delta = -qty_now
        if abs(delta) < 1:
            continue
        side = "buy" if delta > 0 else "sell"
        qty = int(abs(delta)) if side == "buy" else (int(abs(delta)) if float(abs(delta)).is_integer() else abs(delta))
        orders.append(PlannedOrder(sym, side, qty, cur_w, tgt_w))
    return sorted(orders, key=lambda o: 0 if o.side == "sell" else 1)  # free buying power first


def drawdown(equity: float, history: list[tuple[dt.date, float]], reset: str | None) -> float:
    start = dt.date.fromisoformat(reset) if reset else None
    pool = [e for d, e in history if e > 0 and (start is None or d >= start)] + [equity]
    peak = max(pool)
    return (peak - equity) / peak if peak > 0 else 0.0


def already_rebalanced_today(orders: list, prefix: str, today: dt.date) -> bool:
    tag = f"{today:%y%m%d}"
    for o in orders:
        meta = parse_client_order_id(o.client_order_id)
        if meta and meta["prefix"] == prefix and meta["day"] == tag and o.status not in ("canceled", "rejected", "expired"):
            return True
    return False


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def run_rebalance(cfg: PortfolioConfig, broker: Any, data: ResearchData, prices: dict[str, float], now: dt.datetime,
                  dry_run: bool, force: bool, out_dir: Path) -> dict:
    today = now.astimezone(NY).date()
    acct = broker.account()
    equity = float(acct.equity)
    report: dict[str, Any] = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(), "ny_time": now.isoformat(), "profile": cfg.profile,
                              "equity": equity, "dry_run": dry_run}
    dd = drawdown(equity, broker.equity_history(), cfg.drawdown_reset_date)
    report["drawdown"] = dd
    positions = broker.positions()
    todays_orders = broker.orders("all", after=ny_dt(today, dt.time(0)))
    if cfg.max_drawdown_kill is not None and dd >= cfg.max_drawdown_kill:
        targets = TargetResult("", {}, 0.0, 1.0)
        report["kill_switch"] = True
        log.critical("drawdown kill-switch: liquidating daily portfolio", extra={"drawdown": dd})
    else:
        if already_rebalanced_today(todays_orders, cfg.client_order_id_prefix, today) and not force:
            report["skipped"] = "already rebalanced today"
            _write(out_dir, today, report)
            return report
        targets = compute_targets(data, cfg)
    plan = plan_orders(targets.targets, positions, prices, equity, cfg.rebalance_band)
    report.update({"decision_date": targets.decision_date, "targets": targets.targets, "gross_before_cap": targets.gross_before_cap,
                   "scale": targets.scale, "sleeves": targets.sleeves,
                   "positions_before": {p.symbol: p.qty for p in positions},
                   "orders": [o.__dict__ for o in plan]})
    sent = []
    stamp = now.astimezone(NY).strftime("%H%M%S")
    for i, o in enumerate(plan):
        coid = make_client_order_id(cfg.client_order_id_prefix, today, o.symbol, f"r{stamp}{i:02d}", "d")
        if dry_run:
            sent.append({"symbol": o.symbol, "side": o.side, "qty": o.qty, "dry_run": True})
            continue
        res = broker.submit_market(symbol=o.symbol, side=o.side, qty=o.qty, client_order_id=coid)
        sent.append({"symbol": o.symbol, "side": o.side, "qty": o.qty, "id": res.id, "status": res.status, "coid": coid})
        log.info("rebalance order", extra=sent[-1])
    report["sent"] = sent
    _write(out_dir, today, report)
    return report


def _write(out_dir: Path, today: dt.date, report: dict) -> None:
    d = out_dir / today.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "daily_portfolio.json").write_text(json.dumps(report, indent=1, default=str))
