"""Daily multi-strategy paper portfolio: targets, order planning, idempotency, kill switch."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import pytest

from fakes import FakeBroker
from ictbot.daily_portfolio import (
    PortfolioConfig,
    Sleeve,
    compute_targets,
    latest_weights,
    load_portfolio_config,
    plan_orders,
    required_symbols,
    run_rebalance,
)
from ictbot.execution import BrokerPosition
from ictbot.research.base import load_all_strategies
from ictbot.research.costs import CostModel
from ictbot.research.data import synthetic_data
from ictbot.timeutils import ny_dt

ROOT = Path(__file__).resolve().parents[1]
CFG = load_portfolio_config(ROOT / "config" / "daily_portfolio.yaml")


@pytest.fixture(scope="module")
def data():
    return synthetic_data(required_symbols(CFG), start="2024-01-02", end="2025-09-30", seed=5)


def test_shipped_config_loads_and_is_within_hard_caps():
    assert CFG.gross_cap <= 2.0 and CFG.max_drawdown_kill <= 0.5
    assert {s.strategy for s in CFG.sleeves} == {"xsmom_sector_rotation", "meanrev_regime"}


def test_targets_are_weighted_sum_of_research_weights_and_capped(data):
    tr = compute_targets(data, CFG)
    specs = load_all_strategies()
    manual = {}
    for s in CFG.sleeves:
        _, w = latest_weights(specs[s.strategy].run(data, s.params, CostModel()).weights)
        for k, v in w.items():
            if abs(v) > 1e-9:
                manual[k] = manual.get(k, 0.0) + s.weight * v
    gross = sum(manual.values())
    scale = min(1.0, CFG.gross_cap / gross) if gross else 1.0
    assert tr.targets == pytest.approx({k: v * scale for k, v in manual.items()})
    assert sum(tr.targets.values()) <= CFG.gross_cap + 1e-9
    assert all(v >= 0 for v in tr.targets.values())


def test_gross_cap_scales_down():
    cfg = dataclasses.replace(CFG, gross_cap=0.5)
    d = synthetic_data(required_symbols(cfg), start="2024-01-02", end="2025-09-30", seed=5)
    tr = compute_targets(d, cfg)
    assert sum(tr.targets.values()) <= 0.5 + 1e-9


def test_plan_orders_band_exits_and_sell_first():
    pos = [BrokerPosition("XLK", 100, 200.0, 200.0), BrokerPosition("SPY", 10, 500.0, 500.0)]
    prices = {"XLK": 200.0, "SPY": 500.0, "XLF": 50.0}
    orders = plan_orders({"XLK": 0.205, "XLF": 0.3}, pos, prices, equity=100_000, band=0.02)
    # XLK: 0.20 -> 0.205 is inside the band (no trade); SPY not targeted -> full exit; XLF new entry
    assert [(o.symbol, o.side, o.qty) for o in orders] == [("SPY", "sell", 10), ("XLF", "buy", 600)]


def test_rebalance_places_orders_then_is_idempotent(data, tmp_path):
    broker = FakeBroker()
    prices = {s: float(df["close"].iloc[-1]) for s, df in data.daily.items()}
    now = ny_dt(dt.date(2025, 10, 1), dt.time(9, 40))
    r1 = run_rebalance(CFG, broker, data, prices, now, dry_run=False, force=False, out_dir=tmp_path)
    assert r1["sent"] and all(o["side"] == "buy" for o in r1["sent"])
    r2 = run_rebalance(CFG, broker, data, prices, now, dry_run=False, force=False, out_dir=tmp_path)
    assert r2.get("skipped") == "already rebalanced today"
    assert (tmp_path / "2025-10-01" / "daily_portfolio.json").exists()


def test_dry_run_sends_nothing(data, tmp_path):
    broker = FakeBroker()
    prices = {s: float(df["close"].iloc[-1]) for s, df in data.daily.items()}
    rep = run_rebalance(CFG, broker, data, prices, ny_dt(dt.date(2025, 10, 1), dt.time(9, 40)), dry_run=True, force=False, out_dir=tmp_path)
    assert rep["sent"] and all(o.get("dry_run") for o in rep["sent"])
    assert broker.orders("all") == []


def test_kill_switch_liquidates(data, tmp_path):
    broker = FakeBroker(equity=60_000)
    broker.equity_history = lambda: [(dt.date(2025, 9, 1), 100_000.0)]
    broker.pos["XLK"] = BrokerPosition("XLK", 50, 200.0, 200.0)
    prices = {s: float(df["close"].iloc[-1]) for s, df in data.daily.items()} | {"XLK": 200.0}
    rep = run_rebalance(CFG, broker, data, prices, ny_dt(dt.date(2025, 10, 1), dt.time(9, 40)), dry_run=False, force=False, out_dir=tmp_path)
    assert rep["kill_switch"] and rep["targets"] == {}
    assert [(o["symbol"], o["side"]) for o in rep["sent"]] == [("XLK", "sell")]


def test_config_rejects_unsafe_values(tmp_path):
    bad = (ROOT / "config" / "daily_portfolio.yaml").read_text().replace("gross_cap: 1.9", "gross_cap: 3.0")
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ValueError, match="gross_cap"):
        load_portfolio_config(p)
    assert isinstance(CFG, PortfolioConfig) and isinstance(CFG.sleeves[0], Sleeve)
