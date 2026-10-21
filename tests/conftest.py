from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ictbot.config import BotConfig  # noqa: E402
from ictbot.ict_detectors import Bars  # noqa: E402
from ictbot.timeutils import NY, TradingSession, ny_dt  # noqa: E402

DAY0 = dt.date(2025, 3, 10)  # Monday (DST started 2025-03-09 - exercises EDT)
DAY1 = dt.date(2025, 3, 11)


def session(day: dt.date) -> TradingSession:
    return TradingSession(day, ny_dt(day, dt.time(9, 30)), ny_dt(day, dt.time(16, 0)))


def bars_from_ohlc(rows: list[tuple[float, float, float, float]], volume: float = 10_000) -> Bars:
    arr = np.asarray(rows, dtype=float)
    return Bars(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], np.full(len(rows), volume))


def frame_5m(rows: list[tuple[float, float, float, float]], day: dt.date, volume: float = 10_000) -> pd.DataFrame:
    start = ny_dt(day, dt.time(9, 30))
    idx = pd.DatetimeIndex([start + dt.timedelta(minutes=5 * i) for i in range(len(rows))], tz=NY, name="start")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = volume
    df["n_minutes"] = 5
    df["session_day"] = day
    return df


def flat_rows(n: int, mid: float = 100.0, half_range: float = 0.25) -> list[tuple[float, float, float, float]]:
    return [(mid, mid + half_range, mid - half_range, mid) for _ in range(n)]


@pytest.fixture
def cfg() -> BotConfig:
    return BotConfig()
