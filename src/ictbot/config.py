"""Typed configuration loaded from config.yaml.

Every strategy / risk threshold lives here so nothing is a magic number in the
logic modules. Unknown keys are rejected so a typo cannot silently fall back
to a default.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml


class ConfigError(ValueError):
    """Raised when config.yaml is missing, malformed or out of bounds."""


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TimeWindow:
    name: str
    start: str  # "HH:MM" America/New_York
    end: str
    enabled: bool = True

    def start_time(self) -> dt.time:
        return parse_hhmm(self.start)

    def end_time(self) -> dt.time:
        return parse_hhmm(self.end)


@dataclass(frozen=True)
class ModeConfig:
    dry_run: bool = False  # evaluate + log signals, never send orders


@dataclass(frozen=True)
class DataConfig:
    feed: Literal["iex", "sip", "delayed_sip"] = "iex"
    history_days: int = 45  # calendar days of 1-minute history loaded at start
    intraday_lookback_sessions: int = 5  # prior sessions kept in the 5m/1h frames
    bar_completion_delay_seconds: int = 20
    poll_offset_seconds: int = 30
    max_data_staleness_seconds: int = 420
    min_minutes_per_5m_bar: int = 3
    sparse_warn_ratio: float = 0.8
    include_premarket_for_levels: bool = True
    cache_dir: str = "data_cache"


@dataclass(frozen=True)
class SessionConfig:
    flatten_time: str = "15:55"
    no_new_entries_minutes_before_close: int = 30
    skip_early_close_days: bool = True
    event_days_file: str = "config/event_days.yaml"
    skip_event_days: bool = True
    kill_zones: tuple[TimeWindow, ...] = (
        TimeWindow("ny_open", "09:30", "11:00", True),
        TimeWindow("silver_bullet", "10:00", "11:00", False),
    )
    silver_bullet_window: TimeWindow = TimeWindow("silver_bullet", "10:00", "11:00", True)
    level_sessions: tuple[TimeWindow, ...] = (TimeWindow("premarket", "04:00", "09:30", True),)
    opening_range_minutes: int = 15
    earliest_start: str = "08:30"
    latest_start: str = "11:00"
    max_runtime_minutes: int = 340
    exit_when_idle_after_windows: bool = True


@dataclass(frozen=True)
class IndicatorConfig:
    atr_period: int = 14
    swing_lookback: int = 2
    correlation_window_bars: int = 390


@dataclass(frozen=True)
class LiquidityConfig:
    use_prev_day: bool = True
    use_prev_week: bool = True
    use_level_sessions: bool = True
    use_opening_range: bool = True
    use_swings: bool = True
    use_equal_levels: bool = True
    swing_pool_lookback_bars: int = 156
    equal_level_atr_tolerance: float = 0.10
    equal_level_min_touches: int = 2


@dataclass(frozen=True)
class SweepConfig:
    min_buffer_atr: float = 0.05
    min_buffer_abs: float = 0.02
    reclaim_within_bars: int = 2


@dataclass(frozen=True)
class DisplacementConfig:
    min_body_atr: float = 1.2
    max_wick_fraction: float = 0.35  # (upper+lower wick) / range


@dataclass(frozen=True)
class MSSConfig:
    max_bars_after_sweep: int = 12


@dataclass(frozen=True)
class FVGConfig:
    min_size_atr: float = 0.10
    entry_mode: Literal["midpoint", "edge"] = "midpoint"
    order_expiry_bars: int = 6
    max_setup_age_bars: int = 3


@dataclass(frozen=True)
class OrderBlockConfig:
    enabled: bool = True
    required: bool = False


@dataclass(frozen=True)
class PremiumDiscountConfig:
    enabled: bool = True
    required: bool = True
    range_source: Literal["leg", "session"] = "leg"


@dataclass(frozen=True)
class HTFBiasConfig:
    enabled: bool = True
    method: Literal["structure", "ema"] = "structure"
    combine: Literal["both_agree", "daily_only", "hourly_only", "either"] = "both_agree"
    daily_swing_lookback: int = 2
    hourly_swing_lookback: int = 2
    ema_period: int = 20
    allow_neutral: bool = True
    counter_bias_requires_htf_sweep: bool = True
    htf_pool_kinds: tuple[str, ...] = ("prev_day", "prev_week", "level_session")


@dataclass(frozen=True)
class ScoringConfig:
    base: float = 1.0
    htf_aligned: float = 2.0
    htf_pool_swept: float = 1.5
    equal_levels_swept: float = 1.0
    order_block: float = 1.0
    premium_discount: float = 1.0
    silver_bullet: float = 0.5
    displacement_per_atr: float = 0.5
    displacement_cap: float = 1.5
    reward_risk_per_r: float = 0.5
    reward_risk_cap: float = 1.5
    sparse_data_penalty: float = 1.0
    min_score: float = 3.0


@dataclass(frozen=True)
class ICTConfig:
    liquidity: LiquidityConfig = LiquidityConfig()
    sweep: SweepConfig = SweepConfig()
    displacement: DisplacementConfig = DisplacementConfig()
    mss: MSSConfig = MSSConfig()
    fvg: FVGConfig = FVGConfig()
    order_block: OrderBlockConfig = OrderBlockConfig()
    premium_discount: PremiumDiscountConfig = PremiumDiscountConfig()
    htf_bias: HTFBiasConfig = HTFBiasConfig()
    scoring: ScoringConfig = ScoringConfig()


@dataclass(frozen=True)
class PartialTPConfig:
    enabled: bool = False
    fraction: float = 0.5
    at_r: float = 1.0


@dataclass(frozen=True)
class BreakEvenConfig:
    enabled: bool = False
    trigger_r: float = 1.0
    offset: float = 0.01  # $ beyond entry so the stop is strictly better than BE


@dataclass(frozen=True)
class ExecutionConfig:
    stop_buffer_atr: float = 0.10
    target_buffer_atr: float = 0.0
    min_reward_risk: float = 2.0
    bracket_time_in_force: Literal["day", "gtc"] = "gtc"
    allow_short: bool = True
    tick_size: float = 0.01
    client_order_id_prefix: str = "ictb"
    cancel_if_target_hit_before_fill: bool = True
    order_status_poll_seconds: float = 2.0
    order_status_timeout_seconds: float = 30.0
    partial_take_profit: PartialTPConfig = PartialTPConfig()
    break_even: BreakEvenConfig = BreakEvenConfig()


@dataclass(frozen=True)
class VolScalingConfig:
    enabled: bool = True
    target_atr_pct: float = 0.15  # 5m ATR as % of price considered "normal"
    min_scale: float = 0.5
    max_scale: float = 1.0  # never scale risk ABOVE configured risk_per_trade


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.5
    max_position_notional_pct: float = 25.0
    max_total_notional_pct: float = 50.0
    daily_loss_limit_pct: float = 2.0
    weekly_loss_limit_pct: float = 4.0
    max_drawdown_pct: float = 8.0
    drawdown_reset_date: str | None = None  # "YYYY-MM-DD"; manual kill-switch reset
    max_trades_per_day: int = 2
    max_consecutive_losses: int = 3
    cooldown_minutes_after_loss: int = 30
    max_spread_bps: float = 5.0
    max_spread_atr_fraction: float = 0.25
    min_bar_volume: float = 1000.0
    min_relative_volume: float = 0.3
    max_quote_age_seconds: int = 60
    min_equity: float = 2000.0
    min_stop_distance_atr: float = 0.25
    flatten_on_daily_limit: bool = True
    vol_scaling: VolScalingConfig = VolScalingConfig()


@dataclass(frozen=True)
class BucketConfig:
    name: str
    symbols: tuple[str, ...]
    max_open_risk_multiple: float = 1.5


@dataclass(frozen=True)
class PortfolioConfig:
    buckets: tuple[BucketConfig, ...] = (
        BucketConfig("us_large_cap_beta", ("SPY", "QQQM", "QQQ", "VOO", "IVV"), 1.5),
    )
    conflict_mode: Literal["best", "split"] = "best"
    allow_opposite_directions_in_bucket: bool = False
    second_same_direction_risk_fraction: float = 0.5


@dataclass(frozen=True)
class WalkForwardConfig:
    enabled: bool = False
    folds: int = 4


@dataclass(frozen=True)
class BacktestConfig:
    enabled: bool = True
    start: str = "2025-01-02"
    end: str = "2025-12-31"
    holdout_fraction: float = 0.3
    initial_equity: float = 100_000.0
    entry_slippage_bps: float = 0.0  # limit orders fill at limit or better
    stop_slippage_bps: float = 2.0
    market_slippage_bps: float = 1.0
    commission_per_share: float = 0.0
    sec_fee_rate: float = 0.0000278  # $ per $ sold; CHECK current SEC Section 31 rate
    taf_per_share: float = 0.000166  # FINRA TAF on sells; CHECK current rate
    taf_max_per_trade: float = 8.30
    fill_requires_trade_through: bool = True
    walk_forward: WalkForwardConfig = WalkForwardConfig()


@dataclass(frozen=True)
class ReportingConfig:
    reports_dir: str = "reports"
    logs_dir: str = "logs"
    summary_lookback_days: int = 90
    benchmark_symbol: str = "SPY"


@dataclass(frozen=True)
class AlertsConfig:
    enabled: bool = True
    on_fill: bool = True
    on_halt: bool = True
    on_error: bool = True


@dataclass(frozen=True)
class BotConfig:
    symbols: tuple[str, ...] = ("SPY", "QQQM")
    mode: ModeConfig = ModeConfig()
    data: DataConfig = DataConfig()
    session: SessionConfig = SessionConfig()
    indicators: IndicatorConfig = IndicatorConfig()
    ict: ICTConfig = ICTConfig()
    execution: ExecutionConfig = ExecutionConfig()
    risk: RiskConfig = RiskConfig()
    portfolio: PortfolioConfig = PortfolioConfig()
    backtest: BacktestConfig = BacktestConfig()
    reporting: ReportingConfig = ReportingConfig()
    alerts: AlertsConfig = AlertsConfig()


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def parse_hhmm(value: str) -> dt.time:
    try:
        hh, mm = value.split(":")
        return dt.time(int(hh), int(mm))
    except (ValueError, AttributeError) as exc:
        raise ConfigError(f"expected HH:MM time, got {value!r}") from exc


def _build(cls: type, raw: Any, path: str) -> Any:
    """Recursively build a (frozen) dataclass from plain YAML data."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping, got {type(raw).__name__}")
    hints = typing.get_type_hints(cls)
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {sorted(unknown)}")
    kwargs = {}
    for name, value in raw.items():
        kwargs[name] = _coerce(hints[name], value, f"{path}.{name}")
    return cls(**kwargs)


def _coerce(tp: Any, value: Any, path: str) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if dataclasses.is_dataclass(tp):
        return _build(tp, value, path)
    if origin in (typing.Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        non_none = [a for a in args if a is not type(None)]
        return _coerce(non_none[0], value, path)
    if origin is Literal:
        if value not in args:
            raise ConfigError(f"{path}: {value!r} not one of {args}")
        return value
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ConfigError(f"{path}: expected a list")
        inner = args[0]
        return tuple(_coerce(inner, v, f"{path}[{i}]") for i, v in enumerate(value))
    if tp is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{path}: expected true/false, got {value!r}")
        return value
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path}: expected integer, got {value!r}")
        return value
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path}: expected number, got {value!r}")
        return float(value)
    if tp is str:
        if not isinstance(value, (str, dt.date)):
            raise ConfigError(f"{path}: expected string, got {value!r}")
        return str(value)
    return value


def validate(cfg: BotConfig) -> None:
    """Cross-field sanity checks. Hard risk ceilings are enforced in risk.py."""
    if not cfg.symbols:
        raise ConfigError("symbols: at least one symbol required")
    for zone in (*cfg.session.kill_zones, cfg.session.silver_bullet_window, *cfg.session.level_sessions):
        if zone.start_time() >= zone.end_time():
            raise ConfigError(f"window {zone.name}: start must be before end")
    parse_hhmm(cfg.session.flatten_time)
    parse_hhmm(cfg.session.earliest_start)
    parse_hhmm(cfg.session.latest_start)
    if cfg.execution.min_reward_risk <= 0:
        raise ConfigError("execution.min_reward_risk must be > 0")
    if not 0 < cfg.execution.partial_take_profit.fraction < 1:
        raise ConfigError("execution.partial_take_profit.fraction must be in (0, 1)")
    if not 0 <= cfg.backtest.holdout_fraction < 1:
        raise ConfigError("backtest.holdout_fraction must be in [0, 1)")
    if cfg.data.poll_offset_seconds <= cfg.data.bar_completion_delay_seconds:
        raise ConfigError("data.poll_offset_seconds must exceed data.bar_completion_delay_seconds, "
                          "otherwise every cycle sees the newest bar as still forming")
    if cfg.indicators.swing_lookback < 1:
        raise ConfigError("indicators.swing_lookback must be >= 1")
    if cfg.risk.drawdown_reset_date:
        try:
            dt.date.fromisoformat(cfg.risk.drawdown_reset_date)
        except ValueError as exc:
            raise ConfigError("risk.drawdown_reset_date must be YYYY-MM-DD") from exc
    if len(cfg.execution.client_order_id_prefix) > 8:
        raise ConfigError("execution.client_order_id_prefix must be <= 8 chars")


def load_config(path: str | Path = "config.yaml", overrides: dict[str, Any] | None = None) -> BotConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    raw = yaml.safe_load(p.read_text()) or {}
    if overrides:
        raw = _deep_merge(raw, overrides)
    cfg = _build(BotConfig, raw, "config")
    validate(cfg)
    return cfg


def config_from_dict(raw: dict[str, Any]) -> BotConfig:
    cfg = _build(BotConfig, raw, "config")
    validate(cfg)
    return cfg


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def replace(cfg: Any, **changes: Any) -> Any:
    """Convenience wrapper around dataclasses.replace for frozen configs."""
    return dataclasses.replace(cfg, **changes)


__all__ = [
    "BotConfig",
    "ConfigError",
    "TimeWindow",
    "load_config",
    "config_from_dict",
    "parse_hhmm",
    "replace",
]
