"""Higher-timeframe aggregation + bias — the top-down core of SMC.

Real smart-money analysis is multi-timeframe: establish bias on a higher timeframe
(e.g. 15m/1h), then only take lower-timeframe (1m/5m) entries that agree with it.
This module resamples the LTF bar stream into HTF candles and derives HTF bias.
"""
from __future__ import annotations

from typing import Optional

from ..models import Bar, Direction
from .structure import StructureState, find_swings


def _bucket(ts, minutes: int) -> int:
    """Deterministic, timezone-free time bucket index for resampling."""
    total_min = ts.toordinal() * 1440 + ts.hour * 60 + ts.minute
    return total_min // minutes


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Aggregate LTF bars into HTF OHLCV candles by fixed time buckets."""
    if not bars:
        return []
    out: list[Bar] = []
    cur_bucket = None
    o = h = l = c = v = 0.0
    ts0 = bars[0].ts
    sym = bars[0].symbol
    for b in bars:
        bk = _bucket(b.ts, minutes)
        if bk != cur_bucket:
            if cur_bucket is not None:
                out.append(Bar(ts0, o, h, l, c, v, sym))
            cur_bucket = bk
            ts0, o, h, l, c, v = b.ts, b.open, b.high, b.low, b.close, b.volume
        else:
            h = max(h, b.high)
            l = min(l, b.low)
            c = b.close
            v += b.volume
    out.append(Bar(ts0, o, h, l, c, v, sym))
    return out


def htf_bias(bars: list[Bar], minutes: int = 15, swing_k: int = 2) -> Optional[Direction]:
    """Resample to `minutes` and return the prevailing HTF structural trend (or None)."""
    htf = resample(bars, minutes)
    if len(htf) < 3 * swing_k + 5:
        return None
    swings = find_swings(htf, swing_k)
    state = StructureState()
    for i, bar in enumerate(htf):
        state.update(swings, bar, i)
    return state.trend
