"""Human-readable research report (markdown + plots) from results.json."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

HEADER = """> **Research only - paper trading, no orders placed.** Results are historical
> simulations with modelled costs. They are not predictions and not financial
> advice. A strategy surviving every check can still fail going forward.
"""


def pct(x: Any, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x * 100:.{digits}f}%"


def num(x: Any, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def _row(name: str, m: dict) -> str:
    return (f"| {name} | {pct(m.get('cagr'))} | {pct(m.get('monthly_geo_mean'))} | {num(m.get('sharpe'))} | {pct(m.get('max_drawdown'))} "
            f"| {pct(m.get('worst_month'))} | {m.get('n_trades', 'n/a')} |")


TABLE_HEAD = "| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |\n|---|---|---|---|---|---|---|"


def explore_markdown(res: dict) -> str:
    sp = res["splits"]
    lines = ["# Research report - explore stage", "", HEADER, "",
             f"- generated: `{res['generated_utc']}` - commit `{res['git_commit'][:10]}`",
             f"- train **{sp['train'][0]} -> {sp['train'][1]}** | validation **{sp['validation'][0]} -> {sp['validation'][1]}** | "
             f"test **{sp['test'][0]} -> {sp['test'][1]} (LOCKED, not loaded)**",
             f"- total parameter trials run: **{res['total_trials']}** (all counted in the multiple-testing corrections)",
             f"- data feed: `{res['data'].get('feed')}`; costs: half-spread per ETF + {res['costs']['open_slippage_bps']}bp open / "
             f"{res['costs']['stop_slippage_bps']}bp stop slippage, margin {pct(res['costs']['margin_rate'],1)}/yr", ""]
    lines += ["## Survivors (passed every pre-registered check)", "",
              ", ".join(f"**{s}**" for s in res["survivors"]) if res["survivors"] else "**None.** No strategy passed every check.", ""]

    lines += ["## Validation period (out-of-sample for parameter selection)", "", TABLE_HEAD]
    for name, b in res["benchmarks"].items():
        lines.append(_row(f"_{name}_", b["validation"]))
    for r in res["strategies"]:
        if "validation" in r:
            lines.append(_row(r["strategy"], r["validation"]))
    lines += ["", "## Walk-forward out-of-sample (re-selected every 6 months on the trailing 3 years)", "", TABLE_HEAD]
    for name, b in res["benchmarks"].items():
        lines.append(_row(f"_{name}_", b.get("walkforward_window", {})))
    for r in res["strategies"]:
        if "walkforward_oos" in r:
            lines.append(_row(r["strategy"], r["walkforward_oos"]))

    lines += ["", "## Robustness checks", "",
              "| strategy | trials | DSR (train) | PBO | neighbour ratio | null p | 2x-cost val Sharpe | WF choice stability | survives | failed checks |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["strategies"]:
        if "checks" not in r:
            lines.append(f"| {r['strategy']} | - | - | - | - | - | - | - | - | {r.get('skipped') or r.get('error')} |")
            continue
        failed = [k for k, v in r["checks"].items() if not v]
        lines.append(f"| {r['strategy']} | {r['n_trials']} | {num(r['dsr_train'].get('dsr'))} | {num(r['pbo_train'].get('pbo'))} | "
                     f"{num(r['sensitivity_train'].get('neighbour_ratio'))} | {num(r['null_test'].get('p_value'), 3)} | "
                     f"{num(r['cost_stress_2x_validation'].get('sharpe'))} | {pct(r['walkforward_choice_stability'], 0)} | "
                     f"{'YES' if r['survives'] else 'no'} | {', '.join(failed) or '-'} |")

    lines += ["", "## What it would take to hit 5-8% per month (leverage on walk-forward OOS returns)", "",
              "| strategy | Kelly leverage | best monthly geo at any leverage | 5%/mo: leverage | 5%/mo: hist max DD | 5%/mo: P(DD>50%) 1y | 8%/mo: leverage | 8%/mo: hist max DD |",
              "|---|---|---|---|---|---|---|---|"]
    for r in res["strategies"]:
        la = r.get("leverage_on_walkforward_oos") or {}
        if not la or "targets" not in la:
            continue
        t5, t8 = la["targets"].get("5%", {}), la["targets"].get("8%", {})

        def cell(t, k):
            return "unreachable" if not t.get("reachable_historically") else (num(t.get(k)) + "x" if k == "leverage_needed" else pct(t.get(k)))

        p50 = pct(t5.get("bootstrap_1y", {}).get("prob_dd_over_50")) if t5.get("reachable_historically") else "-"
        lines.append(f"| {r['strategy']} | {num(la.get('kelly_leverage'))}x | {pct(la.get('max_monthly_geo_any_leverage'))} | {cell(t5,'leverage_needed')} | "
                     f"{cell(t5,'hist_max_dd')} | {p50} | {cell(t8,'leverage_needed')} | {cell(t8,'hist_max_dd')} |")

    pf = res.get("portfolio") or {}
    if pf:
        lines += ["", f"## Combined portfolio ({pf['member_basis']})", "",
                  f"Members: {', '.join(pf['members'])} (causal inverse-volatility weights on walk-forward OOS returns).", "",
                  TABLE_HEAD, _row("portfolio", pf["walkforward_oos"]),
                  "", f"Adds value vs best single member ({pf['best_single']}, WF Sharpe {num(pf['best_single_wf_sharpe'])}): **{'yes' if pf['adds_value'] else 'no'}**"]

    lines += ["", "## Per-strategy detail", ""]
    for r in res["strategies"]:
        if "checks" not in r:
            continue
        lines += [f"### {r['strategy']} ({r['family']})", "", f"_Hypothesis:_ {r['hypothesis']}", "",
                  f"- selected on train: `{json.dumps(r['selected_params'])}`",
                  f"- train: CAGR {pct(r['train'].get('cagr'))}, Sharpe {num(r['train'].get('sharpe'))}, max DD {pct(r['train'].get('max_drawdown'))}, "
                  f"trades {r['train'].get('n_trades')}, time in market {pct(r['train'].get('time_in_market'),0)}, cost drag {pct(r['train'].get('annual_cost_drag'))}/yr",
                  f"- share of trials with positive train Sharpe: {pct(r['sensitivity_train'].get('share_of_trials_positive'),0)}",
                  "- regimes (train+val, ann. return): " + ", ".join(f"{k}: {pct(v['ann_return'],1)}" for k, v in r["regimes_train_val"].items() if k != "by_year"),
                  "- by year: " + ", ".join(f"{k}: {pct(v,1)}" for k, v in r["regimes_train_val"].get("by_year", {}).items()), ""]
    return "\n".join(lines)


def plot_equity(daily_returns_csv: Path, out_png: Path, columns_suffix: str = "__wf_oos") -> Path | None:
    if not daily_returns_csv.exists():
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.read_csv(daily_returns_csv, index_col=0, parse_dates=True)
    cols = [c for c in df.columns if c.endswith(columns_suffix)]
    if not cols:
        return None
    fig, ax = plt.subplots(figsize=(11, 5))
    for c in cols:
        s = df[c].dropna()
        ax.plot(s.index, (1 + s).cumprod(), label=c.replace(columns_suffix, ""), linewidth=1.2)
    ax.set_yscale("log")
    ax.set_title("Walk-forward out-of-sample equity (log scale, net of modelled costs)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return out_png


def write_explore_report(out_dir: Path) -> Path:
    res = json.loads((out_dir / "results.json").read_text())
    md = explore_markdown(res)
    png = plot_equity(out_dir / "daily_returns.csv.gz", out_dir / "walkforward_equity.png")
    if png:
        md += f"\n\n![walk-forward equity]({png.name})\n"
    path = out_dir / "REPORT.md"
    path.write_text(md)
    return path
