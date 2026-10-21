"""Historical research data.

Source: Alpaca market data, SIP (consolidated) feed - allowed on the free plan
for data older than 15 minutes - with ``adjustment=all`` (splits AND dividends
back-adjusted, so close-to-close returns approximate total return).

Daily bars are BUILT from intraday bars restricted to each session's regular
hours (Alpaca calendar, early closes included) so that "open" is the 09:30
regular-session open, not a 04:00 pre-market print. Caveat: the official
closing-auction print is stamped 16:00:00 and therefore falls outside the RTH
window; our "close" is the last regular-session trade before the auction.

Downloads are cached as CSV.gz with a manifest (feed, timeframe, adjustment,
range, row count, sha256) so every research run records exactly which data it
used. Back-adjusted history changes whenever a new dividend is paid, so the
cache is keyed by its end date and never appended to.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..retry import call_with_retry
from ..timeutils import NY, TradingSession
from .base import ResearchData

log = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AlpacaHistory:
    def __init__(self, key_id: str, secret_key: str, cache_dir: str | Path = "data_cache/research", feed: str = "sip") -> None:
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical import StockHistoricalDataClient

        self._client = StockHistoricalDataClient(key_id, secret_key)
        self._feed_name = feed
        self._feed = {"iex": DataFeed.IEX, "sip": DataFeed.SIP}[feed]
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)

    def bars(self, symbol: str, minutes: int, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, dict]:
        from alpaca.data.enums import Adjustment
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        tag = f"{symbol}_{minutes}m_{self._feed_name}_all_{start}_{end}"
        path = self.cache / f"{tag}.csv.gz"
        man_path = self.cache / f"{tag}.json"
        if path.exists() and man_path.exists():
            df = pd.read_csv(path, index_col=0)
            df.index = pd.to_datetime(df.index, utc=True).tz_convert(NY)
            return df, json.loads(man_path.read_text())
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(minutes, TimeFrameUnit.Minute),
            start=dt.datetime.combine(start, dt.time(0), tzinfo=NY),
            end=dt.datetime.combine(end, dt.time(23, 59), tzinfo=NY),
            adjustment=Adjustment.ALL,
            feed=self._feed,
        )
        barset = call_with_retry(lambda: self._client.get_stock_bars(req), what=f"bars {symbol} {minutes}m", attempts=6)
        rows = barset.data.get(symbol, []) if hasattr(barset, "data") else []
        df = pd.DataFrame(
            {"open": [b.open for b in rows], "high": [b.high for b in rows], "low": [b.low for b in rows],
             "close": [b.close for b in rows], "volume": [b.volume for b in rows]},
            index=pd.DatetimeIndex([b.timestamp for b in rows]).tz_convert(NY) if rows else pd.DatetimeIndex([], tz=NY),
        )
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_csv(path)
        manifest = {"symbol": symbol, "minutes": minutes, "feed": self._feed_name, "adjustment": "all", "start": str(start),
                    "end": str(end), "rows": int(len(df)), "sha256": _sha256(path),
                    "first": str(df.index[0]) if len(df) else None, "last": str(df.index[-1]) if len(df) else None}
        man_path.write_text(json.dumps(manifest, indent=1))
        log.info("downloaded", extra=manifest)
        return df, manifest


class AlpacaCryptoHistory:
    """Daily crypto bars (Alpaca US crypto feed; 24/7 market; no adjustment needed)."""

    def __init__(self, key_id: str | None = None, secret_key: str | None = None, cache_dir: str | Path = "data_cache/research") -> None:
        from alpaca.data.historical import CryptoHistoricalDataClient

        self._client = CryptoHistoricalDataClient(key_id, secret_key)
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)

    def daily(self, symbol: str, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, dict]:
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame

        tag = f"{symbol.replace('/', '-')}_1d_crypto_{start}_{end}"
        path, man_path = self.cache / f"{tag}.csv.gz", self.cache / f"{tag}.json"
        if path.exists() and man_path.exists():
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            return df, json.loads(man_path.read_text())
        req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                                start=dt.datetime.combine(start, dt.time(0)), end=dt.datetime.combine(end, dt.time(23, 59)))
        barset = call_with_retry(lambda: self._client.get_crypto_bars(req), what=f"crypto bars {symbol}", attempts=6)
        rows = barset.data.get(symbol, []) if hasattr(barset, "data") else []
        idx = pd.DatetimeIndex([pd.Timestamp(b.timestamp).tz_convert("UTC").tz_localize(None).normalize() for b in rows])
        df = pd.DataFrame({"open": [b.open for b in rows], "high": [b.high for b in rows], "low": [b.low for b in rows],
                           "close": [b.close for b in rows], "volume": [b.volume for b in rows]}, index=idx)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.index.name = "date"
        df.to_csv(path)
        manifest = {"symbol": symbol, "timeframe": "1Day", "feed": "crypto_us", "start": str(start), "end": str(end), "rows": int(len(df)),
                    "sha256": _sha256(path), "first": str(df.index[0].date()) if len(df) else None, "last": str(df.index[-1].date()) if len(df) else None}
        man_path.write_text(json.dumps(manifest, indent=1))
        log.info("downloaded crypto", extra=manifest)
        return df, manifest


    def latest_prices(self, symbols: list[str]) -> dict[str, float]:
        from alpaca.data.requests import CryptoLatestTradeRequest

        if not symbols:
            return {}
        res = call_with_retry(lambda: self._client.get_crypto_latest_trade(CryptoLatestTradeRequest(symbol_or_symbols=list(symbols))),
                              what="crypto latest trade")
        return {s: float(t.price) for s, t in (res or {}).items() if t is not None and t.price}


def rth_filter(bars: pd.DataFrame, sessions: list[TradingSession]) -> pd.DataFrame:
    """Keep bars whose START is inside [session.open, session.close)."""
    if bars.empty:
        return bars
    opens = pd.DatetimeIndex([s.open for s in sessions])
    closes = pd.DatetimeIndex([s.close for s in sessions])
    pos = opens.searchsorted(bars.index, side="right") - 1
    valid = pos >= 0
    keep = np.zeros(len(bars), dtype=bool)
    keep[valid] = bars.index[valid] < closes[pos[valid]]
    return bars[keep]


def daily_from_intraday(bars_rth: pd.DataFrame) -> pd.DataFrame:
    if bars_rth.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    day = pd.DatetimeIndex(bars_rth.index.tz_convert(NY).date)
    g = bars_rth.groupby(day)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    out.index = pd.DatetimeIndex(out.index).normalize()
    out.index.name = "date"
    return out


def load_research_data(
    history: AlpacaHistory,
    sessions: list[TradingSession],
    daily_symbols: list[str],
    intraday_symbols: list[str],
    start: dt.date,
    end: dt.date,
    daily_build_minutes: int = 30,
    intraday_minutes: int = 5,
    crypto_history: "AlpacaCryptoHistory | None" = None,
    crypto_symbols: list[str] | None = None,
) -> ResearchData:
    daily, intraday, manifests, crypto = {}, {}, [], {}
    for sym in daily_symbols:
        raw, man = history.bars(sym, daily_build_minutes, start, end)
        manifests.append(man)
        d = daily_from_intraday(rth_filter(raw, sessions))
        if len(d):
            daily[sym] = d
        else:
            log.warning("no data", extra={"symbol": sym})
    for sym in intraday_symbols:
        raw, man = history.bars(sym, intraday_minutes, start, end)
        manifests.append(man)
        intraday[sym] = rth_filter(raw, sessions)
    if crypto_history is not None:
        for sym in crypto_symbols or []:
            try:
                df, man = crypto_history.daily(sym, start, end)
            except Exception as exc:  # noqa: BLE001 - an unsupported pair must not kill the run
                log.warning("crypto download failed", extra={"symbol": sym, "error": str(exc)[:200]})
                continue
            manifests.append(man)
            if len(df):
                crypto[sym] = df
    early = sorted(str(s.day) for s in sessions if s.close.time() < dt.time(16, 0))
    return ResearchData(daily, intraday, {"manifests": manifests, "start": str(start), "end": str(end), "early_closes": early,
                                          "feed": history._feed_name}, crypto)


# --------------------------------------------------------------------------- #
# Synthetic data (tests / offline smoke runs) - never used for conclusions
# --------------------------------------------------------------------------- #


def synthetic_data(symbols: list[str], start: str = "2016-01-04", end: str = "2026-09-30", seed: int = 7,
                   intraday_symbols: tuple[str, ...] = (), drift: float = 0.0003, vol: float = 0.011,
                   crypto_symbols: tuple[str, ...] = (), crypto_start: str = "2020-01-01") -> ResearchData:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    common = rng.normal(0, vol * 0.8, len(dates))
    daily = {}
    for j, s in enumerate(symbols):
        idio = rng.normal(0, vol * 0.6, len(dates))
        r = drift + common * (0.4 + 0.15 * (j % 4)) + idio
        close = 100 * np.exp(np.cumsum(r))
        gap = rng.normal(0, vol * 0.3, len(dates))
        open_ = np.concatenate(([100.0], close[:-1])) * np.exp(gap)
        hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.4, len(dates))))
        lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.4, len(dates))))
        daily[s] = pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close,
                                 "volume": rng.integers(1e6, 5e6, len(dates)).astype(float)}, index=dates)
    intraday = {}
    for s in intraday_symbols:
        d = daily[s]
        frames = []
        for day, row in d.iterrows():
            t0 = pd.Timestamp(day.date()).tz_localize(NY) + pd.Timedelta(hours=9, minutes=30)
            idx = pd.date_range(t0, periods=78, freq="5min")
            path = np.cumsum(rng.normal(0, 1, 78))
            path = (path - path[0]) / (abs(path[-1] - path[0]) + 1e-9) * (row.close - row.open) if path[-1] != path[0] else path * 0
            px = row.open + path
            px[-1] = row.close
            op = np.concatenate(([row.open], px[:-1]))
            wig = np.abs(rng.normal(0, (row.high - row.low) * 0.05 + 1e-6, 78))
            frames.append(pd.DataFrame({"open": op, "high": np.maximum(op, px) + wig, "low": np.minimum(op, px) - wig,
                                        "close": px, "volume": 1e4}, index=idx))
        intraday[s] = pd.concat(frames) if frames else pd.DataFrame()
    crypto = {}
    cdates = pd.date_range(crypto_start, end, freq="D")
    common_c = rng.normal(0, 0.03, len(cdates))
    for j, s in enumerate(crypto_symbols):
        r = 0.0008 + common_c * (0.8 + 0.1 * j) + rng.normal(0, 0.02, len(cdates))
        close = 1000 * np.exp(np.cumsum(r))
        open_ = np.concatenate(([1000.0], close[:-1]))
        hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, len(cdates))))
        lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, len(cdates))))
        crypto[s] = pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": 1e3}, index=cdates)
    return ResearchData(daily, intraday, {"synthetic": True, "seed": seed}, crypto)
