"""Core research types shared by every strategy and the engines.

Causality contract (enforced by tests/research/test_causality.py for every
registered strategy): a strategy's decision for date ``t`` may only use data
with timestamps <= the close of ``t``. Daily weight strategies return target
weights indexed by DECISION date; the engine executes them at the NEXT open.
Intraday trade strategies return trades whose entry happens strictly after the
information used to decide them.
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


@dataclass
class ResearchData:
    """Adjusted regular-trading-hours bars.

    daily:    symbol -> DataFrame[open, high, low, close, volume], index = tz-naive
              normalized dates (one row per session the symbol traded)
    intraday: symbol -> DataFrame[open, high, low, close, volume] of 5-minute RTH bars,
              index = tz-aware America/New_York bar START times
    """

    daily: dict[str, pd.DataFrame]
    intraday: dict[str, pd.DataFrame] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return sorted(self.daily)

    def panel(self, column: str, symbols: list[str] | None = None) -> pd.DataFrame:
        syms = symbols or self.symbols
        frames = {s: self.daily[s][column] for s in syms if s in self.daily}
        return pd.DataFrame(frames).sort_index()

    def dates(self) -> pd.DatetimeIndex:
        idx = None
        for df in self.daily.values():
            idx = df.index if idx is None else idx.union(df.index)
        return idx if idx is not None else pd.DatetimeIndex([])

    def truncate(self, end: dt.date | pd.Timestamp) -> "ResearchData":
        """Drop everything AFTER ``end`` (inclusive end). Used to lock the test period."""
        end_ts = pd.Timestamp(end)
        daily = {s: df[df.index <= end_ts] for s, df in self.daily.items()}
        intraday = {}
        for s, df in self.intraday.items():
            if df.empty:
                intraday[s] = df
                continue
            cutoff = pd.Timestamp(end_ts.date() + dt.timedelta(days=1), tz=df.index.tz)
            intraday[s] = df[df.index < cutoff]
        return ResearchData(daily, intraday, dict(self.meta, truncated_at=str(end_ts.date())))


@dataclass
class StrategyResult:
    """Daily net returns plus diagnostics. ``returns`` index = session dates."""

    returns: pd.Series
    gross_returns: pd.Series
    exposure: pd.Series  # gross exposure (sum |w|) held during the day
    turnover: pd.Series  # sum |delta w| traded that day
    costs: pd.Series  # cost drag (fraction of equity) that day
    n_trades: int
    weights: pd.DataFrame | None = None  # decision-date target weights (weight strategies)
    trades: pd.DataFrame | None = None  # trade list (intraday strategies)
    notes: dict[str, Any] = field(default_factory=dict)

    def slice(self, start: dt.date | None, end: dt.date | None) -> "StrategyResult":
        def cut(s):
            if s is None:
                return None
            idx = s.index
            mask = np.ones(len(idx), dtype=bool)
            if start is not None:
                mask &= idx >= pd.Timestamp(start)
            if end is not None:
                mask &= idx <= pd.Timestamp(end)
            return s[mask]

        trades = self.trades
        if trades is not None and not trades.empty and "date" in trades:
            m = np.ones(len(trades), dtype=bool)
            if start is not None:
                m &= trades["date"] >= pd.Timestamp(start)
            if end is not None:
                m &= trades["date"] <= pd.Timestamp(end)
            trades = trades[m]
        return StrategyResult(
            cut(self.returns), cut(self.gross_returns), cut(self.exposure), cut(self.turnover), cut(self.costs),
            int(len(trades)) if trades is not None else self.n_trades, cut(self.weights), trades, dict(self.notes),
        )


class Strategy(Protocol):
    name: str
    family: str
    hypothesis: str
    param_grid: dict[str, list]  # PRE-REGISTERED before looking at results
    default_params: dict[str, Any]
    uses_intraday: bool

    def run(self, data: ResearchData, params: dict[str, Any], costs: Any) -> StrategyResult: ...


def grid(param_grid: dict[str, list]) -> list[dict[str, Any]]:
    keys = list(param_grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(param_grid[k] for k in keys))]


@dataclass
class StrategySpec:
    name: str
    family: str
    hypothesis: str
    param_grid: dict[str, list]
    default_params: dict[str, Any]
    run_fn: Callable[[ResearchData, dict[str, Any], Any], StrategyResult]
    uses_intraday: bool = False
    symbols: tuple[str, ...] = ()

    def run(self, data: ResearchData, params: dict[str, Any], costs) -> StrategyResult:
        merged = dict(self.default_params, **params)
        return self.run_fn(data, merged, costs)

    def trials(self) -> list[dict[str, Any]]:
        return grid(self.param_grid)


REGISTRY: dict[str, StrategySpec] = {}
IMPORT_ERRORS: dict[str, str] = {}


def register(spec: StrategySpec) -> StrategySpec:
    if spec.name in REGISTRY:
        raise ValueError(f"duplicate strategy name {spec.name}")
    REGISTRY[spec.name] = spec
    return spec


def load_all_strategies() -> dict[str, StrategySpec]:
    """Import every module in research.strategies so they self-register."""
    import importlib
    import pkgutil

    from . import strategies

    for mod in pkgutil.iter_modules(strategies.__path__):
        if mod.name.startswith("_") or mod.name == "common":
            continue
        try:
            importlib.import_module(f"{strategies.__name__}.{mod.name}")
        except Exception as exc:  # noqa: BLE001 - surfaced in reports, never silently ignored
            IMPORT_ERRORS[mod.name] = f"{type(exc).__name__}: {exc}"
    return REGISTRY
