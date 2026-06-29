"""Liquidity voids — oversized imbalances price tends to revisit to rebalance.

A liquidity void is a large displacement leaving a wide, thin-traded gap (much bigger
than a typical FVG). Price frequently returns to "fill" the void, so unfilled voids in
the trade direction make logical targets and add context.
"""
from __future__ import annotations

from ..models import Bar, Direction, LiquidityVoid
from .conditions import atr


def detect_voids(bars: list[Bar], atr_n: int = 14, mult: float = 2.5) -> list[LiquidityVoid]:
    """A 3-candle FVG whose gap exceeds `mult` * ATR is treated as a liquidity void."""
    if len(bars) < atr_n + 3:
        return []
    a = atr(bars, atr_n)
    if a <= 0:
        return []
    threshold = mult * a
    out: list[LiquidityVoid] = []
    for i in range(2, len(bars)):
        c0, c2 = bars[i - 2], bars[i]
        if c2.low > c0.high and (c2.low - c0.high) >= threshold:
            out.append(LiquidityVoid(Direction.BULL, top=c2.low, bottom=c0.high,
                                     ts=c2.ts, index=i))
        elif c2.high < c0.low and (c0.low - c2.high) >= threshold:
            out.append(LiquidityVoid(Direction.BEAR, top=c0.low, bottom=c2.high,
                                     ts=c2.ts, index=i))
    return out


def new_void(bars: list[Bar], atr_n: int = 14, mult: float = 2.5):
    """Detect a liquidity void completing on the latest bar (incremental use)."""
    if len(bars) < atr_n + 3:
        return None
    a = atr(bars, atr_n)
    if a <= 0:
        return None
    thr = mult * a
    c0, c2 = bars[-3], bars[-1]
    if c2.low > c0.high and (c2.low - c0.high) >= thr:
        return LiquidityVoid(Direction.BULL, top=c2.low, bottom=c0.high, ts=c2.ts,
                             index=len(bars) - 1)
    if c2.high < c0.low and (c0.low - c2.high) >= thr:
        return LiquidityVoid(Direction.BEAR, top=c0.low, bottom=c2.high, ts=c2.ts,
                             index=len(bars) - 1)
    return None


def new_vacuum(bars: list[Bar], atr_n: int = 14, mult: float = 1.5):
    """Vacuum block (ICT): a true price GAP between consecutive bars (prev close → open)
    bigger than `mult`*ATR — a low-liquidity vacuum price tends to revisit to rebalance.
    Distinct from an FVG (which is intrabar overlap); this is an actual session/news gap.
    """
    if len(bars) < atr_n + 2:
        return None
    a = atr(bars, atr_n)
    if a <= 0:
        return None
    prev, cur = bars[-2], bars[-1]
    gap = cur.open - prev.close
    if gap >= mult * a:        # gapped up -> bullish vacuum below
        return LiquidityVoid(Direction.BULL, top=cur.open, bottom=prev.close,
                             ts=cur.ts, index=len(bars) - 1)
    if -gap >= mult * a:       # gapped down -> bearish vacuum above
        return LiquidityVoid(Direction.BEAR, top=prev.close, bottom=cur.open,
                             ts=cur.ts, index=len(bars) - 1)
    return None


def update_void_states(voids: list[LiquidityVoid], bar: Bar) -> None:
    for v in voids:
        if not v.filled and (v.contains(bar.low) or v.contains(bar.high)):
            v.filled = True


def nearest_unfilled_void(voids: list[LiquidityVoid], price: float, direction: Direction):
    """Closest unfilled void in the trade direction — a rebalance target."""
    if direction is Direction.BULL:
        cands = [v for v in voids if not v.filled and v.mid > price]
        return min(cands, key=lambda v: v.mid - price) if cands else None
    cands = [v for v in voids if not v.filled and v.mid < price]
    return max(cands, key=lambda v: v.mid) if cands else None
