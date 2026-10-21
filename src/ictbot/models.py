"""Domain dataclasses shared by detectors, strategy, risk, execution, backtest."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Direction.LONG else -1

    @property
    def opposite(self) -> "Direction":
        return Direction.SHORT if self is Direction.LONG else Direction.LONG


class Bias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PoolSide(str, Enum):
    """Buy-side liquidity rests ABOVE highs; sell-side liquidity BELOW lows."""

    BUY_SIDE = "buy_side"
    SELL_SIDE = "sell_side"


@dataclass(frozen=True)
class Swing:
    index: int  # bar index of the swing extreme
    price: float
    kind: str  # "high" | "low"
    confirmed_index: int  # first bar index at which the fractal is known (index + n)


@dataclass(frozen=True)
class LiquidityPool:
    name: str  # e.g. "PDH", "PWL", "EQH", "swing_high", "ORH", "premarket_high"
    kind: str  # prev_day | prev_week | level_session | opening_range | swing | equal_levels
    side: PoolSide
    price: float
    available_from: int  # first bar index (in the 5m frame) at which the pool is known
    touches: int = 1


@dataclass(frozen=True)
class Sweep:
    pool: LiquidityPool
    sweep_index: int  # bar that first traded beyond the pool by >= buffer
    reclaim_index: int  # bar that CLOSED back inside (confirmation)
    extreme: float  # most extreme price between sweep_index and reclaim_index

    @property
    def trade_direction(self) -> Direction:
        """Buy-side sweep -> look for shorts; sell-side sweep -> look for longs."""
        return Direction.SHORT if self.pool.side is PoolSide.BUY_SIDE else Direction.LONG


@dataclass(frozen=True)
class Displacement:
    index: int
    direction: Direction
    body: float
    body_atr: float
    wick_fraction: float


@dataclass(frozen=True)
class MSS:
    sweep: Sweep
    displacement: Displacement
    broken_swing: Swing

    @property
    def index(self) -> int:
        return self.displacement.index

    @property
    def direction(self) -> Direction:
        return self.displacement.direction


@dataclass(frozen=True)
class FVG:
    index: int  # third candle of the pattern (gap known when this bar completes)
    direction: Direction  # LONG = bullish gap, SHORT = bearish gap
    bottom: float
    top: float

    @property
    def size(self) -> float:
        return self.top - self.bottom

    @property
    def midpoint(self) -> float:
        """Consequent encroachment."""
        return (self.top + self.bottom) / 2.0

    def entry_edge(self) -> float:
        """First price a retrace touches: top of a bullish gap, bottom of a bearish one."""
        return self.top if self.direction is Direction.LONG else self.bottom

    def far_edge(self) -> float:
        return self.bottom if self.direction is Direction.LONG else self.top


@dataclass
class FVGState:
    fvg: FVG
    touched: bool = False
    reached_midpoint: bool = False
    filled: bool = False  # traded through the far edge
    invalidated: bool = False  # CLOSED through the far edge


@dataclass(frozen=True)
class OrderBlock:
    index: int
    direction: Direction  # direction of the trade it supports
    low: float
    high: float


@dataclass(frozen=True)
class Setup:
    """A fully specified trade idea produced by the strategy (single source of truth)."""

    setup_id: str
    symbol: str
    direction: Direction
    signal_time: dt.datetime  # START time of the bar that confirmed the setup
    confirm_index: int
    entry: float
    stop: float
    target: float
    target_pool: str
    sweep: Sweep
    mss: MSS
    fvg: FVG
    score: float
    atr: float
    tags: tuple[str, ...] = ()
    components: dict[str, float] = field(default_factory=dict)
    order_block: OrderBlock | None = None

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_risk(self) -> float:
        r = self.risk_per_share
        return abs(self.target - self.entry) / r if r > 0 else 0.0

    @property
    def setup_tag(self) -> str:
        side = "L" if self.direction is Direction.LONG else "S"
        return f"{self.sweep.pool.kind}-{side}"


@dataclass(frozen=True)
class SignalRecord:
    """Every evaluated idea, including rejected ones, for the signal log."""

    time: dt.datetime
    symbol: str
    stage: str  # detector stage reached / decision point
    decision: str  # "taken" | "skipped" | "rejected" | "info"
    reason: str
    setup_id: str = ""
    direction: str = ""
    score: float = 0.0
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    reward_risk: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeRecord:
    """A completed (or open) round trip, reconstructed from broker orders or the backtest."""

    trade_id: str
    symbol: str
    direction: str
    setup_tag: str
    entry_time: dt.datetime
    entry_price: float
    qty: float
    stop_price: float
    target_price: float
    exit_time: dt.datetime | None
    exit_price: float | None
    exit_reason: str
    pnl: float
    fees: float
    r_multiple: float
    mae_r: float | None = None
    mfe_r: float | None = None
    score: float = 0.0
