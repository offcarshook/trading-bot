"""Daily multi-strategy PAPER portfolio.

Once per trading day, shortly after the open:
  1. load adjusted RTH daily bars through YESTERDAY's close (SIP history)
  2. run each sleeve's research strategy (single source of truth with the
     backtests) and read its latest decision-date target weights
  3. combine sleeves (weight x sleeve targets), cap total gross exposure
  4. compare with current positions and send market orders (sells first)
     for any symbol whose weight differs by more than the rebalance band

Crypto sleeves (Alpaca spot pairs like BTC/USD) trade fractionally with GTC
market orders, paid fully in cash (crypto is not marginable), so configs that
contain crypto must keep gross_cap <= 1.0 - leverage then comes only from
leveraged ETFs. ``asset_class`` lets the stock run (after the NYSE open) and
the crypto run (just after the 00:00 UTC daily bar closes) manage only their
own symbols while sharing one set of portfolio targets.

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

from .execution import BrokerPosition, crypto_pair, make_client_order_id, parse_client_order_id
from .research.base import ResearchData, load_all_strategies
from .research.costs import CostModel
from .timeutils import NY

log = logging.getLogger(__name__)
REQUIRED_KEYS = {"profile", "sleeves", "gross_cap", "rebalance_band", "max_drawdown_kill", "drawdown_reset_date",
                 "history_calendar_days", "client_order_id_prefix", "window_start", "window_end"}
HARD_GROSS_CAP = 2.0
CRYPTO_GROSS_CAP = 1.0  # crypto must be paid in cash: no margin borrowing alongside it
CRYPTO_QTY_DECIMALS = 6
MIN_CRYPTO_NOTIONAL = 10.0  # USD; skip dust trades (exits always go through)
ASSET_CLASSES = ("all", "stocks", "crypto")


def is_crypto_symbol(symbol: str) -> bool:
    from .research.universe import INSTRUMENTS

    inst = INSTRUMENTS.get(crypto_pair(symbol))
    return "/" in symbol or bool(inst and inst.asset_class == "crypto")


def in_asset_class(symbol: str, asset_class: str) -> bool:
    if asset_class == "all":
        return True
    return is_crypto_symbol(symbol) == (asset_class == "crypto")


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
    reset = raw["drawdown_reset_date"]
    reset = None if reset is None else (reset.isoformat() if hasattr(reset, "isoformat") else str(reset))
    if reset:
        dt.date.fromisoformat(reset)
    cfg = PortfolioConfig(raw["profile"], sleeves, float(raw["gross_cap"]), float(raw["rebalance_band"]), None if kill is None else float(kill),
                          reset, int(raw["history_calendar_days"]), str(raw["client_order_id_prefix"]),
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
    if any(is_crypto_symbol(x) for x in required_symbols(cfg)) and cfg.gross_cap > CRYPTO_GROSS_CAP:
        raise ValueError(f"configs with crypto sleeves need gross_cap <= {CRYPTO_GROSS_CAP}: Alpaca crypto is cash-only, "
                         "so margin borrowing would leave no buying power for it (use leveraged ETFs for leverage)")
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
    from .research.strategies.common import MARGIN_BUFFER, margin_requirement

    used = sum(abs(v) * scale * margin_requirement(k) for k, v in combined.items())
    if used > 1.0 - MARGIN_BUFFER:  # e.g. 3x leveraged ETFs need 75% margin each
        scale *= (1.0 - MARGIN_BUFFER) / used
    targets = {k: v * scale for k, v in combined.items()}
    return TargetResult(str(max(last_dates).date()) if last_dates else "", targets, gross, scale, sleeves_out)


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    side: str
    qty: float  # whole shares for stocks, fractional for crypto
    current_weight: float
    target_weight: float


def _floor(x: float, decimals: int) -> float:
    f = 10 ** decimals
    return math.floor(x * f + 1e-9) / f


def _plan_crypto(sym: str, qty_now: float, px: float, tgt_w: float, equity: float, band: float) -> PlannedOrder | None:
    cur_w = qty_now * px / equity
    if tgt_w <= 1e-9:
        return PlannedOrder(sym, "sell", qty_now, cur_w, 0.0) if qty_now > 0 else None
    if abs(tgt_w - cur_w) < band:
        return None
    delta = tgt_w * equity / px - qty_now
    qty = _floor(abs(delta), CRYPTO_QTY_DECIMALS)
    if qty * px < MIN_CRYPTO_NOTIONAL:
        return None
    return PlannedOrder(sym, "buy" if delta > 0 else "sell", min(qty, qty_now) if delta < 0 else qty, cur_w, tgt_w)


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
        if is_crypto_symbol(sym):
            o = _plan_crypto(sym, max(qty_now, 0.0), px, targets.get(sym, 0.0), equity, band)
            if o:
                orders.append(o)
            continue
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


def open_orders_today(orders: list, prefix: str, today: dt.date) -> list:
    tag = f"{today:%y%m%d}"
    out = []
    for o in orders:
        meta = parse_client_order_id(o.client_order_id)
        if meta and meta["prefix"] == prefix and meta["day"] == tag and o.is_open:
            out.append(o)
    return out


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

FILL_TIMEOUT_S = 90.0
FILL_POLL_S = 3.0


def _wait_filled(broker: Any, coids: list[str], sleep, timeout: float = FILL_TIMEOUT_S) -> dict[str, str]:
    import time as _t

    status: dict[str, str] = {}
    deadline = _t.monotonic() + timeout
    pending = list(coids)
    while pending and _t.monotonic() < deadline:
        for c in list(pending):
            o = broker.order_by_client_id(c)
            status[c] = o.status if o else "unknown"
            if o is None or not o.is_open:
                pending.remove(c)
        if pending:
            sleep(FILL_POLL_S)
    return status


def run_rebalance(cfg: PortfolioConfig, broker: Any, data: ResearchData, prices: dict[str, float], now: dt.datetime,
                  dry_run: bool, force: bool, out_dir: Path, sleep=None, asset_class: str = "all") -> dict:
    """Idempotent by construction: the plan is always (targets - CURRENT positions),
    so re-running after a completed rebalance sends nothing. A run is skipped only
    while earlier orders from today are still working. Only symbols of
    ``asset_class`` are traded (targets are always computed for the whole book)."""
    import time as _t

    if asset_class not in ASSET_CLASSES:
        raise ValueError(f"asset_class must be one of {ASSET_CLASSES}")
    sleep = sleep or _t.sleep
    today = now.astimezone(NY).date()
    report: dict[str, Any] = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(), "ny_time": now.isoformat(), "profile": cfg.profile,
                              "asset_class": asset_class, "dry_run": dry_run, "errors": []}
    mine = lambda sym: in_asset_class(sym, asset_class)  # noqa: E731
    try:
        acct = broker.account()
        equity = float(acct.equity)
        report["equity"] = equity
        dd = drawdown(equity, broker.equity_history(), cfg.drawdown_reset_date)
        report["drawdown"] = dd
        all_positions = broker.positions()
        positions = [p for p in all_positions if mine(p.symbol)]
        prices = dict(prices)
        for p in positions:  # price every held symbol so leftovers from old configs can be exited
            if not prices.get(p.symbol) and p.current_price:
                prices[p.symbol] = float(p.current_price)
        working = [o for o in open_orders_today(broker.orders("open"), cfg.client_order_id_prefix, today) if mine(o.symbol)]
        if working and not force:
            report["skipped"] = f"{len(working)} rebalance order(s) from today still working"
            return report
        if cfg.max_drawdown_kill is not None and dd >= cfg.max_drawdown_kill:
            targets = TargetResult("", {}, 0.0, 1.0)
            report["kill_switch"] = True
            log.critical("drawdown kill-switch: liquidating everything", extra={"drawdown": dd})
        else:
            targets = compute_targets(data, cfg)
        plan = plan_orders({k: v for k, v in targets.targets.items() if mine(k)}, positions, prices, equity, cfg.rebalance_band)
        report.update({"decision_date": targets.decision_date, "targets": targets.targets, "gross_before_cap": targets.gross_before_cap,
                       "scale": targets.scale, "sleeves": targets.sleeves, "positions_before": {p.symbol: p.qty for p in positions},
                       "orders": [o.__dict__ for o in plan]})
        sent: list[dict] = []
        report["sent"] = sent
        stamp = now.astimezone(NY).strftime("%H%M%S")
        sells = [o for o in plan if o.side == "sell"]
        buys = sorted((o for o in plan if o.side == "buy"), key=lambda o: 0 if is_crypto_symbol(o.symbol) else 1)  # cash-only first

        def submit(i: int, o: PlannedOrder, qty) -> str | None:
            coid = make_client_order_id(cfg.client_order_id_prefix, today, o.symbol, f"r{stamp}{i:02d}", "d")
            if dry_run:
                sent.append({"symbol": o.symbol, "side": o.side, "qty": qty, "dry_run": True})
                return None
            try:
                res = broker.submit_market(symbol=o.symbol, side=o.side, qty=qty, client_order_id=coid)
                sent.append({"symbol": o.symbol, "side": o.side, "qty": qty, "id": res.id, "status": res.status, "coid": coid})
                log.info("rebalance order", extra=sent[-1])
                return coid
            except Exception as exc:  # noqa: BLE001 - one rejection must not abort the rest
                report["errors"].append({"symbol": o.symbol, "side": o.side, "qty": qty, "error": str(exc)[:300]})
                log.error("order rejected", extra=report["errors"][-1])
                return None

        sell_ids = [c for c in (submit(i, o, o.qty) for i, o in enumerate(sells)) if c]
        if sell_ids:
            report["sell_status"] = _wait_filled(broker, sell_ids, sleep)
        crypto_buys = [o for o in buys if is_crypto_symbol(o.symbol)]
        stock_buys = [o for o in buys if not is_crypto_symbol(o.symbol)]
        n = len(sells)
        for group, bp_field, label in ((crypto_buys, "non_marginable_buying_power", "crypto"), (stock_buys, "buying_power", "stock")):
            if not group:
                continue
            shrink = 1.0
            if not dry_run:  # re-read: earlier fills changed what is available
                acct = broker.account()
                bp = float(getattr(acct, bp_field, None) or 0)
                need = sum(o.qty * prices[o.symbol] for o in group)
                shrink = min(1.0, 0.98 * bp / need) if need > 0 and bp > 0 else 0.0
                report[f"{label}_buying_power"], report[f"{label}_buy_scale"] = bp, shrink
            for o in group:
                if is_crypto_symbol(o.symbol):
                    qty = _floor(o.qty * shrink, CRYPTO_QTY_DECIMALS)
                    ok = qty * prices[o.symbol] >= MIN_CRYPTO_NOTIONAL
                else:
                    qty = int(math.floor(o.qty * shrink))
                    ok = qty >= 1
                if ok:
                    submit(n, o, qty)
                n += 1
        return report
    except Exception as exc:  # noqa: BLE001
        report["errors"].append({"fatal": str(exc)[:500]})
        log.exception("rebalance failed")
        raise
    finally:
        _write(out_dir, today, report)


def simulate_portfolio(data: ResearchData, cfg: PortfolioConfig, costs: CostModel | None = None):
    """Backtest EXACTLY what the bot trades: combined, capped daily targets,
    the rebalance band, margin financing, next-open execution."""
    from .research.engine import run_weights

    costs = costs or CostModel()
    specs = load_all_strategies()
    frames = []
    for s in cfg.sleeves:
        w = specs[s.strategy].run(data, s.params, costs).weights.ffill().fillna(0.0)
        frames.append(w * s.weight)
    idx = frames[0].index
    for f in frames[1:]:
        idx = idx.union(f.index)
    cols = sorted(set().union(*[f.columns for f in frames]))
    # stock sleeves have no weekend rows: carry their last target across them
    # (a 0-filled weekend row would read as 'sell everything' on Monday)
    total = sum(f.reindex(index=idx).ffill().reindex(columns=cols).fillna(0.0) for f in frames)
    gross = total.abs().sum(axis=1)
    total = total.mul((cfg.gross_cap / gross).clip(upper=1.0).fillna(1.0), axis=0)
    from .research.strategies.common import cap_to_margin

    total = cap_to_margin(total)
    if data.crypto:  # one container so stocks and coins share the cash
        data = ResearchData({**data.daily, **data.crypto}, data.intraday, dict(data.meta, view="mixed"))
    return run_weights(data, total, costs, band=cfg.rebalance_band)


def _write(out_dir: Path, today: dt.date, report: dict) -> None:
    d = out_dir / today.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "daily_portfolio.json").write_text(json.dumps(report, indent=1, default=str))
