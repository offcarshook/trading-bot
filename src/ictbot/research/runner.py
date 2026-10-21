"""Staged research pipeline.

STAGE "explore"  (repeatable)
  * data is TRUNCATED at the end of the validation period - test data is not
    even loaded into the strategies
  * every pre-registered parameter trial is run once
  * parameters are selected on TRAIN only (objective: train Sharpe after costs)
  * validation-period metrics, walk-forward OOS (train+validation), DSR, PBO,
    sensitivity, cost stress, null test, regimes and leverage analysis are
    computed for the train-selected configuration
  * pre-registered survival criteria decide which strategies are candidates

STAGE "test"  (locked)
  * only configurations listed in research/frozen.json can be evaluated
  * every access is appended to research_results/test_access_log.json with the
    git commit, so the number of looks at the test period is auditable
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import math
import os
import subprocess
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import validation as V
from . import strategies as _strategies
from .base import IMPORT_ERRORS, ResearchData, StrategyResult, StrategySpec, load_all_strategies
from .costs import CostModel
from .engine import run_weights
from .metrics import TRADING_DAYS, periods_per_year, sharpe, summarize

log = logging.getLogger(__name__)

# Pre-registered survival criteria (set BEFORE any real-data run; changing them
# after seeing results must be recorded in the research log).
CRITERIA = {
    "validation_sharpe_min": 0.5,
    "validation_cagr_min": 0.0,
    "walkforward_oos_sharpe_min": 0.5,
    "dsr_train_min": 0.90,
    "pbo_max": 0.50,
    "null_p_max": 0.10,
    "cost_stress_2x_validation_sharpe_min": 0.0,
    "neighbour_ratio_min": 0.5,
    "min_trades_train": 30,
}
MONTHLY_TARGETS = (0.05, 0.08)


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return os.environ.get("GITHUB_SHA", "unknown")


def _jsonable(o: Any) -> Any:
    if isinstance(o, (np.floating,)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (dt.date, pd.Timestamp)):
        return str(o)
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def params_key(p: dict) -> str:
    return json.dumps(p, sort_keys=True, default=str)


# --------------------------------------------------------------------------- #
# Benchmarks
# --------------------------------------------------------------------------- #


def benchmarks(data: ResearchData, costs: CostModel) -> dict[str, StrategyResult]:
    out = {}
    dates = data.dates()
    if "SPY" in data.daily:
        w = pd.DataFrame({"SPY": 1.0}, index=dates)
        out["buy_hold_SPY"] = run_weights(data, w, costs)
    if "QQQ" in data.daily:
        out["buy_hold_QQQ"] = run_weights(data, pd.DataFrame({"QQQ": 1.0}, index=dates), costs)
    if "SPY" in data.daily and "IEF" in data.daily:
        w = pd.DataFrame({"SPY": 0.6, "IEF": 0.4}, index=dates)
        per = pd.Series(dates.to_period("M"), index=dates)
        first_of_month = per.ne(per.shift(1))
        w = w.where(first_of_month, np.nan)  # all-NaN rows = hold (drift) -> true monthly rebalance
        out["60_40_SPY_IEF"] = run_weights(data, w, costs)
    return out


def data_quality(data: ResearchData) -> dict:
    """Per-symbol coverage and sanity checks (bad adjustments show up as huge jumps)."""
    all_dates = data.dates()
    out = {}
    for sym, df in data.daily.items():
        r = df["close"].pct_change().abs()
        first = df.index.min()
        expected = all_dates[all_dates >= first]
        out[sym] = {"first": str(first.date()), "last": str(df.index.max().date()), "days": int(len(df)),
                    "missing_sessions_after_first": int(len(expected.difference(df.index))),
                    "max_abs_daily_return": float(r.max()) if len(r) else None,
                    "days_abs_return_over_15pct": [str(d.date()) for d in r[r > 0.15].index][:10],
                    "zero_volume_days": int((df["volume"] <= 0).sum())}
    for sym, df in data.intraday.items():
        out[f"{sym}_5m"] = {"bars": int(len(df)), "sessions": int(len(set(df.index.date))) if len(df) else 0}
    return out


def splits_for(spec: StrategySpec, data: ResearchData) -> V.Splits:
    data_end = data.dates().max().date()
    if spec.split_mode != "adaptive":
        return V.Splits.default(data_end)
    frames = [data.crypto.get(s) if s in data.crypto else data.daily.get(s) for s in spec.symbols]
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        return V.Splits.default(data_end)
    first = max(f.index.min() for f in frames).date()  # all symbols available (conservative)
    last = min(f.index.max() for f in frames).date()
    return V.Splits.adaptive(first, last)


def crypto_benchmark(data: ResearchData, splits: V.Splits, costs: CostModel) -> dict:
    if "BTC/USD" not in data.crypto:
        return {}
    cv = data.crypto_view()
    res = run_weights(cv, pd.DataFrame({"BTC/USD": 1.0}, index=cv.dates()), costs)
    return {"buy_hold_BTC": {"validation": summarize(res.slice(*splits.validation).returns),
                             "walkforward_window": summarize(V.cut(res.returns, splits.train[0] + dt.timedelta(days=730), splits.validation[1]))}}


def ann_periods(spec: StrategySpec, returns: pd.Series) -> int:
    """Rows per year for annualizing: stock strategies keep the fixed 252 (unchanged reports); adaptive
    (crypto, one row per calendar day) use the observed frequency, as metrics.summarize does."""
    return TRADING_DAYS if spec.split_mode != "adaptive" else int(round(periods_per_year(returns)))


# --------------------------------------------------------------------------- #
# Null test
# --------------------------------------------------------------------------- #


def engine_replay(spec: StrategySpec, data: ResearchData, params: dict, costs: CostModel,
                  expected: pd.Series) -> tuple[ResearchData, pd.DataFrame, dict] | None:
    """(view, decision frame, keyword args) of the strategy's run_weights call, recorded by re-running it;
    None unless exactly one call reproduces ``expected`` bit for bit (trade strategies, returns built from
    several runs). StrategyResult.weights cannot be replayed faithfully: the engine reports decisions
    forward-filled (crypto, tsmom) and letfrot the drifted book, both without the all-NaN HOLD rows, and
    crypto trades its own hole-filled crypto view, not ``data``."""
    calls = []

    def record(view, weights, c, **kw):
        res = run_weights(view, weights, c, **kw)
        calls.append((view, weights, kw, res.returns))
        return res

    fn = getattr(spec.run_fn, "func", spec.run_fn)
    own = sys.modules.get(getattr(fn, "__module__", ""))
    mods = [m for k, m in list(sys.modules.items()) if (k.startswith(f"{_strategies.__name__}.") or m is own)
            and getattr(m, "run_weights", None) is run_weights]
    for m in mods:
        m.run_weights = record
    try:
        spec.run(data, params, costs)
    except Exception:  # noqa: BLE001 - no replay -> the caller falls back
        log.exception("null replay failed", extra={"strategy": spec.name})
        return None
    finally:
        for m in mods:
            m.run_weights = run_weights
    hits = [c for c in calls if c[3].equals(expected)]
    return hits[0][:3] if len(hits) == 1 else None


def null_test(spec: StrategySpec, data: ResearchData, best: StrategyResult, params: dict, costs: CostModel,
              start: dt.date, end: dt.date, periods: int) -> dict:
    """Is the timing of the selected configuration better than random timing over [start, end]?

    * "decision_shift" (strategies whose decision frame has HOLD rows: crypto, tsmom, letfrot): the
      frame the strategy really sent to run_weights - decision rows plus all-NaN hold rows - is
      circularly shifted (window row 0 = the decision in force at ``start``) and replayed on the
      strategy's own view (crypto: its hole-filled crypto view, identical prices) with its own band /
      engine arguments. A shifted run trades on as many rows as the strategy, at shifted dates, and
      holds the drifted book in between.
    * "position_shift" (dense frames, or no exact replay): StrategyResult.weights (decisions
      forward-filled) shifted and re-targeted EVERY row on ``data`` (adaptive: its crypto view) with
      band = notes["band"] (0 if absent), as before.
    * "block_bootstrap_mean" for trade strategies (no weights): H0 mean return <= 0."""
    actual = V.cut(best.returns, start, end)
    if best.weights is None:
        null = V.mean_return_test(actual)
        null["method"] = "block_bootstrap_mean"
        return null
    view, wts, kw, method = data, best.weights, {"band": float(best.notes.get("band", 0.0))}, "position_shift"
    rep = engine_replay(spec, data, params, costs, best.returns)
    if rep is not None:
        dec = rep[1][[c for c in rep[1].columns if c in rep[0].daily]].reindex(best.returns.index)
        vals = dec.to_numpy(float)
        hold = np.isnan(vals).all(axis=1)
        win = (dec.index >= pd.Timestamp(start)) & (dec.index <= pd.Timestamp(end))
        if hold[win].any() or spec.split_mode == "adaptive":
            view, kw = rep[0], rep[2]
            wts = dec
            if hold[win].any():
                method = "decision_shift"
                i0 = int(np.argmax(win))
                last = np.maximum.accumulate(np.where(hold, -1, np.arange(len(dec))))[i0]
                wts = dec.copy()
                wts.iloc[i0] = np.nan_to_num(vals[last]) if last >= 0 else 0.0
    elif spec.split_mode == "adaptive":
        view = data.crypto_view()
    tv = wts[(wts.index >= pd.Timestamp(start)) & (wts.index <= pd.Timestamp(end))]

    def rerun(w: pd.DataFrame) -> pd.Series:
        return V.cut(run_weights(view, w, costs, **kw).returns, start, end)

    null = V.position_shift_null(tv, rerun, sharpe(actual, periods), n_shifts=100, periods=periods)
    null.update(method=method, replayed=rep is not None, decision_rows=int((~tv.isna().all(axis=1)).sum()), rows=int(len(tv)))
    return null


# --------------------------------------------------------------------------- #
# Explore one strategy
# --------------------------------------------------------------------------- #


def explore_strategy(spec: StrategySpec, data: ResearchData, splits: V.Splits, costs: CostModel, labels: pd.Series,
                     run_null: bool = True, wf_train_years: int = 3) -> dict:
    t0 = time.time()
    trials = spec.trials()
    tr_s, tr_e = splits.train
    va_s, va_e = splits.validation
    trial_rows, full_returns, results = [], {}, {}
    for p in trials:
        try:
            res = spec.run(data, p, costs)
        except Exception as exc:  # noqa: BLE001 - a broken trial is recorded, not fatal
            log.exception("trial failed", extra={"strategy": spec.name, "params": p})
            trial_rows.append({"params": p, "error": str(exc)[:300]})
            continue
        k = params_key(p)
        results[k] = res
        full_returns[k] = res.returns
        tr = res.slice(tr_s, tr_e)
        trial_rows.append({"params": p, "train_sharpe": sharpe(tr.returns, ann_periods(spec, res.returns)), "train_n_trades": tr.n_trades,
                           "train_cagr": summarize(tr.returns).get("cagr")})
    ok = [r for r in trial_rows if "error" not in r]
    if not ok:
        return {"strategy": spec.name, "error": "all trials failed", "trials": trial_rows}
    scores = [r["train_sharpe"] for r in ok]
    best_row = ok[int(np.nanargmax(scores))]
    bk = params_key(best_row["params"])
    best = results[bk]
    ppy = ann_periods(spec, best.returns)
    tr, va = best.slice(tr_s, tr_e), best.slice(va_s, va_e)
    train_m = summarize(tr.returns, tr.exposure, tr.turnover, tr.n_trades, tr.costs)
    val_m = summarize(va.returns, va.exposure, va.turnover, va.n_trades, va.costs)

    train_matrix = pd.DataFrame({k: V.cut(s, tr_s, tr_e) for k, s in full_returns.items()})
    dsr = V.deflated_sharpe(V.cut(best.returns, tr_s, tr_e), [sharpe(train_matrix[c]) / math.sqrt(252) for c in train_matrix], len(train_matrix.columns),
                            periods=ppy)
    pbo = V.pbo_cscv(train_matrix) if train_matrix.shape[1] > 1 else {"pbo": None, "reason": "single trial"}
    sens = V.sensitivity([r["params"] for r in ok], scores, spec.param_grid)
    wf = V.walk_forward({k: V.cut(s, tr_s, va_e) for k, s in full_returns.items()}, tr_s, va_e, train_years=wf_train_years, step_months=6,
                        objective=partial(sharpe, periods=ppy))
    wf_m = summarize(wf["oos_returns"])

    stressed = spec.run(data, best_row["params"], costs.stressed(2.0))
    stress_val = summarize(stressed.slice(va_s, va_e).returns)

    null = {"p_value": None}
    if run_null:
        try:
            null = null_test(spec, data, best, best_row["params"], costs, tr_s, va_e, ppy)
        except Exception as exc:  # noqa: BLE001 - recorded (fails the null check), the rest of the report stands
            log.exception("null test failed", extra={"strategy": spec.name})
            null = {"p_value": None, "error": f"{type(exc).__name__}: {exc}"[:300]}

    if spec.split_mode == "adaptive" and len(labels):  # SPY's last label carries over weekends / holidays (still lagged)
        labels = labels.reindex(labels.index.union(best.returns.index)).ffill()
    regimes = V.regime_breakdown(V.cut(best.returns, tr_s, va_e), labels, periods=ppy)
    # exposure of whichever trial walk-forward picked for each block, so margin
    # interest is only charged on days the strategy actually holds positions
    wf_expo = []
    for ch in wf["choices"]:
        e = results[ch["chosen"]].exposure
        wf_expo.append(e[(e.index >= pd.Timestamp(ch["from"])) & (e.index <= pd.Timestamp(ch["to"]))])
    wf_exposure = pd.concat(wf_expo) if wf_expo else None
    lev_wf = V.leverage_analysis(wf["oos_returns"], MONTHLY_TARGETS, costs.margin_rate, exposure=wf_exposure, periods=ppy) if len(wf["oos_returns"]) > 60 else {}

    c = CRITERIA
    checks = {
        "validation_sharpe": val_m.get("sharpe", 0) >= c["validation_sharpe_min"],
        "validation_cagr": val_m.get("cagr", -1) > c["validation_cagr_min"],
        "walkforward_oos_sharpe": wf_m.get("sharpe", 0) >= c["walkforward_oos_sharpe_min"],
        "dsr_train": (dsr.get("dsr") or 0) >= c["dsr_train_min"],
        "pbo": pbo.get("pbo") is None or pbo["pbo"] <= c["pbo_max"],
        "null_test": null.get("p_value") is not None and null["p_value"] <= c["null_p_max"],
        "cost_stress_2x": stress_val.get("sharpe", -1) >= c["cost_stress_2x_validation_sharpe_min"],
        "neighbourhood": sens.get("neighbour_ratio") is None or sens["neighbour_ratio"] >= c["neighbour_ratio_min"],
        "enough_trades": train_m.get("n_trades", 0) >= c["min_trades_train"],
    }
    return {
        "strategy": spec.name, "family": spec.family, "hypothesis": spec.hypothesis, "n_trials": len(trials),
        "splits": splits.as_dict(), "split_mode": spec.split_mode,
        "n_failed_trials": len(trial_rows) - len(ok), "selected_params": best_row["params"],
        "train": train_m, "validation": val_m, "walkforward_oos": wf_m, "walkforward_choices": wf["choices"],
        "walkforward_choice_stability": wf["most_common_choice_share"], "dsr_train": dsr, "pbo_train": pbo,
        "sensitivity_train": sens, "cost_stress_2x_validation": stress_val, "null_test": null, "regimes_train_val": regimes,
        "leverage_on_walkforward_oos": lev_wf, "checks": checks, "survives": all(checks.values()),
        "trials": trial_rows, "seconds": round(time.time() - t0, 1),
        "_series": {"best_full": best.returns, "wf_oos": wf["oos_returns"], "wf_exposure": wf_exposure},
    }


# --------------------------------------------------------------------------- #
# Portfolio of survivors (returns-level, causal inverse-vol weights)
# --------------------------------------------------------------------------- #


def inverse_vol_combo(series: dict[str, pd.Series], lookback: int = 126) -> pd.Series:
    df = pd.DataFrame(series).fillna(0.0)
    vol = df.rolling(lookback, min_periods=40).std().shift(1)
    inv = 1.0 / vol.replace(0, np.nan)
    w = inv.div(inv.sum(axis=1), axis=0).fillna(1.0 / df.shape[1])
    return (w * df).sum(axis=1)


# --------------------------------------------------------------------------- #
# Stage drivers
# --------------------------------------------------------------------------- #


def run_explore(data_full: ResearchData, out_dir: Path, only: list[str] | None = None, run_null: bool = True,
                costs: CostModel | None = None) -> dict:
    costs = costs or CostModel()
    data_end = data_full.dates().max().date()
    splits = V.Splits.default(data_end)
    data = data_full.truncate(splits.validation[1])  # <-- TEST PERIOD LOCKED OUT
    assert data.dates().max() <= pd.Timestamp(splits.validation[1])
    specs = load_all_strategies()
    if only:
        specs = {k: v for k, v in specs.items() if k in only}
    labels = V.regime_labels(data.daily["SPY"]["close"]) if "SPY" in data.daily else pd.Series(dtype=str)

    bench, bench_series = {}, {}
    for name, res in benchmarks(data, costs).items():
        bench_series[f"_bench_{name}"] = {"wf_oos": V.cut(res.returns, dt.date(splits.train[0].year + 3, 1, 1), splits.validation[1])}
        bench[name] = {"train": summarize(res.slice(*splits.train).returns), "validation": summarize(res.slice(*splits.validation).returns),
                       "walkforward_window": summarize(V.cut(res.returns, dt.date(splits.train[0].year + 3, 1, 1), splits.validation[1]))}

    reports, series = [], dict(bench_series)
    for name, spec in specs.items():
        if spec.uses_intraday and not any(len(v) for v in data.intraday.values()):
            reports.append({"strategy": name, "skipped": "no intraday data loaded"})
            continue
        sp = splits_for(spec, data_full)
        data_s = data if spec.split_mode != "adaptive" else data_full.truncate(sp.validation[1])  # <-- its test period locked out
        log.info("exploring", extra={"strategy": name, "trials": len(spec.trials()), "splits": sp.as_dict()})
        try:
            rep = explore_strategy(spec, data_s, sp, costs, labels, run_null=run_null, wf_train_years=3 if spec.split_mode != "adaptive" else 2)
            if spec.split_mode == "adaptive":
                rep["benchmarks_own_splits"] = crypto_benchmark(data_s, sp, costs)
        except Exception as exc:  # noqa: BLE001 - one broken strategy is recorded in the report, the run goes on
            log.exception("strategy failed", extra={"strategy": name})
            reports.append({"strategy": name, "family": spec.family, "split_mode": spec.split_mode, "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        series[name] = rep.pop("_series", {})
        reports.append(rep)
        log.info("explored", extra={"strategy": name, "survives": rep.get("survives"), "val_sharpe": rep.get("validation", {}).get("sharpe"),
                                    "wf_sharpe": rep.get("walkforward_oos", {}).get("sharpe"), "seconds": rep.get("seconds")})

    survivors = [r["strategy"] for r in reports if r.get("survives")]
    ranked = sorted([r for r in reports if "walkforward_oos" in r], key=lambda r: r["walkforward_oos"].get("sharpe", -9), reverse=True)
    combo_names = survivors if len(survivors) >= 2 else [r["strategy"] for r in ranked[:3] if r["walkforward_oos"].get("sharpe", 0) > 0]
    portfolio = {}
    if len(combo_names) >= 2:
        combo = inverse_vol_combo({n: series[n]["wf_oos"] for n in combo_names})
        best_single = max(combo_names, key=lambda n: sharpe(series[n]["wf_oos"]))
        portfolio = {"members": combo_names, "member_basis": "survivors" if len(survivors) >= 2 else "top walk-forward (NOT survivors)",
                     "walkforward_oos": summarize(combo), "best_single": best_single,
                     "best_single_wf_sharpe": sharpe(series[best_single]["wf_oos"]),
                     "adds_value": sharpe(combo) > sharpe(series[best_single]["wf_oos"]),
                     "leverage": V.leverage_analysis(combo, MONTHLY_TARGETS, costs.margin_rate),
                     "bootstrap_1y_unlevered": V.bootstrap_summary(combo, n_sims=1000)}
        series["_portfolio"] = {"wf_oos": combo}

    result = {
        "stage": "explore", "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "git_commit": git_commit(),
        "splits": splits.as_dict(), "test_period_loaded": False, "costs": dataclasses.asdict(costs), "criteria": CRITERIA,
        "data": {k: v for k, v in data_full.meta.items() if k != "manifests"}, "data_manifests": data_full.meta.get("manifests", []),
        "data_quality": data_quality(data_full), "benchmarks": bench, "strategies": reports, "survivors": survivors, "portfolio": portfolio,
        "total_trials": int(sum(r.get("n_trials", 0) for r in reports)),
        "strategy_import_errors": dict(IMPORT_ERRORS),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(_jsonable(result), indent=1))
    _write_series(out_dir, series)
    return result


def _write_series(out_dir: Path, series: dict) -> None:
    cols = {}
    for name, d in series.items():
        for kind, s in d.items():
            if s is not None and len(s):
                cols[f"{name}__{kind}"] = s
    if cols:
        pd.DataFrame(cols).to_csv(out_dir / "daily_returns.csv.gz")


def run_test(data_full: ResearchData, frozen_path: Path, results_root: Path, reason: str, costs: CostModel | None = None) -> dict:
    """Evaluate FROZEN candidates on the untouched test period. Every call is logged."""
    costs = costs or CostModel()
    frozen = json.loads(frozen_path.read_text())
    data_end = data_full.dates().max().date()
    splits = V.Splits.default(data_end)
    log_path = results_root / "test_access_log.json"
    access = json.loads(log_path.read_text()) if log_path.exists() else []
    entry = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(), "git_commit": git_commit(), "reason": reason,
             "frozen": frozen, "access_number": len(access) + 1}
    access.append(entry)
    results_root.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(access, indent=1))
    specs = load_all_strategies()
    out = {"stage": "test", "splits": splits.as_dict(), "access_number": entry["access_number"], "candidates": [], "benchmarks": {}}
    for name, res in benchmarks(data_full, costs).items():
        out["benchmarks"][name] = summarize(res.slice(*splits.test).returns)
    series = {}
    for cand in frozen["candidates"]:
        spec = specs[cand["strategy"]]
        sp = splits_for(spec, data_full)
        res = spec.run(data_full, cand["params"], costs)
        ppy = ann_periods(spec, res.returns)
        te = res.slice(*sp.test)
        m = summarize(te.returns, te.exposure, te.turnover, te.n_trades, te.costs)
        stressed = summarize(spec.run(data_full, cand["params"], costs.stressed(2.0)).slice(*sp.test).returns)
        lev = V.leverage_analysis(te.returns, MONTHLY_TARGETS, costs.margin_rate, exposure=te.exposure, periods=ppy)
        bench = crypto_benchmark(data_full, V.Splits(sp.train, sp.validation, sp.test), costs) if spec.split_mode == "adaptive" else {}
        if bench:
            cv = data_full.crypto_view()
            bh = run_weights(cv, pd.DataFrame({"BTC/USD": 1.0}, index=cv.dates()), costs)
            bench = {"buy_hold_BTC_test": summarize(bh.slice(*sp.test).returns)}
        out["candidates"].append({"strategy": cand["strategy"], "params": cand["params"], "test_period": [str(sp.test[0]), str(sp.test[1])],
                                  "benchmark_own_test": bench, "test": m, "test_cost_stress_2x": stressed,
                                  "leverage_on_test": lev, "bootstrap_1y": V.bootstrap_summary(te.returns, n_sims=1000, horizon_days=ppy)})
        series[cand["strategy"]] = {"test": te.returns}
    out_dir = results_root / "test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"results_access{entry['access_number']}.json").write_text(json.dumps(_jsonable(out), indent=1))
    _write_series(out_dir, series)
    return out
