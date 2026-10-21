"""Instrument universe and per-symbol trading-cost assumptions.

Survivorship note: the universe is a hand-picked list of large, long-lived
ETFs that all traded continuously through 2016-2026. Choosing instruments that
are still popular today is a mild form of survivorship/selection bias; the
report states this. No single stocks are used.

Half-spreads are conservative round numbers for regular-hours marketable
orders in normal conditions (wider than typical quoted spreads for the
largest ETFs). Gold/FX are represented by ETFs (GLD, UUP) because Alpaca
offers neither spot XAU/USD nor forex.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str
    half_spread_bps: float
    leverage_factor: float = 1.0  # >1 for daily-reset leveraged ETFs
    note: str = ""


INSTRUMENTS: dict[str, Instrument] = {
    i.symbol: i
    for i in [
        # US equity index
        Instrument("SPY", "us_equity", 0.5),
        Instrument("QQQ", "us_equity", 0.5),
        Instrument("IWM", "us_equity", 1.0),
        Instrument("DIA", "us_equity", 1.0),
        # sectors
        Instrument("XLK", "us_sector", 1.5),
        Instrument("XLF", "us_sector", 1.5),
        Instrument("XLE", "us_sector", 1.5),
        Instrument("XLV", "us_sector", 1.5),
        Instrument("XLY", "us_sector", 1.5),
        Instrument("XLP", "us_sector", 1.5),
        Instrument("XLI", "us_sector", 1.5),
        Instrument("XLU", "us_sector", 1.5),
        Instrument("XLB", "us_sector", 2.0),
        # international
        Instrument("EFA", "intl_equity", 1.5),
        Instrument("EEM", "intl_equity", 1.5),
        # rates / credit
        Instrument("TLT", "rates", 1.0),
        Instrument("IEF", "rates", 1.0),
        Instrument("SHY", "rates", 1.0),
        Instrument("LQD", "credit", 1.5),
        Instrument("HYG", "credit", 1.5),
        # real assets / FX proxies
        Instrument("GLD", "gold", 1.0, note="proxy for XAU/USD"),
        Instrument("SLV", "commodity", 2.5),
        Instrument("USO", "commodity", 2.5),
        Instrument("DBC", "commodity", 3.0),
        Instrument("VNQ", "real_estate", 1.5),
        Instrument("UUP", "fx", 3.0, note="USD index proxy - Alpaca has no forex"),
        # daily-reset leveraged ETFs (for the leverage hypothesis only)
        Instrument("SSO", "leveraged", 2.0, 2.0),
        Instrument("QLD", "leveraged", 2.5, 2.0),
        Instrument("UPRO", "leveraged", 2.0, 3.0),
        Instrument("TQQQ", "leveraged", 1.5, 3.0),
        Instrument("TNA", "leveraged", 3.0, 3.0),
        Instrument("UDOW", "leveraged", 3.0, 3.0),
    ]
}

CORE_DAILY = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "TLT", "IEF", "SHY", "LQD", "HYG", "GLD", "SLV", "DBC", "VNQ", "UUP"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
LEVERAGED = ["SSO", "QLD", "UPRO", "TQQQ", "TNA", "UDOW"]
INTRADAY = ["SPY", "QQQ", "IWM"]
ALL_DAILY = sorted(set(CORE_DAILY + SECTORS + LEVERAGED + ["USO"]))


def half_spread_bps(symbol: str) -> float:
    inst = INSTRUMENTS.get(symbol)
    return inst.half_spread_bps if inst else 5.0
