"""Baseline: the EXISTING ICT strategy, exactly as configured in config.yaml,
run through the existing 1-minute-bar backtester on SIP data for the train and
validation periods only (the test period is never touched here).

It is a single pre-registered configuration (no tuning), so it carries no
multiple-testing penalty - but it also gets no help from parameter search.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
from pathlib import Path

import pandas as pd

from ..backtest import run_backtest
from ..config import BotConfig
from ..data import CachedMinuteBars
from ..reporting import compute_metrics, per_setup_stats
from . import validation as V
from .metrics import summarize
from .runner import _jsonable, git_commit

log = logging.getLogger(__name__)


def run_ict_baseline(cfg: BotConfig, broker, data_source, out_dir: Path, start: dt.date, end: dt.date, cache_dir: str) -> dict:
    splits = V.Splits.default(end)
    end = min(end, splits.validation[1])  # never the test period
    cfg = dataclasses.replace(cfg, backtest=dataclasses.replace(cfg.backtest, start=str(start), end=str(end)))
    sessions = broker.sessions(start - dt.timedelta(days=cfg.data.history_days), end)
    symbols = sorted(set(cfg.symbols) | {cfg.reporting.benchmark_symbol})
    minutes = CachedMinuteBars(data_source, cache_dir).load(symbols, [s.day for s in sessions])
    events = {}
    res = run_backtest(cfg, minutes, sessions, start, end, events)
    eq = res.equity
    daily_eq = eq.groupby([ts.date() for ts in eq.index]).last()
    daily_eq.index = pd.DatetimeIndex(daily_eq.index)
    rets = daily_eq.pct_change().fillna(0.0)
    out = {"stage": "ict_baseline", "git_commit": git_commit(), "config_symbols": list(cfg.symbols), "feed": "sip",
           "train": summarize(V.cut(rets, *splits.train)), "validation": summarize(V.cut(rets, *splits.validation)),
           "trade_metrics_train": compute_metrics([t for t in res.trades if t.entry_time.date() <= splits.train[1]]),
           "trade_metrics_validation": compute_metrics([t for t in res.trades if splits.validation[0] <= t.entry_time.date() <= splits.validation[1]]),
           "per_setup": per_setup_stats(res.trades).to_dict("records"), "n_trades": len(res.trades), "signals_evaluated": res.signals,
           "trading_days": len(res.days)}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(_jsonable(out), indent=1))
    rets.to_frame("ict_baseline").to_csv(out_dir / "daily_returns.csv.gz")
    pd.DataFrame([dataclasses.asdict(t) for t in res.trades]).to_csv(out_dir / "trades.csv", index=False)
    return out
