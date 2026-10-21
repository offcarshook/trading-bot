"""Risk engine limits, portfolio bucket logic, execution idempotency, reconciliation."""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from conftest import DAY1
from fakes import FakeBroker
from ictbot.config import BotConfig
from ictbot.data import Quote
from ictbot.execution import ExecutionEngine, make_client_order_id, parse_client_order_id
from ictbot.models import FVG, MSS, Direction, Displacement, LiquidityPool, PoolSide, Setup, Sweep, Swing
from ictbot.portfolio import select_setups
from ictbot.risk import (
    AccountSnapshot,
    ApprovedOrder,
    Exposure,
    MarketCheck,
    Rejection,
    RiskConfigError,
    RiskEngine,
    RiskState,
)
from ictbot.state import reconstruct_trades, risk_state_from_broker, snapshot
from ictbot.timeutils import ny_dt

NOW = ny_dt(DAY1, dt.time(10, 15))
CLOSE = ny_dt(DAY1, dt.time(16, 0))


def make_setup(symbol="SPY", direction=Direction.SHORT, entry=500.0, stop=501.0, target=497.0, score=5.0, atr=0.8, sid="abc1234567"):
    pool = LiquidityPool("PD_high", "prev_day", PoolSide.BUY_SIDE, 500.8, 0)
    sweep = Sweep(pool, 10, 10, 500.9)
    disp = Displacement(11, direction, 1.0, 1.5, 0.1)
    mss = MSS(sweep, disp, Swing(5, 499.5, "low", 7))
    fvg = FVG(12, direction, 499.8, 500.2)
    return Setup(sid, symbol, direction, NOW, 12, entry, stop, target, "PD_low", sweep, mss, fvg, score, atr)


def acct(equity=100_000.0, last=None, bp=None, **kw):
    return AccountSnapshot(equity, last if last is not None else equity, bp if bp is not None else equity * 2, **kw)


def rstate(**kw):
    base = dict(now=NOW, day_pnl_pct=0.0, week_pnl_pct=0.0, drawdown_pct=0.0, trades_today=0, consecutive_losses=0)
    base.update(kw)
    return RiskState(**base)


def market(**kw):
    base = dict(now=NOW, session_close=CLOSE, quote=Quote(499.99, 500.01, NOW - dt.timedelta(seconds=2)), bar_volume=50_000, rvol=1.0, newest_bar_age_s=30)
    base.update(kw)
    return MarketCheck(**base)


BUCKET = ("SPY", "QQQM")


def approve(engine, setup=None, account=None, state=None, exposures=(), mk=None, frac=1.0):
    return engine.approve(setup or make_setup(), account or acct(), state or rstate(), list(exposures), mk or market(), BUCKET, 1.5, frac)


# --------------------------------------------------------------------------- #
# Config ceilings and issuance
# --------------------------------------------------------------------------- #


def test_config_above_hard_ceiling_refuses(cfg: BotConfig):
    bad = dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, risk_per_trade_pct=5.0))
    with pytest.raises(RiskConfigError):
        RiskEngine(bad)


def test_strategy_cannot_forge_an_approved_order():
    with pytest.raises(PermissionError):
        ApprovedOrder("SPY", Direction.LONG, 10, 100.0, 99.0, 103.0, 10.0, "x", "t", 1.0)


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #


def test_sizing_from_stop_distance(cfg: BotConfig):
    eng = RiskEngine(dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, vol_scaling=dataclasses.replace(cfg.risk.vol_scaling, enabled=False))))
    o = approve(eng)
    assert isinstance(o, ApprovedOrder)
    # 0.5% of 100k = $500 risk / $1.00 per share = 500 shares... capped by 25% notional: 25k/500 = 50 shares
    assert o.qty == 50
    assert o.stop > o.entry > o.target


def test_risk_sizing_binds_when_stop_is_wide(cfg: BotConfig):
    eng = RiskEngine(dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, vol_scaling=dataclasses.replace(cfg.risk.vol_scaling, enabled=False))))
    o = approve(eng, setup=make_setup(entry=500.0, stop=520.0, target=440.0, atr=8.0))
    assert o.qty == 25  # $500 / $20
    assert o.risk_dollars == pytest.approx(500.0)


def test_vol_scaling_reduces_size_in_high_volatility(cfg: BotConfig):
    eng = RiskEngine(cfg)
    calm = approve(eng, setup=make_setup(entry=500.0, stop=520.0, target=440.0, atr=0.5))
    wild = approve(eng, setup=make_setup(entry=500.0, stop=520.0, target=440.0, atr=2.0))
    assert wild.qty < calm.qty
    assert calm.qty == 25  # scale capped at 1.0 - never above configured risk


def test_total_notional_cap(cfg: BotConfig):
    eng = RiskEngine(cfg)
    held = [Exposure("IWM", Direction.LONG, 230, 200.0, 199.0, False)]  # $46k used of $50k
    o = approve(eng, exposures=held)
    assert isinstance(o, ApprovedOrder) and o.qty == 8  # (50k-46k)/500


def test_correlated_bucket_risk_cap(cfg: BotConfig):
    eng = RiskEngine(cfg)
    # QQQM already risks $600 of a $750 (1.5 x $500) bucket budget
    held = [Exposure("QQQM", Direction.SHORT, 100, 200.0, 206.0, False)]
    o = approve(eng, setup=make_setup(entry=500.0, stop=510.0, target=470.0), exposures=held)
    assert isinstance(o, ApprovedOrder)
    assert o.risk_dollars <= 150.0 + 1e-9 and "reduced_by_bucket_cap" in o.notes
    full = [Exposure("QQQM", Direction.SHORT, 125, 200.0, 206.0, False)]  # $750 -> no room
    assert approve(eng, exposures=full).reason == "bucket_risk_cap_reached"


def test_size_below_one_share_rejected(cfg: BotConfig):
    eng = RiskEngine(cfg)
    r = approve(eng, account=acct(equity=2_500.0), setup=make_setup(entry=500.0, stop=520.0, target=440.0))
    assert isinstance(r, Rejection) and r.reason == "size_below_one_share"


# --------------------------------------------------------------------------- #
# Halts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "state_kw,reason,flatten,kill",
    [
        (dict(day_pnl_pct=-2.0), "daily_loss_limit", True, False),
        (dict(week_pnl_pct=-4.1), "weekly_loss_limit", True, False),
        (dict(drawdown_pct=8.0), "max_drawdown_kill_switch", True, True),
        (dict(trades_today=2), "max_trades_per_day", False, False),
        (dict(consecutive_losses=3), "max_consecutive_losses", False, False),
        (dict(last_loss_exit=NOW - dt.timedelta(minutes=10)), "cooldown_after_loss", False, False),
        (dict(manual_disable=True), "manually_disabled", False, False),
    ],
)
def test_halts(cfg: BotConfig, state_kw, reason, flatten, kill):
    eng = RiskEngine(cfg)
    st = eng.status(acct(), rstate(**state_kw))
    assert not st.can_open and reason in st.reasons
    assert st.flatten is flatten and st.kill_switch is kill
    assert approve(eng, state=rstate(**state_kw)).reason == "halted"


def test_cooldown_expires(cfg: BotConfig):
    eng = RiskEngine(cfg)
    assert eng.status(acct(), rstate(last_loss_exit=NOW - dt.timedelta(minutes=31))).can_open


def test_no_averaging_down(cfg: BotConfig):
    eng = RiskEngine(cfg)
    held = [Exposure("SPY", Direction.SHORT, 10, 501.0, 503.0, False)]
    assert approve(eng, exposures=held).reason == "position_or_order_exists"


def test_unprotected_exposure_blocks_everything(cfg: BotConfig):
    eng = RiskEngine(cfg)
    held = [Exposure("IWM", Direction.LONG, 10, 200.0, None, False)]
    assert approve(eng, exposures=held).reason == "unprotected_exposure_present"


# --------------------------------------------------------------------------- #
# Pre-trade checks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mk_kw,reason",
    [
        (dict(quote=None), "missing_quote"),
        (dict(quote=Quote(499.0, 501.0, NOW)), "spread_too_wide_bps"),
        (dict(quote=Quote(499.99, 500.01, NOW - dt.timedelta(minutes=5))), "stale_quote"),
        (dict(newest_bar_age_s=None), "stale_or_missing_bars"),
        (dict(newest_bar_age_s=3600), "stale_or_missing_bars"),
        (dict(bar_volume=10), "bar_volume_too_low"),
        (dict(rvol=0.1), "relative_volume_too_low"),
        (dict(now=CLOSE - dt.timedelta(minutes=10)), "too_close_to_close"),
        (dict(shortable=False), "not_shortable_or_htb"),
    ],
)
def test_pre_trade_guards(cfg: BotConfig, mk_kw, reason):
    eng = RiskEngine(cfg)
    if "now" in mk_kw:
        mk_kw["quote"] = Quote(499.99, 500.01, mk_kw["now"])
    assert approve(eng, mk=market(**mk_kw)).reason == reason


def test_wrong_side_stop_rejected(cfg: BotConfig):
    eng = RiskEngine(cfg)
    assert approve(eng, setup=make_setup(entry=500.0, stop=499.0, target=497.0)).reason == "invalid_prices"


# --------------------------------------------------------------------------- #
# Portfolio selection
# --------------------------------------------------------------------------- #


def test_portfolio_best_mode_takes_higher_score(cfg: BotConfig):
    a, b = make_setup("SPY", score=4.0, sid="aaaaaaaaaa"), make_setup("QQQM", score=6.0, sid="bbbbbbbbbb")
    sel, skipped = select_setups([a, b], [], cfg)
    assert [s.setup.symbol for s in sel] == ["QQQM"]
    assert skipped[0][1] == "bucket_conflict_lower_score"


def test_portfolio_split_mode(cfg: BotConfig):
    c = dataclasses.replace(cfg, portfolio=dataclasses.replace(cfg.portfolio, conflict_mode="split"))
    sel, _ = select_setups([make_setup("SPY", sid="aaaaaaaaaa"), make_setup("QQQM", sid="bbbbbbbbbb")], [], c)
    assert sorted(s.setup.symbol for s in sel) == ["QQQM", "SPY"]
    assert all(s.risk_fraction == 0.5 for s in sel)


def test_portfolio_second_same_direction_reduced_and_opposite_blocked(cfg: BotConfig):
    held = [Exposure("SPY", Direction.SHORT, 10, 501.0, 503.0, False)]
    sel, _ = select_setups([make_setup("QQQM", Direction.SHORT, sid="bbbbbbbbbb")], held, cfg)
    assert sel[0].risk_fraction == cfg.portfolio.second_same_direction_risk_fraction
    long_q = make_setup("QQQM", Direction.LONG, entry=500.0, stop=499.0, target=503.0, sid="cccccccccc")
    sel, skipped = select_setups([long_q], held, cfg)
    assert sel == [] and skipped[0][1] == "opposite_direction_in_correlated_bucket"


# --------------------------------------------------------------------------- #
# Execution idempotency + reconciliation
# --------------------------------------------------------------------------- #


def _approved(cfg, setup=None):
    o = approve(RiskEngine(cfg), setup=setup)
    assert isinstance(o, ApprovedOrder)
    return o


def test_client_order_id_roundtrip():
    coid = make_client_order_id("ictb", DAY1, "QQQM", "abc1234567", "e")
    assert parse_client_order_id(coid) == {"prefix": "ictb", "day": "250311", "symbol": "QQQM", "setup": "abc1234567", "leg": "e"}
    assert parse_client_order_id("manual-order") is None


def test_restart_never_double_places(cfg: BotConfig):
    broker = FakeBroker()
    order = _approved(cfg)
    first = ExecutionEngine(broker, cfg).place_entry(order, DAY1)
    second = ExecutionEngine(broker, cfg).place_entry(order, DAY1)  # "restarted" bot
    assert broker.submits == 1
    assert second.duplicate and second.orders[0].id == first.orders[0].id


def test_timeout_after_submit_is_reconciled_not_resent(cfg: BotConfig):
    broker = FakeBroker()
    broker.fail_after_submit_once = True
    res = ExecutionEngine(broker, cfg).place_entry(_approved(cfg), DAY1)
    assert broker.submits == 1 and res.duplicate


def test_bracket_carries_stop_and_target(cfg: BotConfig):
    broker = FakeBroker()
    res = ExecutionEngine(broker, cfg).place_entry(_approved(cfg), DAY1)
    o = res.orders[0]
    assert o.order_class == "bracket"
    types = sorted(leg.type for leg in o.legs)
    assert types == ["limit", "stop"]


def test_partial_take_profit_uses_two_protected_brackets(cfg: BotConfig):
    c = dataclasses.replace(cfg, execution=dataclasses.replace(cfg.execution, partial_take_profit=dataclasses.replace(cfg.execution.partial_take_profit, enabled=True)))
    broker = FakeBroker()
    res = ExecutionEngine(broker, c).place_entry(_approved(c), DAY1)
    assert len(res.orders) == 2
    assert all(any(leg.type == "stop" for leg in o.legs) for o in res.orders)
    assert sum(o.qty for o in res.orders) == 50


def test_dry_run_sends_nothing(cfg: BotConfig):
    broker = FakeBroker()
    res = ExecutionEngine(broker, cfg, dry_run=True).place_entry(_approved(cfg), DAY1)
    assert res.dry_run and broker.submits == 0


def test_snapshot_flags_unprotected_and_stale(cfg: BotConfig):
    broker = FakeBroker()
    eng = ExecutionEngine(broker, cfg)
    placed = eng.place_entry(_approved(cfg), DAY1).orders[0]
    broker.fill_entry(placed.id, 500.0)
    st = snapshot(broker.positions(), broker.orders("open"), cfg, DAY1)
    assert st.unprotected == [] and st.exposures[0].stop == 501.0
    broker.cancel(placed.id)  # legs die -> position naked
    for leg in placed.legs:
        leg.status = "canceled"
    st = snapshot(broker.positions(), broker.orders("open"), cfg, DAY1)
    assert st.unprotected == ["SPY"]
    later = snapshot(broker.positions(), broker.orders("open"), cfg, DAY1 + dt.timedelta(days=1))
    assert later.stale_orders == []  # nothing open anymore


def test_flatten_all_cancels_then_closes(cfg: BotConfig):
    broker = FakeBroker()
    eng = ExecutionEngine(broker, cfg, sleep=lambda s: None)
    placed = eng.place_entry(_approved(cfg), DAY1).orders[0]
    broker.fill_entry(placed.id, 500.0)
    actions = eng.flatten_all(DAY1, "eod")
    assert broker.positions() == []
    assert any(a.startswith("close SPY") for a in actions)
    flat = [o for o in broker.orders("all") if (parse_client_order_id(o.client_order_id) or {}).get("leg") == "f"]
    assert len(flat) == 1 and flat[0].side == "buy"


def test_trade_reconstruction_and_risk_state(cfg: BotConfig):
    broker = FakeBroker()
    eng = ExecutionEngine(broker, cfg)
    t0 = ny_dt(DAY1, dt.time(10, 0))
    o1 = eng.place_entry(_approved(cfg, make_setup(sid="aaaaaaaaaa")), DAY1).orders[0]
    broker.fill_entry(o1.id, 500.0, t0)
    broker.fill_leg(o1.id, "sl", 501.0, t0 + dt.timedelta(minutes=5))
    trades = reconstruct_trades(broker.orders("all"), "ictb")
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop_loss" and t.pnl == pytest.approx(-50.0) and t.r_multiple == pytest.approx(-1.0)
    rs = risk_state_from_broker(now=t0 + dt.timedelta(minutes=10), equity=99_950, last_equity=100_000,
                                equity_history=[(DAY1 - dt.timedelta(days=1), 100_000.0)], trades=trades,
                                working_setup_ids=set(), cfg=cfg)
    assert rs.trades_today == 1 and rs.consecutive_losses == 1
    assert rs.last_loss_exit == t0 + dt.timedelta(minutes=5)
    assert rs.day_pnl_pct == pytest.approx(-0.05)
    assert RiskEngine(cfg).status(acct(), rs).reasons == ("cooldown_after_loss",)


def test_drawdown_kill_switch_reset_date(cfg: BotConfig):
    hist = [(dt.date(2025, 1, 2), 110_000.0), (dt.date(2025, 3, 1), 100_000.0)]
    kw = dict(now=NOW, equity=100_000, last_equity=100_000, equity_history=hist, trades=[], working_setup_ids=set())
    assert risk_state_from_broker(cfg=cfg, **kw).drawdown_pct == pytest.approx(9.0909, rel=1e-3)
    reset = dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, drawdown_reset_date="2025-02-01"))
    assert risk_state_from_broker(cfg=reset, **kw).drawdown_pct == pytest.approx(0.0)


def test_flatten_rereads_positions_after_cancels(cfg: BotConfig):
    """Audit finding: a stop leg can fill while its cancel is in flight. flatten_all
    must not then send a stale market close that would open a reverse position."""
    broker = FakeBroker()
    eng = ExecutionEngine(broker, cfg, sleep=lambda s: None)
    placed = eng.place_entry(_approved(cfg), DAY1).orders[0]
    broker.fill_entry(placed.id, 500.0)
    real_cancel = broker.cancel

    def racing_cancel(order_id):
        broker.fill_leg(placed.id, "sl", 501.0)  # stop fills first...
        real_cancel(order_id)  # ...then the cancel arrives

    broker.cancel = racing_cancel
    eng.flatten_all(DAY1, "eod")
    flat_orders = [o for o in broker.orders("all") if (parse_client_order_id(o.client_order_id) or {}).get("leg") == "f"]
    assert flat_orders == [], "a market close was sent for a position that no longer existed"
    assert broker.positions() == []
