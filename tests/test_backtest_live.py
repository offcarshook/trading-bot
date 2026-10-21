"""Backtest fill model + end-to-end invariants, and a live-loop smoke test with fakes."""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from conftest import DAY0, DAY1, session
from fakes import FakeBroker
from ictbot.alerts import Notifier
from ictbot.backtest import exit_on_bar, limit_fill_price, run_backtest, split_days, trade_fees
from ictbot.config import BotConfig
from ictbot.data import Quote
from ictbot.live import DayContext, LiveBot
from ictbot.models import Direction
from ictbot.reporting import Recorder, compute_metrics
from ictbot.state import PlanCache
from ictbot.timeutils import NY, ny_dt
from test_strategy import DAY0_ROWS, TODAY_ROWS

# --------------------------------------------------------------------------- #
# Fill model
# --------------------------------------------------------------------------- #


def test_limit_requires_trade_through():
    assert limit_fill_price(Direction.LONG, 100.0, (100.5, 100.6, 100.0, 100.2), True) is None
    assert limit_fill_price(Direction.LONG, 100.0, (100.5, 100.6, 100.0, 100.2), False) == 100.0
    assert limit_fill_price(Direction.LONG, 100.0, (99.5, 99.8, 99.4, 99.6), True) == 99.5  # gap: better price
    assert limit_fill_price(Direction.SHORT, 100.0, (99.7, 100.2, 99.6, 100.1), True) == 100.0


def test_stop_wins_when_both_touched_and_gaps_slip():
    hit = exit_on_bar(Direction.LONG, 99.0, 101.0, (100.0, 101.5, 98.5, 100.0), 0.0, True)
    assert hit == (99.0, "stop_loss")
    gap = exit_on_bar(Direction.LONG, 99.0, 101.0, (98.0, 98.5, 97.0, 98.2), 10.0, True)
    assert gap[1] == "stop_loss" and gap[0] == pytest.approx(98.0 * (1 - 0.001))
    assert exit_on_bar(Direction.SHORT, 101.0, 99.0, (100.0, 100.2, 98.9, 99.1), 0.0, True) == (99.0, "take_profit")
    assert exit_on_bar(Direction.SHORT, 101.0, 99.0, (100.0, 100.2, 98.9, 99.1), 0.0, False) is None


def test_fees_charged_on_sell_side(cfg: BotConfig):
    long_fee = trade_fees(cfg, Direction.LONG, 100, 500.0, 510.0)
    assert long_fee == pytest.approx(cfg.backtest.sec_fee_rate * 510 * 100 + cfg.backtest.taf_per_share * 100, rel=1e-6)


def test_holdout_split():
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(10)]
    ins, oos = split_days(days, 0.3)
    assert len(ins) == 7 and len(oos) == 3 and ins[-1] < oos[0]


# --------------------------------------------------------------------------- #
# Synthetic minute data
# --------------------------------------------------------------------------- #


def expand_5m_to_1m(rows, day, start=dt.time(9, 30), vol=2000.0) -> pd.DataFrame:
    """Each 5m (o,h,l,c) becomes five 1m bars that aggregate back exactly."""
    out, idx = [], []
    t0 = ny_dt(day, start)
    for k, (o, h, l, c) in enumerate(rows):
        mins = [(o, h, min(o, c), o), (o, max(o, c), l, c), (c, c, c, c), (c, c, c, c), (c, c, c, c)]
        for j, m in enumerate(mins):
            idx.append(t0 + dt.timedelta(minutes=5 * k + j))
            out.append(m)
    df = pd.DataFrame(out, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(idx, tz=NY))
    df["volume"] = vol
    return df


def random_walk_minutes(days: list[dt.date], seed: int, start_px: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames, px = [], start_px
    for d in days:
        idx = pd.date_range(ny_dt(d, dt.time(9, 30)), periods=390, freq="1min", tz=NY)
        steps = rng.normal(0, 0.03, len(idx)) * px / 100
        closes = px + np.cumsum(steps)
        opens = np.concatenate(([px], closes[:-1]))
        wig = np.abs(rng.normal(0, 0.02, len(idx))) * px / 100
        frames.append(pd.DataFrame({"open": opens, "high": np.maximum(opens, closes) + wig, "low": np.minimum(opens, closes) - wig,
                                    "close": closes, "volume": rng.integers(500, 5000, len(idx)).astype(float)}, index=idx))
        px = closes[-1]
    return pd.concat(frames)


def test_backtest_runs_and_never_holds_overnight(cfg: BotConfig):
    days = [dt.date(2025, 3, 3) + dt.timedelta(days=i) for i in range(12)]
    days = [d for d in days if d.weekday() < 5]
    sessions = [session(d) for d in days]
    minutes = {"SPY": random_walk_minutes(days, 1, 500.0), "QQQM": random_walk_minutes(days, 2, 200.0)}
    loose = dataclasses.replace(cfg, ict=dataclasses.replace(cfg.ict, scoring=dataclasses.replace(cfg.ict.scoring, min_score=0.0)))
    res = run_backtest(loose, minutes, sessions, days[2], days[-1])
    assert len(res.equity) > 0 and res.signals >= 0
    for t in res.trades:
        assert t.exit_time.date() == t.entry_time.date()
        assert t.exit_time <= ny_dt(t.entry_time.date(), dt.time(15, 55))
    m = compute_metrics(res.trades, res.equity)
    assert m["trades"] == len(res.trades)


# --------------------------------------------------------------------------- #
# Live loop smoke test
# --------------------------------------------------------------------------- #


class FakeData:
    def __init__(self, minutes: dict[str, pd.DataFrame]):
        self.m = minutes

    def minute_bars(self, symbols, start, end):
        return {s: self.m[s][(self.m[s].index >= start) & (self.m[s].index < end)] for s in symbols}

    def latest_quote(self, symbol):
        return Quote(100.0, 100.01, self.now)


def test_live_cycle_places_exactly_once(cfg: BotConfig, tmp_path, monkeypatch):
    monkeypatch.delenv("ICTBOT_TRADING_ENABLED", raising=False)
    cfg = dataclasses.replace(cfg, symbols=("SPY",), reporting=dataclasses.replace(cfg.reporting, reports_dir=str(tmp_path / "reports")))
    m1 = pd.concat([expand_5m_to_1m(DAY0_ROWS, DAY0), expand_5m_to_1m(TODAY_ROWS, DAY1)])
    data = FakeData({"SPY": m1})
    broker = FakeBroker()
    clock_now = [ny_dt(DAY1, dt.time(10, 15, 30))]
    bot = LiveBot(cfg, broker, data, Notifier(cfg.alerts), clock=lambda: clock_now[0], sleep=lambda s: None, state_dir=str(tmp_path / "state"))
    ctx = DayContext(session(DAY1), [session(DAY0), session(DAY1)], True, "")
    rec = Recorder(cfg.reporting.reports_dir, DAY1)
    cache = PlanCache(tmp_path / "state", DAY1)
    data.now = clock_now[0]
    bot.load_history(ctx)
    bot.cycle(ctx, clock_now[0], cache, rec)
    assert broker.submits == 1
    o = next(iter(broker.orders_by_id.values()))
    assert o.side == "sell" and o.limit_price == pytest.approx(100.1)
    assert {leg.type for leg in o.legs} == {"limit", "stop"}
    signals = pd.read_csv(rec.day_dir / "signals.csv")
    assert "taken" in set(signals["decision"])

    # next bar: same setup must not be placed again (idempotent across cycles)
    clock_now[0] = ny_dt(DAY1, dt.time(10, 20, 30))
    data.now = clock_now[0]
    bot.cycle(ctx, clock_now[0], cache, rec)
    assert broker.submits == 1

    # a fresh process (restart) with an empty local cache also must not re-place it
    bot2 = LiveBot(cfg, broker, data, Notifier(cfg.alerts), clock=lambda: clock_now[0], sleep=lambda s: None, state_dir=str(tmp_path / "state2"))
    bot2.load_history(ctx)
    bot2.cycle(ctx, clock_now[0], PlanCache(tmp_path / "state2", DAY1), rec)
    assert broker.submits == 1


def test_live_cycle_respects_manual_disable(cfg: BotConfig, tmp_path, monkeypatch):
    monkeypatch.setenv("ICTBOT_TRADING_ENABLED", "false")
    cfg = dataclasses.replace(cfg, symbols=("SPY",), reporting=dataclasses.replace(cfg.reporting, reports_dir=str(tmp_path / "r")))
    m1 = pd.concat([expand_5m_to_1m(DAY0_ROWS, DAY0), expand_5m_to_1m(TODAY_ROWS, DAY1)])
    data = FakeData({"SPY": m1})
    data.now = ny_dt(DAY1, dt.time(10, 15, 30))
    broker = FakeBroker()
    bot = LiveBot(cfg, broker, data, Notifier(cfg.alerts), clock=lambda: data.now, sleep=lambda s: None, state_dir=str(tmp_path / "s"))
    ctx = DayContext(session(DAY1), [session(DAY0), session(DAY1)], True, "")
    bot.load_history(ctx)
    info = bot.cycle(ctx, data.now, PlanCache(tmp_path / "s", DAY1), Recorder(cfg.reporting.reports_dir, DAY1))
    assert broker.submits == 0 and "manually_disabled" in info["halt"]


def test_start_gate_handles_dst(cfg: BotConfig):
    bot = LiveBot(cfg, FakeBroker(), None, Notifier(cfg.alerts))
    # cron 13:00 UTC: 09:00 EDT (summer) -> run;  08:00 EST (winter) -> exit
    summer = dt.datetime(2025, 7, 1, 13, 0, tzinfo=dt.timezone.utc).astimezone(NY)
    winter = dt.datetime(2025, 1, 7, 13, 0, tzinfo=dt.timezone.utc).astimezone(NY)
    assert bot.start_gate(summer)[0] is True
    assert bot.start_gate(winter)[0] is False
    # cron 14:00 UTC: 10:00 EDT -> still allowed (late but inside window), 09:00 EST -> run
    assert bot.start_gate(dt.datetime(2025, 1, 7, 14, 0, tzinfo=dt.timezone.utc).astimezone(NY))[0] is True


def test_full_day_run_flattens_and_writes_journal(cfg: BotConfig, tmp_path, monkeypatch):
    """Drive LiveBot.run() through a whole simulated day with a fake clock."""
    monkeypatch.delenv("ICTBOT_TRADING_ENABLED", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "event_days.yaml").write_text("events: []\n")
    cfg = dataclasses.replace(
        cfg, symbols=("SPY",),
        reporting=dataclasses.replace(cfg.reporting, reports_dir=str(tmp_path / "reports")),
        session=dataclasses.replace(cfg.session, exit_when_idle_after_windows=False, max_runtime_minutes=600),
    )
    rest = [(98.9, 99.0, 98.8, 98.95)] * (78 - len(TODAY_ROWS))
    m1 = pd.concat([expand_5m_to_1m(DAY0_ROWS, DAY0), expand_5m_to_1m(TODAY_ROWS + rest, DAY1)])
    t = [ny_dt(DAY1, dt.time(9, 20))]

    class ClockData(FakeData):
        def latest_quote(self, symbol):
            return Quote(98.94, 98.95, t[0])

    broker = FakeBroker()
    broker.sessions_list = [session(DAY0), session(DAY1)]
    bot = LiveBot(cfg, broker, ClockData({"SPY": m1}), Notifier(cfg.alerts), clock=lambda: t[0],
                  sleep=lambda s: t.__setitem__(0, t[0] + dt.timedelta(seconds=s)), state_dir=str(tmp_path / "state"))
    assert bot.run() == 0
    assert broker.submits == 1  # placed once, then cancelled/expired - never re-placed
    parent = next(o for o in broker.orders_by_id.values() if o.order_class == "bracket")
    assert parent.status == "canceled"
    assert t[0] >= ny_dt(DAY1, dt.time(15, 55))
    day_dir = tmp_path / "reports" / DAY1.isoformat()
    assert (day_dir / "journal.md").exists() and (day_dir / "signals.csv").exists()
    events = (day_dir / "events.jsonl").read_text()
    assert '"end_of_day"' in events and '"cancel"' in events


def test_dry_run_logs_taken_once_and_sends_nothing(cfg: BotConfig, tmp_path, monkeypatch):
    monkeypatch.delenv("ICTBOT_TRADING_ENABLED", raising=False)
    cfg = dataclasses.replace(cfg, symbols=("SPY",), mode=dataclasses.replace(cfg.mode, dry_run=True),
                              reporting=dataclasses.replace(cfg.reporting, reports_dir=str(tmp_path / "r")))
    m1 = pd.concat([expand_5m_to_1m(DAY0_ROWS, DAY0), expand_5m_to_1m(TODAY_ROWS + [(98.9, 99.0, 98.85, 98.95)] * 3, DAY1)])
    data = FakeData({"SPY": m1})
    broker = FakeBroker()
    bot = LiveBot(cfg, broker, data, Notifier(cfg.alerts), clock=lambda: data.now, sleep=lambda s: None, state_dir=str(tmp_path / "s"))
    ctx = DayContext(session(DAY1), [session(DAY0), session(DAY1)], True, "")
    rec = Recorder(cfg.reporting.reports_dir, DAY1)
    bot.load_history(ctx)
    for hhmm in ((10, 15, 30), (10, 20, 30), (10, 25, 30)):
        data.now = ny_dt(DAY1, dt.time(*hhmm))
        bot.cycle(ctx, data.now, PlanCache(tmp_path / "s", DAY1), rec)
    assert broker.submits == 0
    sig = pd.read_csv(rec.day_dir / "signals.csv")
    assert (sig["decision"] == "taken").sum() == 1


def test_manual_run_long_before_open_exits_without_waiting(cfg: BotConfig, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    broker = FakeBroker()
    broker.sessions_list = [session(DAY0), session(DAY1)]
    t = [ny_dt(DAY1, dt.time(4, 45))]
    slept = []
    cfg = dataclasses.replace(cfg, reporting=dataclasses.replace(cfg.reporting, reports_dir=str(tmp_path / "r")))
    bot = LiveBot(cfg, broker, None, Notifier(cfg.alerts), clock=lambda: t[0], sleep=slept.append, state_dir=str(tmp_path / "s"))
    assert bot.run(respect_start_window=False) == 0
    assert slept == []
