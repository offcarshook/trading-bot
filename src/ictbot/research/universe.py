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
        # extended leveraged ETF universe (all launched before 2016)
        Instrument("SOXL", "leveraged", 3.0, 3.0), Instrument("TECL", "leveraged", 3.0, 3.0),
        Instrument("FAS", "leveraged", 3.0, 3.0), Instrument("LABU", "leveraged", 5.0, 3.0),
        Instrument("CURE", "leveraged", 5.0, 3.0), Instrument("DRN", "leveraged", 5.0, 3.0),
        Instrument("ERX", "leveraged", 4.0, 2.0), Instrument("NUGT", "leveraged", 4.0, 2.0),
        Instrument("TMF", "leveraged", 3.0, 3.0), Instrument("YINN", "leveraged", 5.0, 3.0),
        Instrument("SPXL", "leveraged", 2.0, 3.0), Instrument("MIDU", "leveraged", 6.0, 3.0),
        Instrument("RETL", "leveraged", 8.0, 3.0), Instrument("DPST", "leveraged", 6.0, 3.0),
        # extended unlevered ETFs
        Instrument("SMH", "us_sector", 1.5), Instrument("XBI", "us_sector", 2.0), Instrument("IBB", "us_sector", 2.0),
        Instrument("GDX", "commodity", 2.0), Instrument("KWEB", "intl_equity", 3.0), Instrument("ARKK", "us_equity", 3.0),
        Instrument("IGV", "us_sector", 2.5), Instrument("ITB", "us_sector", 2.5), Instrument("XME", "us_sector", 3.0),
        Instrument("TAN", "us_sector", 4.0), Instrument("URA", "commodity", 4.0), Instrument("EWJ", "intl_equity", 2.0),
        Instrument("EWZ", "intl_equity", 2.0), Instrument("INDA", "intl_equity", 2.5), Instrument("FXI", "intl_equity", 2.0),
        # crypto (Alpaca spot, no margin, no shorting). half-spread here INCLUDES the
        # 25 bp tier-1 taker fee per side (Alpaca crypto fee schedule, Oct 2026)
        Instrument("BTC/USD", "crypto", 28.0), Instrument("ETH/USD", "crypto", 29.0),
        Instrument("SOL/USD", "crypto", 32.0), Instrument("LTC/USD", "crypto", 33.0),
        Instrument("BCH/USD", "crypto", 35.0), Instrument("LINK/USD", "crypto", 35.0),
        Instrument("AVAX/USD", "crypto", 35.0), Instrument("DOGE/USD", "crypto", 33.0),
        Instrument("UNI/USD", "crypto", 38.0), Instrument("AAVE/USD", "crypto", 40.0),
    ]
}

CORE_DAILY = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "TLT", "IEF", "SHY", "LQD", "HYG", "GLD", "SLV", "DBC", "VNQ", "UUP"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
LEVERAGED = ["SSO", "QLD", "UPRO", "TQQQ", "TNA", "UDOW"]
INTRADAY = ["SPY", "QQQ", "IWM"]
LEVERAGED_EXT = ["SOXL", "TECL", "FAS", "LABU", "CURE", "DRN", "ERX", "NUGT", "TMF", "YINN", "SPXL", "MIDU", "RETL", "DPST"]
EXTENDED = ["SMH", "XBI", "IBB", "GDX", "KWEB", "ARKK", "IGV", "ITB", "XME", "TAN", "URA", "EWJ", "EWZ", "INDA", "FXI"]
CRYPTO = ["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "BCH/USD", "LINK/USD", "AVAX/USD", "DOGE/USD", "UNI/USD", "AAVE/USD"]
ALL_DAILY = sorted(set(CORE_DAILY + SECTORS + LEVERAGED + ["USO"] + LEVERAGED_EXT + EXTENDED))


def half_spread_bps(symbol: str) -> float:
    inst = INSTRUMENTS.get(symbol)
    return inst.half_spread_bps if inst else 5.0
