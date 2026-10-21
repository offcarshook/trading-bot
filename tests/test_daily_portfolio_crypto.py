"""Crypto support in the daily paper portfolio: fractional orders, cash-only buying
power, asset-class isolation between the stock and crypto runs, mixed simulation."""

from __future__ import annotations

import dataclasses
import datetime as dt

import pandas as pd
import pytest

from fakes import FakeBroker
from ictbot import daily_portfolio as dp
from ictbot.daily_portfolio import PortfolioConfig, Sleeve, TargetResult, plan_orders, run_rebalance, simulate_portfolio
from ictbot.execution import BrokerPosition, crypto_pair, make_client_order_id, parse_client_order_id
from ictbot.research.base import REGISTRY, StrategySpec
from ictbot.research.costs import CostModel
from ictbot.research.data import synthetic_data
from ictbot.research.engine import run_weights
from ictbot.research.strategies.common import margin_requirement
from ictbot.timeutils import ny_dt

CFG = PortfolioConfig("test", (), 1.0, 0.02, None, None, 400, "dpf", "09:31", "11:00")
NOW = ny_dt(dt.date(2025, 9, 30), dt.time(9, 40))


def test_crypto_symbol_helpers():
    assert crypto_pair("BTCUSD") == "BTC/USD" and crypto_pair("AAVEUSD") == "AAVE/USD" and crypto_pair("BTC/USD") == "BTC/USD"
    assert dp.is_crypto_symbol("BTC/USD") and dp.is_crypto_symbol("BTCUSD") and not dp.is_crypto_symbol("SPY")
    assert not dp.is_crypto_symbol("TQQQ") and margin_requirement("BTC/USD") == 1.0
    coid = make_client_order_id("dpf", NOW.date(), "BTC/USD", "r09400000", "d")
    assert parse_client_order_id(coid)["symbol"] == "BTCUSD"


def test_plan_crypto_fractional_buy_exit_and_dust():
    pos = [BrokerPosition("ETH/USD", 1.2345678, 3000.0, 3000.0)]
    prices = {"BTC/USD": 60_000.0, "ETH/USD": 3000.0, "SOL/USD": 150.0}
    orders = plan_orders({"BTC/USD": 0.3, "SOL/USD": 0.00005}, pos, prices, equity=100_000, band=0.02)
    got = {o.symbol: (o.side, o.qty) for o in orders}
    assert got["ETH/USD"] == ("sell", 1.2345678)  # full fractional exit
    assert got["BTC/USD"] == ("buy", 0.5)  # 30k / 60k, fractional
    assert "SOL/USD" not in got  # target below the band and below min notional


def test_plan_crypto_partial_trim_never_exceeds_holding():
    pos = [BrokerPosition("BTC/USD", 1.0, 50_000.0, 60_000.0)]
    (o,) = plan_orders({"BTC/USD": 0.3}, pos, {"BTC/USD": 60_000.0}, equity=100_000, band=0.02)
    assert o.side == "sell" and o.qty == pytest.approx(0.5) and o.qty <= 1.0


def _broker():
    b = FakeBroker(equity=100_000)
    b.marks = {"BTC/USD": 60_000.0, "SPY": 500.0, "TQQQ": 50.0}
    b.acct.buying_power = "100000"
    b.acct.non_marginable_buying_power = "100000"
    return b


@pytest.fixture
def fixed_targets(monkeypatch):
    def fake(data, cfg, costs=None):
        return TargetResult("2025-09-29", {"BTC/USD": 0.3, "TQQQ": 0.5}, 0.8, 1.0, {})

    monkeypatch.setattr(dp, "compute_targets", fake)


def test_asset_class_runs_only_touch_their_own_symbols(fixed_targets, tmp_path):
    b = _broker()
    b.pos["SPY"] = BrokerPosition("SPY", 10, 500.0, 500.0)  # leftover stock
    prices = {"BTC/USD": 60_000.0, "TQQQ": 50.0}
    rep = run_rebalance(CFG, b, None, prices, NOW, dry_run=False, force=False, out_dir=tmp_path, sleep=lambda s: None, asset_class="crypto")
    assert {o["symbol"] for o in rep["sent"]} == {"BTC/USD"}
    assert "SPY" in b.pos and "TQQQ" not in b.pos and b.pos["BTC/USD"].qty == pytest.approx(0.5)
    rep = run_rebalance(CFG, b, None, prices, NOW, dry_run=False, force=False, out_dir=tmp_path, sleep=lambda s: None, asset_class="stocks")
    assert {(o["symbol"], o["side"]) for o in rep["sent"]} == {("SPY", "sell"), ("TQQQ", "buy")}
    assert b.pos["BTC/USD"].qty == pytest.approx(0.5) and b.pos["TQQQ"].qty == 1000
    rep = run_rebalance(CFG, b, None, prices, NOW, dry_run=False, force=False, out_dir=tmp_path, sleep=lambda s: None, asset_class="all")
    assert rep["sent"] == []  # idempotent across both classes


def test_crypto_buys_shrink_to_cash_only_buying_power(fixed_targets, tmp_path):
    b = _broker()
    b.acct.non_marginable_buying_power = "15000"  # half of the 30k BTC target
    rep = run_rebalance(CFG, b, None, {"BTC/USD": 60_000.0, "TQQQ": 50.0}, NOW, dry_run=False, force=False, out_dir=tmp_path,
                        sleep=lambda s: None, asset_class="crypto")
    (o,) = rep["sent"]
    assert o["qty"] == pytest.approx(0.98 * 15_000 / 60_000, abs=1e-6) and rep["crypto_buy_scale"] < 1


def test_unknown_asset_class_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_rebalance(CFG, _broker(), None, {}, NOW, dry_run=True, force=False, out_dir=tmp_path, asset_class="forex")


def _const_spec(name, weights, symbols):
    def run(data, params, costs):
        view = data.crypto_view() if any("/" in s for s in symbols) else data
        idx = view.dates()
        w = pd.DataFrame({s: weights[s] for s in symbols}, index=idx)
        return run_weights(view, w, costs)

    return StrategySpec(name, "test", "constant weights", {"x": [1]}, {"x": 1}, run, symbols=tuple(symbols))


@pytest.fixture
def mixed_specs():
    specs = [_const_spec("_t_coin", {"BTC/USD": 0.4}, ["BTC/USD"]), _const_spec("_t_stock", {"SPY": 0.5}, ["SPY"])]
    for s in specs:
        REGISTRY[s.name] = s
    yield specs
    for s in specs:
        REGISTRY.pop(s.name, None)


def test_mixed_simulation_holds_stocks_over_weekends(mixed_specs):
    data = synthetic_data(["SPY"], start="2024-01-02", end="2024-06-28", seed=3, crypto_symbols=("BTC/USD",), crypto_start="2024-01-01")
    cfg = dataclasses.replace(CFG, sleeves=(Sleeve("_t_coin", 1.0, {}), Sleeve("_t_stock", 1.0, {})), rebalance_band=0.05)
    res = simulate_portfolio(data, cfg, CostModel())
    assert res.returns.index.dayofweek.max() == 6  # weekends are in the book (crypto trades)
    # constant targets + a 5% band: after entry only drift trims, never a Monday 'sell all stocks'
    assert res.exposure.iloc[5:].min() > 0.8
    assert res.turnover.iloc[5:].max() < 0.2


def test_config_with_crypto_requires_cash_gross_cap(mixed_specs, tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("profile: x\nsleeves:\n  - {strategy: _t_coin, weight: 1.0, params: {}}\ngross_cap: 1.5\nrebalance_band: 0.02\n"
                 "max_drawdown_kill: null\ndrawdown_reset_date: null\nhistory_calendar_days: 400\nclient_order_id_prefix: dpf\n"
                 "window_start: '09:31'\nwindow_end: '11:00'\n")
    with pytest.raises(ValueError, match="cash-only"):
        dp.load_portfolio_config(p)
    p.write_text(p.read_text().replace("gross_cap: 1.5", "gross_cap: 1.0"))
    assert dp.load_portfolio_config(p).gross_cap == 1.0


def test_engine_cash_only_buys_wait_for_cash():
    # Sat decision moves the book from SPY to BTC; SPY cannot trade until Monday
    idx = pd.date_range("2024-01-04", periods=6)  # Thu..Tue; SPY trades Thu, Fri, Mon, Tue
    spy = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}, index=idx[[0, 1, 4, 5]])
    btc = pd.DataFrame({"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1.0}, index=idx)
    from ictbot.research.base import ResearchData

    data = ResearchData({"SPY": spy, "BTC/USD": btc}, {}, {})
    w = pd.DataFrame({"SPY": [1.0, 1.0, 0.0, 0.0, 0.0, 0.0], "BTC/USD": [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]}, index=idx)
    free = run_weights(data, w, CostModel())
    assert free.exposure.max() > 1.5  # without the rule: SPY 1.0 + BTC 1.0 on Sunday (borrowing for crypto)
    res = run_weights(data, w, CostModel(), cash_only=("BTC/USD",))
    assert res.exposure.max() <= 1.0 + 1e-12
    assert res.exposure.iloc[-1] == pytest.approx(1.0)  # Monday: SPY sold, BTC bought with the freed cash
