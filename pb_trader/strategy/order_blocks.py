"""Order blocks — the core SMC entry object.

A bullish order block (demand) is the last down-close candle before an up
displacement that leaves a fair-value gap; a bearish order block (supply) is the
last up-close candle before a down displacement. Price tends to return to mitigate
the block before continuing. We derive blocks from detected FVGs (the displacement
that creates a gap is exactly what validates the block).
"""
from __future__ import annotations

from ..models import Bar, BreakerBlock, Direction, FVG, OrderBlock


def order_blocks_from_fvgs(bars: list[Bar], fvgs: list[FVG],
                           search: int = 5) -> list[OrderBlock]:
    """For each fresh FVG, find the originating opposing candle = the order block."""
    blocks: list[OrderBlock] = []
    for f in fvgs:
        if f.inverted:
            continue
        i = f.index  # the 3rd candle of the gap (displacement close)
        origin = i - 2
        if f.direction is Direction.BULL:
            # Last down candle at/before the displacement origin -> demand block.
            for j in range(origin, max(origin - search, -1), -1):
                if bars[j].close < bars[j].open:
                    blocks.append(OrderBlock(Direction.BULL, top=bars[j].high,
                                             bottom=bars[j].low, ts=bars[j].ts, index=j))
                    break
        else:
            for j in range(origin, max(origin - search, -1), -1):
                if bars[j].close > bars[j].open:
                    blocks.append(OrderBlock(Direction.BEAR, top=bars[j].high,
                                             bottom=bars[j].low, ts=bars[j].ts, index=j))
                    break
    return blocks


def order_block_at_formation(bars: list[Bar], direction: Direction,
                             search: int = 5):
    """The order block for an FVG that just completed on the latest bar.

    The displacement's 3rd candle is bars[-1]; the origin is bars[-3]. Walk back from
    there for the last opposing candle = the order block.
    """
    origin = len(bars) - 3
    if origin < 0:
        return None
    if direction is Direction.BULL:
        for j in range(origin, max(origin - search, -1), -1):
            if bars[j].close < bars[j].open:
                return OrderBlock(Direction.BULL, top=bars[j].high, bottom=bars[j].low,
                                  ts=bars[j].ts, index=j)
    else:
        for j in range(origin, max(origin - search, -1), -1):
            if bars[j].close > bars[j].open:
                return OrderBlock(Direction.BEAR, top=bars[j].high, bottom=bars[j].low,
                                  ts=bars[j].ts, index=j)
    return None


def flip_broken_blocks(blocks: list[OrderBlock], breakers: list[BreakerBlock],
                       bar: Bar) -> None:
    """Incremental breaker detection: a block price closes through flips polarity."""
    for ob in blocks:
        if ob.broken:
            continue
        if ob.direction is Direction.BULL and bar.close < ob.bottom:
            ob.broken = True
            breakers.append(BreakerBlock(Direction.BEAR, ob.top, ob.bottom, ob.ts, ob.index))
        elif ob.direction is Direction.BEAR and bar.close > ob.top:
            ob.broken = True
            breakers.append(BreakerBlock(Direction.BULL, ob.top, ob.bottom, ob.ts, ob.index))


def update_block_states(blocks: list[OrderBlock], bar: Bar) -> None:
    """Mark a block mitigated once price trades back into its zone."""
    for ob in blocks:
        if ob.mitigated:
            continue
        if ob.contains(bar.low) or ob.contains(bar.high) or ob.contains(bar.close):
            ob.mitigated = True


def fresh_blocks(blocks: list[OrderBlock], direction: Direction) -> list[OrderBlock]:
    """Unmitigated blocks aligned with the given direction."""
    return [b for b in blocks if not b.mitigated and b.direction is direction]


def retesting_block(blocks: list[OrderBlock], direction: Direction,
                    bar: Bar) -> bool:
    """True if the current bar is tapping a fresh, aligned order block."""
    for ob in blocks:
        if ob.direction is not direction:
            continue
        if ob.contains(bar.low) or ob.contains(bar.high) or ob.contains(bar.close):
            return True
    return False


def find_breakers(blocks: list[OrderBlock], bars: list[Bar]) -> list[BreakerBlock]:
    """Derive breaker blocks: an order block that price has *closed through* (failed)
    flips polarity and becomes a breaker on the opposite side.

    A bullish (demand) OB broken to the downside -> bearish breaker (resistance).
    A bearish (supply) OB broken to the upside -> bullish breaker (support).
    """
    if not bars:
        return []
    breakers: list[BreakerBlock] = []
    for ob in blocks:
        after = bars[ob.index + 1:]
        if not after:
            continue
        if ob.direction is Direction.BULL:
            if any(b.close < ob.bottom for b in after):
                breakers.append(BreakerBlock(Direction.BEAR, ob.top, ob.bottom,
                                             ob.ts, ob.index))
        else:
            if any(b.close > ob.top for b in after):
                breakers.append(BreakerBlock(Direction.BULL, ob.top, ob.bottom,
                                             ob.ts, ob.index))
    return breakers


def retesting_propulsion(blocks: list[OrderBlock], direction: Direction, bar: Bar,
                         tol: float) -> bool:
    """Propulsion block (ICT): price retests an order block that is STACKED with another
    same-direction unmitigated block nearby — the move is propelling off layered demand
    (bull) or supply (bear), a higher-probability continuation than a lone block.
    """
    aligned = [b for b in blocks if b.direction is direction and not b.mitigated]
    here = [b for b in aligned
            if b.contains(bar.low) or b.contains(bar.high) or b.contains(bar.close)]
    if not here:
        return False
    ref = here[0]
    # Is there a second aligned block stacked within `tol` of the retested one?
    for b in aligned:
        if b is ref:
            continue
        if abs(b.mid - ref.mid) <= tol:
            return True
    return False


def retesting_breaker(breakers: list[BreakerBlock], direction: Direction,
                      bar: Bar) -> bool:
    for bk in breakers:
        if bk.direction is not direction:
            continue
        if bk.contains(bar.low) or bk.contains(bar.high) or bk.contains(bar.close):
            return True
    return False
