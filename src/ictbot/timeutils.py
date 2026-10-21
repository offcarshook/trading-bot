"""Timezone-aware time helpers. All market logic runs in America/New_York."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
REGULAR_CLOSE = dt.time(16, 0)
BAR_MINUTES = 5


def now_ny() -> dt.datetime:
    return dt.datetime.now(tz=NY)


def to_ny(ts: dt.datetime) -> dt.datetime:
    if ts.tzinfo is None:
        raise ValueError("naive datetime passed where tz-aware was required")
    return ts.astimezone(NY)


def ny_dt(day: dt.date, t: dt.time) -> dt.datetime:
    """Combine a date and wall-clock NY time into an aware datetime (DST-safe)."""
    return dt.datetime.combine(day, t, tzinfo=NY)


@dataclass(frozen=True)
class TradingSession:
    """One regular trading session, sourced from Alpaca's /v2/calendar."""

    day: dt.date
    open: dt.datetime  # aware, NY
    close: dt.datetime  # aware, NY

    @property
    def is_early_close(self) -> bool:
        return self.close.timetz().replace(tzinfo=None) < REGULAR_CLOSE

    def contains(self, ts: dt.datetime) -> bool:
        return self.open <= ts < self.close


def session_from_calendar(day: dt.date, open_naive: dt.datetime, close_naive: dt.datetime) -> TradingSession:
    """Alpaca's calendar model returns NAIVE datetimes that are NY wall-clock
    times (verified in alpaca-py 0.44 ``Calendar.__init__``); localise them."""
    o = open_naive.replace(tzinfo=NY) if open_naive.tzinfo is None else open_naive.astimezone(NY)
    c = close_naive.replace(tzinfo=NY) if close_naive.tzinfo is None else close_naive.astimezone(NY)
    return TradingSession(day=day, open=o, close=c)


def floor_to_bar(ts: dt.datetime, session_open: dt.datetime, minutes: int = BAR_MINUTES) -> dt.datetime:
    """Start of the bar containing ``ts`` with bars anchored at the session open."""
    elapsed = (ts - session_open).total_seconds()
    k = int(elapsed // (minutes * 60))
    return session_open + dt.timedelta(minutes=k * minutes)


def next_bar_boundary(ts: dt.datetime, session_open: dt.datetime, minutes: int = BAR_MINUTES) -> dt.datetime:
    return floor_to_bar(ts, session_open, minutes) + dt.timedelta(minutes=minutes)


def in_window(ts: dt.datetime, start: dt.time, end: dt.time) -> bool:
    """True if NY wall time of ``ts`` is within [start, end)."""
    t = to_ny(ts).time()
    return start <= t < end


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())
