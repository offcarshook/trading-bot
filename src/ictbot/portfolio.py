"""Portfolio layer: correlated risk buckets and cross-symbol setup selection.

SPY and QQQM (or QQQ) move together most of the time, so they live in ONE
bucket: aggregate open risk is capped (enforced inside the risk engine) and
same-bar signals are resolved here before sizing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import BotConfig, BucketConfig
from .indicators import rolling_correlation
from .models import Setup
from .risk import Exposure


@dataclass(frozen=True)
class Selection:
    setup: Setup
    risk_fraction: float
    note: str


def bucket_for(symbol: str, cfg: BotConfig) -> BucketConfig:
    for b in cfg.portfolio.buckets:
        if symbol in b.symbols:
            return b
    return BucketConfig(name=f"solo_{symbol}", symbols=(symbol,), max_open_risk_multiple=1.0)


def select_setups(candidates: list[Setup], exposures: list[Exposure], cfg: BotConfig) -> tuple[list[Selection], list[tuple[Setup, str]]]:
    """Pick which of this bar's candidate setups may proceed to sizing.

    Rules per bucket:
      * a symbol with an open position / working entry is skipped (no pyramiding);
      * an opposite-direction trade vs existing bucket exposure is skipped unless allowed;
      * a same-direction trade while the bucket already has exposure gets a reduced risk fraction;
      * several fresh candidates: ``best`` keeps only the top score, ``split`` shares
        one trade's risk between same-direction candidates.
    """
    pc = cfg.portfolio
    selected: list[Selection] = []
    skipped: list[tuple[Setup, str]] = []
    by_bucket: dict[str, list[Setup]] = {}
    for s in sorted(candidates, key=lambda s: s.score, reverse=True):
        by_bucket.setdefault(bucket_for(s.symbol, cfg).name, []).append(s)

    for bname, group in by_bucket.items():
        bucket = next((b for b in pc.buckets if b.name == bname), bucket_for(group[0].symbol, cfg))
        held = [e for e in exposures if e.symbol in bucket.symbols]
        held_syms = {e.symbol for e in held}
        held_dirs = {e.direction for e in held}
        eligible: list[Setup] = []
        for s in group:
            if s.symbol in held_syms:
                skipped.append((s, "symbol_already_exposed"))
            elif held_dirs and s.direction not in held_dirs and not pc.allow_opposite_directions_in_bucket:
                skipped.append((s, "opposite_direction_in_correlated_bucket"))
            elif any(o.symbol == s.symbol for o in eligible):
                skipped.append((s, "lower_score_same_symbol"))
            else:
                eligible.append(s)
        if not eligible:
            continue
        base_fraction = pc.second_same_direction_risk_fraction if held else 1.0
        top = eligible[0]
        if pc.conflict_mode == "split" and not held:
            same_dir = [s for s in eligible if s.direction is top.direction]
            for s in eligible:
                if s not in same_dir:
                    skipped.append((s, "bucket_conflict_opposite_direction"))
            frac = 1.0 / len(same_dir)
            selected += [Selection(s, frac, f"split_{len(same_dir)}") for s in same_dir]
        else:
            selected.append(Selection(top, base_fraction, "reduced_second_in_bucket" if held else "best_in_bucket"))
            skipped += [(s, "bucket_conflict_lower_score") for s in eligible[1:]]
    return selected, skipped


def correlation_report(closes: dict[str, pd.Series], window: int) -> dict[str, float | None]:
    """Latest rolling correlation of 5m returns for every symbol pair."""
    out: dict[str, float | None] = {}
    syms = sorted(closes)
    for i, a in enumerate(syms):
        for b in syms[i + 1 :]:
            corr = rolling_correlation(closes[a], closes[b], window)
            val = corr.dropna()
            out[f"{a}/{b}"] = round(float(val.iloc[-1]), 4) if not val.empty else None
    return out
