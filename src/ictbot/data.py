"""Market data: fetching (Alpaca) and pure aggregation helpers.

Primary timeframe is 5-minute bars aggregated from 1-minute bars, anchored to
each session's open from the Alpaca calendar. Only COMPLETED buckets are ever
emitted: a bucket counts as complete once ``asof >= bucket_end + delay``.
1-hour and daily bars are aggregated from the same regular-trading-hours (RTH)
1-minute bars so every timeframe shares one consistent source.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np
import pandas as pd

from .retry import call_with_retry
from .timeutils import NY, TradingSession, ny_dt

log = logging.getLogger(__name__)
OHLCV = ["open", "high", "low", "close", "volume"]


class MarketDataSource(Protocol):
    def minute_bars(self, symbols: list[str], start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]: ...

    def latest_quote(self, symbol: str) -> "Quote | None": ...


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    timestamp: dt.datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        return self.spread / self.mid * 1e4 if self.mid > 0 else float("inf")


# --------------------------------------------------------------------------- #
# Pure aggregation
# --------------------------------------------------------------------------- #


def empty_bars() -> pd.DataFrame:
    df = pd.DataFrame(columns=[*OHLCV, "n_minutes", "session_day"])
    df.index = pd.DatetimeIndex([], tz=NY, name="start")
    return df


def _between(df: pd.DataFrame, lo: dt.datetime, hi: dt.datetime) -> pd.DataFrame:
    """Rows with lo <= index < hi on a sorted index (binary search, no full scan)."""
    if df.empty:
        return df
    idx = df.index
    i, j = idx.searchsorted(lo, side="left"), idx.searchsorted(hi, side="left")
    return df.iloc[i:j]


def rth_slice(bars_1m: pd.DataFrame, session: TradingSession) -> pd.DataFrame:
    return _between(bars_1m, session.open, session.close)


def window_slice(bars_1m: pd.DataFrame, day: dt.date, start: dt.time, end: dt.time) -> pd.DataFrame:
    return _between(bars_1m, ny_dt(day, start), ny_dt(day, end))


def aggregate_session(
    bars_1m: pd.DataFrame, session: TradingSession, minutes: int, asof: dt.datetime | None = None, delay_s: int = 0
) -> pd.DataFrame:
    """Aggregate one session's RTH 1-minute bars into ``minutes`` buckets
    anchored at the session open. Buckets that are not complete at ``asof``
    (bucket_end + delay > asof) are DROPPED - no partial candles, ever."""
    rth = rth_slice(bars_1m, session)
    if rth.empty:
        return empty_bars()
    open_ns = pd.Timestamp(session.open).as_unit("ns").value
    width = minutes * 60 * 1_000_000_000
    bucket = (rth.index.as_unit("ns").asi8 - open_ns) // width  # pandas 3 may default to us
    starts_at = np.flatnonzero(np.diff(bucket, prepend=bucket[0] - 1))
    o = rth["open"].to_numpy(float)
    h = rth["high"].to_numpy(float)
    lo = rth["low"].to_numpy(float)
    c = rth["close"].to_numpy(float)
    v = rth["volume"].to_numpy(float)
    ends_at = np.append(starts_at[1:], len(rth)) - 1
    keys = bucket[starts_at]
    index = pd.DatetimeIndex(open_ns + keys * width, tz="UTC").tz_convert(NY)
    out = pd.DataFrame(
        {
            "open": o[starts_at],
            "high": np.maximum.reduceat(h, starts_at),
            "low": np.minimum.reduceat(lo, starts_at),
            "close": c[ends_at],
            "volume": np.add.reduceat(v, starts_at),
            "n_minutes": np.diff(np.append(starts_at, len(rth))),
        },
        index=index,
    )
    out.index.name = "start"
    out["session_day"] = session.day
    return completed_only(out, minutes, session, asof, delay_s)


def completed_only(bars: pd.DataFrame, minutes: int, session: TradingSession, asof: dt.datetime | None, delay_s: int = 0) -> pd.DataFrame:
    """Keep buckets whose end (capped at the session close) + delay <= asof."""
    if bars.empty or asof is None:
        return bars
    ends = np.minimum(bars.index + pd.Timedelta(minutes=minutes), session.close)
    return bars[ends <= asof - dt.timedelta(seconds=delay_s)]


def aggregate_sessions(
    bars_1m: pd.DataFrame, sessions: Iterable[TradingSession], minutes: int, asof: dt.datetime | None = None, delay_s: int = 0
) -> pd.DataFrame:
    frames = [aggregate_session(bars_1m, s, minutes, asof, delay_s) for s in sessions]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames).sort_index() if frames else empty_bars()


def daily_from_minutes(bars_1m: pd.DataFrame, sessions: Iterable[TradingSession]) -> pd.DataFrame:
    """One RTH OHLCV row per session (index = session date)."""
    rows = []
    for s in sessions:
        rth = rth_slice(bars_1m, s)
        if rth.empty:
            continue
        rows.append(
            {
                "day": s.day,
                "open": rth["open"].iloc[0],
                "high": rth["high"].max(),
                "low": rth["low"].min(),
                "close": rth["close"].iloc[-1],
                "volume": rth["volume"].sum(),
            }
        )
    if not rows:
        return pd.DataFrame(columns=OHLCV)
    return pd.DataFrame(rows).set_index("day").sort_index()


def window_high_low(bars_1m: pd.DataFrame, day: dt.date, start: dt.time, end: dt.time) -> tuple[float | None, float | None]:
    w = window_slice(bars_1m, day, start, end)
    if w.empty:
        return None, None
    return float(w["high"].max()), float(w["low"].min())


@dataclass(frozen=True)
class DataQuality:
    symbol: str
    expected_minutes: int
    received_minutes: int
    sparse_5m_bars: int
    newest_bar_age_s: float | None

    @property
    def coverage(self) -> float:
        return self.received_minutes / self.expected_minutes if self.expected_minutes else 1.0


def assess_quality(
    symbol: str, bars_1m: pd.DataFrame, bars_5m_today: pd.DataFrame, session: TradingSession, asof: dt.datetime, min_minutes: int
) -> DataQuality:
    end = min(asof, session.close)
    expected = max(0, int((end - session.open).total_seconds() // 60))
    rth = rth_slice(bars_1m, session)
    rth = rth[rth.index < end]
    newest_age = (asof - (rth.index[-1] + dt.timedelta(minutes=1))).total_seconds() if not rth.empty else None
    sparse = int((bars_5m_today["n_minutes"] < min_minutes).sum()) if not bars_5m_today.empty else 0
    return DataQuality(symbol, expected, len(rth), sparse, newest_age)


# --------------------------------------------------------------------------- #
# Alpaca implementation
# --------------------------------------------------------------------------- #


class AlpacaMarketData:
    """Fetches 1-minute bars and quotes from Alpaca's market data API.

    Free (Basic) plan facts verified against Alpaca docs: real-time data is
    IEX-only; SIP history is allowed only when ``end`` is >= 15 minutes old;
    200 historical calls/min. IEX volume is a small slice of consolidated
    volume, so volume filters are relative to the same feed.
    """

    PAGE_LIMIT = 10_000

    def __init__(self, key_id: str, secret_key: str, feed: str = "iex") -> None:
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical import StockHistoricalDataClient

        self._client = StockHistoricalDataClient(key_id, secret_key)
        self._feed = {"iex": DataFeed.IEX, "sip": DataFeed.SIP, "delayed_sip": DataFeed.DELAYED_SIP}[feed]

    def minute_bars(self, symbols: list[str], start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
        from alpaca.data.enums import Adjustment
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=self._feed,
            adjustment=Adjustment.SPLIT,
        )
        barset = call_with_retry(lambda: self._client.get_stock_bars(req), what="get_stock_bars")
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            rows = barset.data.get(sym, []) if hasattr(barset, "data") else []
            if not rows:
                out[sym] = pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], tz=NY))
                continue
            df = pd.DataFrame(
                {
                    "open": [b.open for b in rows],
                    "high": [b.high for b in rows],
                    "low": [b.low for b in rows],
                    "close": [b.close for b in rows],
                    "volume": [b.volume for b in rows],
                },
                index=pd.DatetimeIndex([b.timestamp for b in rows]).tz_convert(NY),
            )
            df.index.name = "start"
            out[sym] = df[~df.index.duplicated(keep="last")].sort_index()
        return out

    def daily_closes(self, symbol: str, start: dt.date, end: dt.date) -> pd.Series:
        """Daily closes (for the buy-and-hold benchmark only)."""
        from alpaca.data.enums import Adjustment
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(
            symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=ny_dt(start, dt.time(0)),
            end=ny_dt(end, dt.time(23, 59)), feed=self._feed, adjustment=Adjustment.ALL,
        )
        barset = call_with_retry(lambda: self._client.get_stock_bars(req), what="get_stock_bars_daily")
        rows = barset.data.get(symbol, []) if hasattr(barset, "data") else []
        return pd.Series({b.timestamp.astimezone(NY).date(): float(b.close) for b in rows}, dtype=float)

    def latest_trade_price(self, symbol: str) -> float | None:
        from alpaca.data.requests import StockLatestTradeRequest

        req = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=self._feed)
        res = call_with_retry(lambda: self._client.get_stock_latest_trade(req), what="get_stock_latest_trade")
        t = res.get(symbol) if isinstance(res, dict) else None
        return float(t.price) if t is not None and t.price else None

    def latest_quote(self, symbol: str) -> Quote | None:
        from alpaca.data.requests import StockLatestQuoteRequest

        req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=self._feed)
        res = call_with_retry(lambda: self._client.get_stock_latest_quote(req), what="get_stock_latest_quote")
        q = res.get(symbol) if isinstance(res, dict) else None
        if q is None or not q.bid_price or not q.ask_price:
            return None
        return Quote(float(q.bid_price), float(q.ask_price), q.timestamp)


class CachedMinuteBars:
    """CSV cache of 1-minute bars per symbol/day for repeatable backtests."""

    def __init__(self, source: MarketDataSource, cache_dir: str | Path) -> None:
        self._source = source
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str, day: dt.date) -> Path:
        feed = getattr(self._source, "_feed", None)
        tag = str(getattr(feed, "value", feed or "unknown"))  # never mix IEX and SIP bars
        return self._dir / tag / symbol / f"{day.isoformat()}.csv.gz"

    def load(self, symbols: list[str], days: list[dt.date]) -> dict[str, pd.DataFrame]:
        frames: dict[str, list[pd.DataFrame]] = {s: [] for s in symbols}
        missing = [d for d in days if any(not self._path(s, d).exists() for s in symbols)]
        for chunk_start in range(0, len(missing), 5):
            chunk = missing[chunk_start : chunk_start + 5]
            start = ny_dt(chunk[0], dt.time(4, 0))
            end = ny_dt(chunk[-1], dt.time(20, 0))
            fetched = self._source.minute_bars(symbols, start, end)
            for sym, df in fetched.items():
                for d in chunk:
                    part = df[(df.index >= ny_dt(d, dt.time(0))) & (df.index < ny_dt(d + dt.timedelta(days=1), dt.time(0)))]
                    if part.empty:
                        continue  # never cache an empty/failed day permanently
                    p = self._path(sym, d)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    part.to_csv(p)
        for sym in symbols:
            for d in days:
                p = self._path(sym, d)
                if p.exists():
                    df = pd.read_csv(p, index_col=0)
                    if not df.empty:
                        df.index = pd.to_datetime(df.index, utc=True).tz_convert(NY)
                        frames[sym].append(df)
        return {s: (pd.concat(f).sort_index() if f else pd.DataFrame(columns=OHLCV)) for s, f in frames.items()}
