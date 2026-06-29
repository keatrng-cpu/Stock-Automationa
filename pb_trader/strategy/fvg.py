"""Fair Value Gaps (FVG) and Inversion FVGs (iFVG) — the PB entry primitive."""
from __future__ import annotations

from ..models import Bar, Direction, FVG


def detect_fvgs(bars: list[Bar], min_size: float = 0.0) -> list[FVG]:
    """Detect 3-candle FVGs across the series.

    Bullish FVG at i: low[i] > high[i-2]  -> gap = [high[i-2], low[i]]
    Bearish FVG at i: high[i] < low[i-2]  -> gap = [high[i], low[i-2]]
    """
    out: list[FVG] = []
    for i in range(2, len(bars)):
        a, c = bars[i - 2], bars[i]
        if c.low > a.high and (c.low - a.high) > min_size:
            out.append(FVG(Direction.BULL, top=c.low, bottom=a.high, ts=c.ts, index=i))
        elif c.high < a.low and (a.low - c.high) > min_size:
            out.append(FVG(Direction.BEAR, top=a.low, bottom=c.high, ts=c.ts, index=i))
    return out


def new_fvg(bars: list[Bar], min_size: float = 0.0, sponsor_mult: float = 1.3):
    """Detect a single FVG that completes on the latest bar (incremental use).

    Marks the gap as *sponsored* (PB) when the displacement candle that created it
    traded above-average volume — i.e. institutionally backed, not a thin drift.
    """
    if len(bars) < 3:
        return None
    a, c = bars[-3], bars[-1]
    # Sponsorship: displacement candle volume vs the recent average.
    window = bars[-21:-1]
    avg_vol = (sum(b.volume for b in window) / len(window)) if window else 0.0
    sponsored = avg_vol > 0 and c.volume >= sponsor_mult * avg_vol
    idx = len(bars) - 1
    if c.low > a.high and (c.low - a.high) > min_size:
        return FVG(Direction.BULL, top=c.low, bottom=a.high, ts=c.ts, index=idx,
                   sponsored=sponsored)
    if c.high < a.low and (a.low - c.high) > min_size:
        return FVG(Direction.BEAR, top=a.low, bottom=c.high, ts=c.ts, index=idx,
                   sponsored=sponsored)
    return None


def update_fvg_states(fvgs: list[FVG], bar: Bar, index: int = -1) -> None:
    """Mark fills and inversions as new price prints.

    A bullish FVG is *filled* when price trades back into it; it *inverts* to bearish
    resistance once a candle closes fully below it (iFVG), and symmetrically for bears.
    `index` records WHEN the inversion happened (for PB mechanical-model sequencing).
    """
    for f in fvgs:
        if f.inverted:
            continue
        if f.contains(bar.low) or f.contains(bar.high):
            f.filled = True
        if f.direction is Direction.BULL and bar.close < f.bottom:
            f.inverted = True
            f.inverted_at = index
            f.direction = Direction.BEAR
        elif f.direction is Direction.BEAR and bar.close > f.top:
            f.inverted = True
            f.inverted_at = index
            f.direction = Direction.BULL


def fresh_fvgs(fvgs: list[FVG]) -> list[FVG]:
    """Unfilled, non-inverted gaps — PB requires fresh levels only."""
    return [f for f in fvgs if not f.filled and not f.inverted]


def active_ifvgs(fvgs: list[FVG]) -> list[FVG]:
    """Inverted FVGs available for retest entries."""
    return [f for f in fvgs if f.inverted]
