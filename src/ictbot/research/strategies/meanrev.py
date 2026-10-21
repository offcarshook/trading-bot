"""Regime-filtered short-term mean reversion on the four US equity index ETFs.

Hypothesis: when an index ETF trades above its own 200-day SMA (bull regime),
a sharp short-term oversold close (RSI(2) washout, low internal bar strength,
or a run of consecutive down closes) is followed by above-average returns over
the next few sessions, as liquidity-driven selling reverts (Connors & Alvarez
2008, "Short Term Trading Strategies That Work"; Pagonidis 2013, "The IBS
effect"). An optional volatility filter skips entries when the symbol's own
20-day realized vol is above its trailing one-year 80th percentile (a causal
VIX proxy); an optional short side mirrors the rules in a bear regime.

Mechanics (each symbol independently, equal notional budget ``gross / n``):
* every signal uses only the CLOSE of decision date t (and earlier bars); the
  engine executes the resulting target weight at the OPEN of t+1;
* entry: flat, regime agrees, oversold (overbought for shorts), vol filter ok;
* exit: close back above the 5-day SMA (``exit_rule='sma5'``) or RSI(2) above
  70 (``'rsi2'``), or ``max_hold`` sessions after the entry decision - all
  decided at a close and executed at the next open;
* no re-entry on the bar that produced an exit, and after a TIME-STOP exit the
  entry signal must first switch off for one bar ("re-arm") so a persistent
  washout is not re-bought immediately (that would make the time stop a
  one-day pause that only pays costs).

The indicator state machine is path dependent, so it runs as a plain Python
loop over sessions per symbol (4 x ~2,700 iterations of scalar work).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import StrategyResult, StrategySpec, register
from ..engine import run_weights
from .common import available

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA"]

# Literature thresholds per oversold measure. "loose" = the commonly published
# level, "strict" = the deeper washout variant. Overbought (short side) levels
# mirror them: RSI 100-x, IBS 1-x, the same count of consecutive UP closes.
ENTRY_THRESHOLDS = {
    "rsi2": {"loose": 10.0, "strict": 5.0},  # RSI(2) below (Connors: 5-10)
    "ibs": {"loose": 0.2, "strict": 0.1},  # (C-L)/(H-L) below (Pagonidis: 0.2)
    "down_days": {"loose": 3, "strict": 4},  # N consecutive lower closes
}
RSI_EXIT = 70.0  # long exit when RSI(2) > 70; short exit when RSI(2) < 30
REGIME_SMA = 200
EXIT_SMA = 5
VOL_WINDOW = 20
VOL_LOOKBACK = 252
VOL_QUANTILE = 0.8
MAX_GROSS = 2.0


def rsi(close: pd.Series, n: int = 2) -> pd.Series:
    """Wilder RSI (recursive smoothing, alpha = 1/n) - causal by construction."""
    d = close.diff()
    gain = d.clip(lower=0.0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    loss = (-d).clip(lower=0.0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + gain / loss)
    out = out.where(loss > 0, np.where(gain > 0, 100.0, 50.0))  # no losses -> 100, flat -> 50
    return out.where(gain.notna() & loss.notna())


def ibs(df: pd.DataFrame) -> pd.Series:
    """Internal bar strength (close - low) / (high - low); NaN on zero-range bars."""
    rng = (df["high"] - df["low"]).where(lambda r: r > 0)
    return (df["close"] - df["low"]) / rng


def run_length(flag: pd.Series) -> pd.Series:
    """Length of the current run of True values ending at each bar."""
    f = flag.fillna(False).astype(bool)
    grp = (~f).cumsum()
    return f.astype(int).groupby(grp).cumsum()


def signals(df: pd.DataFrame, p: dict) -> dict[str, np.ndarray]:
    """Boolean decision-time arrays for one symbol, all computed from bars <= t."""
    close = df["close"].astype(float)
    sig, level = p["signal"], p["threshold"]
    thr = ENTRY_THRESHOLDS[sig][level]
    r2 = rsi(close, 2)
    if sig == "rsi2":
        oversold, overbought = r2 < thr, r2 > 100.0 - thr
    elif sig == "ibs":
        b = ibs(df)
        oversold, overbought = b < thr, b > 1.0 - thr
    elif sig == "down_days":
        chg = close.diff()
        oversold, overbought = run_length(chg < 0) >= thr, run_length(chg > 0) >= thr
    else:
        raise ValueError(f"unknown signal {sig}")

    sma_regime = close.rolling(REGIME_SMA, min_periods=REGIME_SMA).mean()
    bull, bear = close > sma_regime, close < sma_regime  # NaN SMA -> both False (no trading)

    if p["vol_filter"]:
        rv = np.log(close).diff().rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * np.sqrt(252)
        cap = rv.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK).quantile(VOL_QUANTILE)  # trailing, includes t
        vol_ok = rv < cap  # NaN (warm-up) -> False: no entries until a full year of vol history
    else:
        vol_ok = pd.Series(True, index=close.index)

    if p["exit_rule"] == "sma5":
        sma5 = close.rolling(EXIT_SMA, min_periods=EXIT_SMA).mean()
        exit_long, exit_short = close > sma5, close < sma5
    elif p["exit_rule"] == "rsi2":
        exit_long, exit_short = r2 > RSI_EXIT, r2 < 100.0 - RSI_EXIT
    else:
        raise ValueError(f"unknown exit_rule {p['exit_rule']}")

    def arr(s):
        return s.fillna(False).to_numpy(bool)

    return {
        "long_entry": arr(oversold & bull & vol_ok),
        "short_entry": arr(overbought & bear & vol_ok) if p["allow_short"] else np.zeros(len(close), bool),
        "exit_long": arr(exit_long),
        "exit_short": arr(exit_short),
    }


def positions(sig: dict[str, np.ndarray], max_hold: int) -> tuple[np.ndarray, list[int]]:
    """Decision-date position (+1/0/-1) per bar and the holding length (in sessions)
    of every completed or open trade."""
    le, se, xl, xs = (sig[k].tolist() for k in ("long_entry", "short_entry", "exit_long", "exit_short"))
    n = len(le)
    pos = np.zeros(n)
    holds: list[int] = []
    state, held = 0, 0
    armed_l = armed_s = True
    for t in range(n):
        if not le[t]:
            armed_l = True
        if not se[t]:
            armed_s = True
        exited = False
        if state != 0:
            held += 1
            hit = xl[t] if state > 0 else xs[t]
            if hit or held >= max_hold:
                if not hit:  # time stop: a still-active signal must switch off before re-entry
                    if state > 0 and le[t]:
                        armed_l = False
                    elif state < 0 and se[t]:
                        armed_s = False
                holds.append(held)
                state, exited = 0, True
        if state == 0 and not exited:
            if le[t] and armed_l:
                state, held = 1, 0
            elif se[t] and armed_s:
                state, held = -1, 0
        pos[t] = state
    if state != 0:
        holds.append(held)
    return pos, holds


def _flat_result(data) -> StrategyResult:
    idx = data.dates()
    z = pd.Series(0.0, index=idx)
    return StrategyResult(z, z.copy(), z.copy(), z.copy(), z.copy(), 0, weights=pd.DataFrame(index=idx),
                          notes={"warning": "none of the meanrev symbols are available"})


def run(data, p, costs):
    syms = available(data, UNIVERSE)
    if not syms:
        return _flat_result(data)
    gross = min(float(p["gross"]), MAX_GROSS)
    per_sym = gross / len(syms)
    dates = data.dates()
    cols, n_entries, hold_days = {}, 0, []
    for s in syms:
        df = data.daily[s].sort_index()
        df = df[~df.index.duplicated(keep="last")]
        pos, holds = positions(signals(df, p), int(p["max_hold"]))
        n_entries += len(holds)
        hold_days += holds
        # decision persists on dates this symbol has no bar (engine cannot trade it then anyway)
        cols[s] = pd.Series(pos * per_sym, index=df.index).reindex(dates).ffill().fillna(0.0)
    w = pd.DataFrame(cols, index=dates)
    # the band only suppresses drift re-balancing while a trade is open; it must
    # stay well below a position size so that entries and exits always execute
    band = min(float(p["band"]), 0.25 * per_sym)
    res = run_weights(data, w, costs, band=band)
    res.notes.update({"round_trips": n_entries, "avg_hold_sessions": float(np.mean(hold_days)) if hold_days else 0.0,
                      "time_in_market": float((w.abs().sum(axis=1) > 0).mean()), "per_symbol_weight": per_sym})
    return res


SPEC = register(StrategySpec(
    name="meanrev_regime",
    family="mean_reversion",
    hypothesis=("For SPY/QQQ/IWM/DIA trading above their 200-day SMA, buying the next open after a short-term oversold close "
                "(RSI(2), IBS or consecutive down closes) and selling on the bounce earns a positive after-cost return "
                "per unit of exposure (Sharpe > 0) out of sample."),
    param_grid={
        "signal": ["rsi2", "ibs", "down_days"],
        "threshold": ["loose", "strict"],
        "exit_rule": ["sma5", "rsi2"],
        "max_hold": [5, 10],
        "vol_filter": [False, True],
        "allow_short": [False],
        "gross": [1.0],
        "band": [0.02],
    },
    default_params={"signal": "rsi2", "threshold": "loose", "exit_rule": "sma5", "max_hold": 5, "vol_filter": False,
                    "allow_short": False, "gross": 1.0, "band": 0.02},
    run_fn=run,
    symbols=tuple(UNIVERSE),
))
