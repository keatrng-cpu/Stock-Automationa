"""Order blocks — the core SMC entry object.

A bullish order block (demand) is the last down-close candle before an up
displacement that leaves a fair-value gap; a bearish order block (supply) is the
last up-close candle before a down displacement. Price tends to return to mitigate
the block before continuing. We derive blocks from detected FVGs (the displacement
that creates a gap is exactly what validates the block).
"""
from __future__ import annotations

from ..models import Bar, Direction, FVG, OrderBlock


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
