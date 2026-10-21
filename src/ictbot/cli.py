"""Command line interface.

  ictbot check            verify paper credentials, calendar, data and assets
  ictbot run              live paper-trading loop (one trading day)
  ictbot flatten          independent safety job: cancel + flatten near the close
  ictbot report           cumulative report rebuilt from broker history
  ictbot backtest         optional backtest / walk-forward (needs data access)
  ictbot reset-killswitch set risk.drawdown_reset_date to today in config.yaml
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd

from .config import BotConfig, ConfigError, load_config, parse_hhmm
from .logging_setup import setup_logging
from .risk import validate_risk_config
from .safety import LiveTradingRefused
from .timeutils import now_ny, ny_dt

log = logging.getLogger("ictbot")
DISCLAIMER = "Educational PAPER-trading experiment. Not financial advice. No profitability is claimed or implied."


def _cfg(args: argparse.Namespace) -> BotConfig:
    cfg = load_config(args.config)
    if getattr(args, "dry_run", False):
        cfg = dataclasses.replace(cfg, mode=dataclasses.replace(cfg.mode, dry_run=True))
    validate_risk_config(cfg)
    return cfg


def _clients(cfg: BotConfig):
    from .data import AlpacaMarketData
    from .execution import AlpacaBroker
    from .safety import load_paper_credentials

    creds = load_paper_credentials()
    return AlpacaBroker(creds.key_id, creds.secret_key), AlpacaMarketData(creds.key_id, creds.secret_key, cfg.data.feed)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    broker, data = _clients(cfg)
    a = broker.account()
    print(f"OK paper endpoint: {broker.base_url}")
    print(f"account status={getattr(a.status, 'value', a.status)} equity={a.equity} buying_power={a.buying_power} "
          f"shorting_enabled={a.shorting_enabled} pattern_day_trader={a.pattern_day_trader} daytrade_count={a.daytrade_count}")
    today = now_ny().date()
    sess = broker.sessions(today, today + dt.timedelta(days=7))
    for s in sess[:3]:
        print(f"session {s.day}: {s.open:%H:%M}-{s.close:%H:%M} ET{' (EARLY CLOSE)' if s.is_early_close else ''}")
    for sym in cfg.symbols:
        info = broker.asset(sym)
        q = data.latest_quote(sym)
        print(f"{sym}: tradable={info.tradable} shortable={info.shortable} easy_to_borrow={info.easy_to_borrow} "
              f"fractionable={info.fractionable} quote={'%.2f/%.2f' % (q.bid, q.ask) if q else 'n/a'} feed={cfg.data.feed}")
    print(DISCLAIMER)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .live import build_live_bot

    cfg = _cfg(args)
    log.info(DISCLAIMER)
    bot = build_live_bot(cfg)
    return bot.run(respect_start_window=not args.ignore_start_window)


def cmd_flatten(args: argparse.Namespace) -> int:
    from .execution import ExecutionEngine
    from .reporting import Recorder

    cfg = _cfg(args)
    now = now_ny()
    broker, _ = _clients(cfg)
    today = now.date()
    sess = [s for s in broker.sessions(today, today) if s.day == today]
    if not sess and not args.force:
        log.info("market closed today - nothing to do")
        return 0
    flatten_at = ny_dt(today, parse_hhmm(cfg.session.flatten_time))
    if sess:
        flatten_at = min(flatten_at, sess[0].close - dt.timedelta(minutes=5))
    if not args.force:
        window_start = flatten_at - dt.timedelta(minutes=args.max_wait_minutes)
        if now < window_start or (sess and now >= sess[0].close):
            log.info("outside the flatten window - exiting (expected for the off-DST cron trigger)",
                     extra={"now": now.isoformat(), "flatten_at": flatten_at.isoformat()})
            return 0
        while now_ny() < flatten_at:
            time.sleep(min(30.0, (flatten_at - now_ny()).total_seconds() + 0.5))
    actions = ExecutionEngine(broker, cfg, dry_run=cfg.mode.dry_run).flatten_all(today, "safety_flatten_job")
    Recorder(cfg.reporting.reports_dir, today).event("safety_flatten", actions=actions)
    log.info("safety flatten done", extra={"actions": actions})
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .reporting import write_summary
    from .state import reconstruct_trades

    cfg = _cfg(args)
    broker, data = _clients(cfg)
    days = args.days or cfg.reporting.summary_lookback_days
    start = now_ny().date() - dt.timedelta(days=days)
    orders = broker.orders("all", after=ny_dt(start, dt.time(0)))
    trades = reconstruct_trades(orders, cfg.execution.client_order_id_prefix)
    hist = [(d, e) for d, e in broker.equity_history() if d >= start]
    equity = pd.Series({ny_dt(d, dt.time(16)): e for d, e in hist}, dtype=float)
    bench = None
    try:
        closes = data.daily_closes(cfg.reporting.benchmark_symbol, start, now_ny().date())
        bench = pd.Series(closes.to_numpy(), index=[ny_dt(d, dt.time(16)) for d in closes.index])
    except Exception as exc:  # noqa: BLE001
        log.warning("benchmark unavailable", extra={"error": str(exc)[:200]})
    out = Path(cfg.reporting.reports_dir) / "summary"
    path = write_summary(out, trades, equity, bench, f"Paper account summary - last {days} days")
    print(f"summary written: {path}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from .backtest import report_backtest, run_backtest
    from .data import CachedMinuteBars
    from .live import load_event_days

    cfg = _cfg(args)
    if not cfg.backtest.enabled:
        log.info("backtest.enabled is false in config - nothing to do")
        return 0
    start = dt.date.fromisoformat(args.start or cfg.backtest.start)
    end = dt.date.fromisoformat(args.end or cfg.backtest.end)
    broker, data = _clients(cfg)
    sessions = broker.sessions(start - dt.timedelta(days=cfg.data.history_days), end)
    if end >= now_ny().date():
        sessions = [s for s in sessions if s.day < now_ny().date()]
    symbols = sorted(set(cfg.symbols) | {cfg.reporting.benchmark_symbol})
    minutes = CachedMinuteBars(data, cfg.data.cache_dir).load(symbols, [s.day for s in sessions])
    result = run_backtest(cfg, minutes, sessions, start, end, load_event_days(cfg.session.event_days_file))
    out = Path(cfg.reporting.reports_dir) / f"backtest-{start}-{end}"
    path = report_backtest(cfg, result, minutes, sessions, out)
    from .reporting import Recorder

    Recorder(out.parent, None).write_trades(result.trades, name=f"{out.name}-trades.csv")
    print(f"backtest report: {path}  ({len(result.trades)} trades)")
    return 0


def cmd_test_order(args: argparse.Namespace) -> int:
    """Plumbing test with ONE share. Default: a bracket priced far below the
    market (should not fill), then cancelled. --fill: a marketable bracket
    that fills during market hours, is held briefly, then closed at market.
    Deliberately bypasses the strategy; it still carries a stop and target."""
    import os

    from .execution import make_client_order_id
    from .risk import assert_order_invariants
    from .models import Direction
    from .strategy import round_to_tick

    cfg = _cfg(args)
    broker, data = _clients(cfg)
    sym = args.symbol
    gh = os.environ.get("GITHUB_ACTIONS") == "true"

    def notice(msg: str) -> None:
        log.info(msg)
        if gh:
            print(f"::notice title=ictbot test order::{msg}", flush=True)

    last = data.latest_trade_price(sym)
    if not last:
        raise ValueError(f"no recent price for {sym}")
    tick = cfg.execution.tick_size
    if args.fill:
        if not broker.clock().is_open:
            raise ValueError("market is closed - a filling test order needs regular trading hours")
        if any(p.symbol == sym for p in broker.positions()) or any(o.symbol == sym for o in broker.orders("open")):
            raise ValueError(f"{sym} already has a position or open order - refusing so the test cannot touch the bot's trades")
        q = data.latest_quote(sym)
        ref = q.ask if q else last
        entry = round_to_tick(ref * 1.001, tick, "up")  # marketable limit: fills now, caps slippage at ~0.1%
        stop = round_to_tick(entry * 0.995, tick, "down")
        target = round_to_tick(entry * 1.005, tick, "up")
    else:
        entry = round_to_tick(last * (1 - args.below_pct / 100), tick, "down")
        stop = round_to_tick(entry * 0.99, tick, "down")
        target = round_to_tick(entry * 1.02, tick, "up")
    assert_order_invariants(Direction.LONG, 1, entry, stop, target)
    stamp = now_ny().strftime("%H%M%S")
    coid = make_client_order_id("icbtest", now_ny().date(), sym, f"t{stamp}", "e")
    o = broker.submit_bracket(symbol=sym, side="buy", qty=1, limit_price=entry, take_profit=target, stop_loss=stop, tif="day", client_order_id=coid)
    notice(f"TEST ORDER accepted: {sym} BUY 1 limit {entry} (last {last}) stop {stop} target {target} status={o.status} legs={len(o.legs)}")
    if args.fill:
        deadline = time.monotonic() + 60
        cur = o
        while time.monotonic() < deadline:
            cur = broker.order_by_client_id(coid)
            if cur and cur.status == "filled":
                break
            time.sleep(2)
        if not cur or cur.status != "filled":
            broker.cancel(o.id)
            notice(f"TEST ORDER did not fill within 60s (status={cur.status if cur else 'unknown'}) - cancelled")
            return 1
        notice(f"TEST ORDER FILLED: bought 1 {sym} @ {cur.filled_avg_price} - stop and target legs active")
        time.sleep(args.hold_seconds)
        from .execution import ExecutionEngine

        ExecutionEngine(broker, cfg, sleep=time.sleep).flatten_all(now_ny().date(), "test_order_close", {sym})
        time.sleep(5)
        flats = [x for x in broker.orders("all", after=now_ny() - dt.timedelta(minutes=10)) if x.symbol == sym and x.side == "sell" and x.type == "market"]
        exit_px = flats[-1].filled_avg_price if flats else None
        pnl = (exit_px - cur.filled_avg_price) if exit_px else None
        left = [p for p in broker.positions() if p.symbol == sym]
        notice(f"TEST ORDER CLOSED: sold 1 {sym} @ {exit_px} | P&L {pnl if pnl is None else round(pnl, 2)} | position left: {'NONE' if not left else left[0].qty}")
        return 0
    if args.keep_open:
        log.info("keep_open set - order left working (DAY order, expires at the close if unfilled)")
        return 0
    time.sleep(args.cancel_after)
    broker.cancel(o.id)
    after = broker.order_by_client_id(coid)
    done = f"TEST ORDER cancelled after {args.cancel_after}s: final status={after.status if after else 'unknown'}"
    log.info(done)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::notice title=ictbot test order::{done}", flush=True)
    return 0


def cmd_reset_killswitch(args: argparse.Namespace) -> int:
    path = Path(args.config)
    today = now_ny().date().isoformat()
    text = path.read_text()
    new, n = re.subn(r"(?m)^(\s*drawdown_reset_date:\s*)(\S+)(.*)$", rf'\g<1>"{today}"\g<3>', text)
    if n != 1:
        print("could not find risk.drawdown_reset_date in config - edit it manually", file=sys.stderr)
        return 1
    path.write_text(new)
    print(f"risk.drawdown_reset_date set to {today}. Commit and push config.yaml so the GitHub workflow picks it up.")
    print("The drawdown peak will now be measured from today. Make sure you understand WHY the kill-switch fired first.")
    return 0


# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ictbot", description=DISCLAIMER)
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true", help="log signals, send no orders")
    r.add_argument("--ignore-start-window", action="store_true", help="skip the NY-time start gate (manual runs)")
    f = sub.add_parser("flatten")
    f.add_argument("--force", action="store_true", help="flatten immediately regardless of time")
    f.add_argument("--max-wait-minutes", type=int, default=25)
    f.add_argument("--dry-run", action="store_true")
    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int, default=None)
    b = sub.add_parser("backtest")
    b.add_argument("--start")
    b.add_argument("--end")
    sub.add_parser("reset-killswitch")
    t = sub.add_parser("test-order", help="place + cancel one far-from-market 1-share paper bracket")
    t.add_argument("--symbol", default="SPY")
    t.add_argument("--below-pct", type=float, default=10.0)
    t.add_argument("--cancel-after", type=int, default=120)
    t.add_argument("--keep-open", action="store_true")
    t.add_argument("--fill", action="store_true", help="really fill 1 share during market hours, then close it")
    t.add_argument("--hold-seconds", type=int, default=60)
    return p


COMMANDS = {"check": cmd_check, "run": cmd_run, "flatten": cmd_flatten, "report": cmd_report, "backtest": cmd_backtest, "reset-killswitch": cmd_reset_killswitch, "test-order": cmd_test_order}


def _gh_annotation(title: str, message: str) -> None:
    """Surface a failure reason on the GitHub Actions run page (secrets redacted)."""
    import os

    from .logging_setup import redact

    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title={title}::{redact(message)}", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg_for_logs = load_config(args.config)
        setup_logging(cfg_for_logs.reporting.logs_dir, args.log_level, run_name=args.cmd)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 3
    try:
        return COMMANDS[args.cmd](args)
    except LiveTradingRefused as exc:
        log.critical(f"REFUSED: {exc}")
        _gh_annotation("ictbot refused to start", str(exc))
        return 4
    except (ConfigError, ValueError) as exc:
        log.critical(f"configuration error: {exc}")
        _gh_annotation("ictbot configuration error", str(exc))
        return 3
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 130
    except Exception:  # noqa: BLE001
        log.exception("fatal error")
        try:
            from .alerts import Notifier

            Notifier(cfg_for_logs.alerts).send("error", f"fatal error in '{args.cmd}' - see workflow logs")
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
