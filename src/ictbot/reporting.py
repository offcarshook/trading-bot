"""Structured logs (CSV/JSONL), performance metrics, journals, equity plots."""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .models import SignalRecord, TradeRecord

log = logging.getLogger(__name__)
TRADING_DAYS = 252
DISCLAIMER = "_Educational paper-trading experiment. Not financial advice. Past (simulated) results do not predict future results._"


def _jsonable(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "value"):
        return v.value
    return v


# --------------------------------------------------------------------------- #
# Append-only structured logs
# --------------------------------------------------------------------------- #


class Recorder:
    SIGNAL_FIELDS = [f.name for f in dataclasses.fields(SignalRecord)]
    TRADE_FIELDS = [f.name for f in dataclasses.fields(TradeRecord)]

    def __init__(self, reports_dir: str | Path, day: dt.date | None = None) -> None:
        self.root = Path(reports_dir)
        self.day_dir = self.root / (day.isoformat() if day else "misc")
        self.day_dir.mkdir(parents=True, exist_ok=True)
        self._seen: set[tuple] = set()

    def _append_csv(self, path: Path, fields: list[str], row: dict[str, Any]) -> None:
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            if new:
                w.writeheader()
            w.writerow({k: (json.dumps(v, default=_jsonable) if isinstance(v, (dict, list, tuple)) else _jsonable(v)) for k, v in row.items()})

    def signal(self, rec: SignalRecord, dedupe: bool = True) -> None:
        key = (rec.symbol, rec.setup_id, rec.stage, rec.decision, rec.reason)
        if dedupe and rec.setup_id and key in self._seen:
            return
        self._seen.add(key)
        self._append_csv(self.day_dir / "signals.csv", self.SIGNAL_FIELDS, dataclasses.asdict(rec))

    def event(self, kind: str, **data: Any) -> None:
        line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "kind": kind, **data}
        with (self.day_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, default=_jsonable) + "\n")

    def write_trades(self, trades: Iterable[TradeRecord], name: str = "trades.csv") -> Path:
        path = self.day_dir / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=self.TRADE_FIELDS)
            w.writeheader()
            for t in trades:
                w.writerow({k: _jsonable(v) for k, v in dataclasses.asdict(t).items()})
        return path


# --------------------------------------------------------------------------- #
# MAE / MFE
# --------------------------------------------------------------------------- #


def mae_mfe(trade: TradeRecord, bars_1m: pd.DataFrame) -> tuple[float | None, float | None]:
    """Maximum adverse / favourable excursion in R using 1m bars inside the trade."""
    if bars_1m is None or bars_1m.empty or trade.exit_time is None or not math.isfinite(trade.stop_price):
        return None, None
    risk = abs(trade.entry_price - trade.stop_price)
    if risk <= 0:
        return None, None
    w = bars_1m[(bars_1m.index >= trade.entry_time.replace(second=0, microsecond=0)) & (bars_1m.index <= trade.exit_time)]
    if w.empty:
        return None, None
    if trade.direction == "long":
        mae = (trade.entry_price - w["low"].min()) / risk
        mfe = (w["high"].max() - trade.entry_price) / risk
    else:
        mae = (w["high"].max() - trade.entry_price) / risk
        mfe = (trade.entry_price - w["low"].min()) / risk
    return round(max(0.0, float(mae)), 3), round(max(0.0, float(mfe)), 3)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float(((peak - equity) / peak).max() * 100.0)


def ratio_metrics(daily_returns: pd.Series) -> tuple[float | None, float | None]:
    r = daily_returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return None, None
    sharpe = r.mean() / r.std(ddof=1) * math.sqrt(TRADING_DAYS)
    downside = r[r < 0]
    dd = math.sqrt((downside**2).sum() / len(r)) if len(downside) else 0.0
    sortino = r.mean() / dd * math.sqrt(TRADING_DAYS) if dd > 0 else None
    return round(float(sharpe), 3), (round(float(sortino), 3) if sortino is not None else None)


def compute_metrics(trades: list[TradeRecord], equity: pd.Series | None = None) -> dict[str, Any]:
    closed = [t for t in trades if t.exit_time is not None]
    pnl = np.array([t.pnl - t.fees for t in closed], dtype=float)
    rs = np.array([t.r_multiple for t in closed if t.r_multiple is not None and math.isfinite(t.r_multiple)], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    out: dict[str, Any] = {
        "trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "win_rate": round(len(wins) / len(pnl), 4) if len(pnl) else None,
        "avg_r": round(float(rs.mean()), 3) if len(rs) else None,
        "expectancy_r": round(float(rs.mean()), 3) if len(rs) else None,
        "expectancy_usd": round(float(pnl.mean()), 2) if len(pnl) else None,
        "net_pnl": round(float(pnl.sum()), 2),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if len(losses) and losses.sum() < 0 else (math.inf if len(wins) else None),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
        "avg_mae_r": _mean([t.mae_r for t in closed]),
        "avg_mfe_r": _mean([t.mfe_r for t in closed]),
        "sharpe": None,
        "sortino": None,
        "max_drawdown_pct": None,
    }
    if equity is not None and len(equity) > 1:
        daily = equity.groupby(pd.Index([pd.Timestamp(i).date() for i in equity.index])).last()
        out["sharpe"], out["sortino"] = ratio_metrics(daily.pct_change())
        out["max_drawdown_pct"] = round(max_drawdown_pct(equity), 3)
    return out


def per_setup_stats(trades: list[TradeRecord]) -> pd.DataFrame:
    closed = [t for t in trades if t.exit_time is not None]
    if not closed:
        return pd.DataFrame(columns=["setup", "trades", "win_rate", "avg_r", "net_pnl"])
    df = pd.DataFrame([{"setup": t.setup_tag, "pnl": t.pnl - t.fees, "r": t.r_multiple} for t in closed])
    g = df.groupby("setup")
    return pd.DataFrame(
        {"trades": g.size(), "win_rate": g["pnl"].apply(lambda s: round((s > 0).mean(), 3)), "avg_r": g["r"].mean().round(3), "net_pnl": g["pnl"].sum().round(2)}
    ).reset_index()


def _mean(values: list[float | None]) -> float | None:
    v = [x for x in values if x is not None and math.isfinite(x)]
    return round(sum(v) / len(v), 3) if v else None


# --------------------------------------------------------------------------- #
# Markdown + plots
# --------------------------------------------------------------------------- #


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return "inf" if math.isinf(v) else f"{v:,.4g}" if abs(v) < 1000 else f"{v:,.2f}"
    return str(v)


def metrics_table(m: dict[str, Any]) -> str:
    rows = ["| metric | value |", "|---|---|"] + [f"| {k} | {_fmt(v)} |" for k, v in m.items()]
    return "\n".join(rows)


def df_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_"
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns)
    body = "\n".join("| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False))
    return head + "\n" + body


def trades_table(trades: list[TradeRecord]) -> str:
    if not trades:
        return "_no trades_"
    cols = ["symbol", "direction", "setup_tag", "entry_time", "entry_price", "qty", "stop_price", "target_price", "exit_price", "exit_reason", "pnl", "r_multiple", "mae_r", "mfe_r"]
    df = pd.DataFrame([{c: getattr(t, c) for c in cols} for t in trades])
    df["entry_time"] = df["entry_time"].map(lambda x: x.strftime("%m-%d %H:%M") if x else "")
    return df_table(df)


def signal_summary(signals_csv: Path) -> str:
    if not signals_csv.exists():
        return "_no signals logged_"
    df = pd.read_csv(signals_csv)
    if df.empty:
        return "_no signals logged_"
    counts = Counter(zip(df["decision"], df["reason"]))
    rows = ["| decision | reason | count |", "|---|---|---|"] + [f"| {d} | {r} | {n} |" for (d, r), n in counts.most_common()]
    return "\n".join(rows)


def write_journal(
    recorder: Recorder,
    day: dt.date,
    trades: list[TradeRecord],
    *,
    context: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> Path:
    path = recorder.day_dir / "journal.md"
    lines = [
        f"# Trading journal - {day.isoformat()} (PAPER)",
        "",
        DISCLAIMER,
        "",
        "## Context",
        "",
        "```json",
        json.dumps(context, indent=2, default=_jsonable),
        "```",
        "",
        "## Signals (including skipped, with reasons)",
        "",
        signal_summary(recorder.day_dir / "signals.csv"),
        "",
        "## Trades",
        "",
        trades_table(trades),
        "",
        "## Day metrics",
        "",
        metrics_table(metrics or compute_metrics(trades)),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def plot_equity(equity: pd.Series, benchmark: pd.Series | None, path: Path, title: str) -> Path | None:
    if equity is None or len(equity) < 2:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(equity.index, equity.values, label="strategy equity", linewidth=1.6)
    if benchmark is not None and len(benchmark) > 1:
        b = benchmark.reindex(equity.index, method="ffill").dropna()
        if len(b):
            scaled = b / b.iloc[0] * equity.loc[b.index[0]]
            ax.plot(scaled.index, scaled.values, label="buy & hold SPY (scaled)", linewidth=1.2, alpha=0.8)
    ax.set_title(title)
    ax.set_ylabel("equity ($)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def write_summary(
    out_dir: Path,
    trades: list[TradeRecord],
    equity: pd.Series | None,
    benchmark: pd.Series | None,
    title: str,
    extra_sections: dict[str, str] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    m = compute_metrics(trades, equity)
    if benchmark is not None and len(benchmark) > 1 and equity is not None and len(equity) > 1:
        b = benchmark.reindex(equity.index, method="ffill").dropna()
        if len(b) > 1:
            m["benchmark_return_pct"] = round(float((b.iloc[-1] / b.iloc[0] - 1) * 100), 3)
        m["strategy_return_pct"] = round(float((equity.iloc[-1] / equity.iloc[0] - 1) * 100), 3)
    plot = plot_equity(equity, benchmark, out_dir / "equity_curve.png", title) if equity is not None else None
    lines = [f"# {title}", "", DISCLAIMER, "", "## Performance", "", metrics_table(m), "", "## Per-setup statistics", "", df_table(per_setup_stats(trades)), ""]
    if plot:
        lines += ["## Equity curve vs buy-and-hold SPY", "", f"![equity]({plot.name})", ""]
    for heading, body in (extra_sections or {}).items():
        lines += [f"## {heading}", "", body, ""]
    lines += ["## Trades", "", trades_table(trades), ""]
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps(m, indent=2, default=_jsonable))
    return path
