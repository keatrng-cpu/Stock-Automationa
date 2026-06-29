"""Market structure: swing points, BOS (Break of Structure), CHOCH (Change of Character)."""
from __future__ import annotations

from typing import Optional

from ..models import Bar, Direction, StructureEvent, SwingPoint


def find_swings(bars: list[Bar], k: int = 2) -> list[SwingPoint]:
    """Fractal swing detection.

    A swing high at i requires high[i] to be the max of the window [i-k, i+k].
    A swing low at i requires low[i] to be the min of that window.
    """
    swings: list[SwingPoint] = []
    n = len(bars)
    for i in range(k, n - k):
        window = bars[i - k:i + k + 1]
        hi = bars[i].high
        lo = bars[i].low
        if hi == max(b.high for b in window) and hi > bars[i - 1].high:
            swings.append(SwingPoint(i, bars[i].ts, hi, "high"))
        if lo == min(b.low for b in window) and lo < bars[i - 1].low:
            swings.append(SwingPoint(i, bars[i].ts, lo, "low"))
    return swings


class StructureState:
    """Incrementally tracks trend and emits BOS / CHOCH events.

    Trend is BULL while we keep breaking prior swing highs; a close below the most
    recent protected swing low flips character (CHOCH) and vice versa.
    """

    def __init__(self) -> None:
        self.trend: Optional[Direction] = None
        self.last_high: Optional[SwingPoint] = None
        self.last_low: Optional[SwingPoint] = None
        self.events: list[StructureEvent] = []

    def update(self, swings: list[SwingPoint], bar: Bar, index: int) -> Optional[StructureEvent]:
        # Refresh the most recent confirmed swing high/low up to this bar.
        for sp in swings:
            if sp.index >= index:
                break
            if sp.kind == "high":
                self.last_high = sp
            else:
                self.last_low = sp

        event: Optional[StructureEvent] = None
        if self.last_high and bar.close > self.last_high.price:
            if self.trend == Direction.BEAR:
                event = StructureEvent(index, bar.ts, "CHOCH", Direction.BULL, self.last_high.price)
            elif self.trend == Direction.BULL:
                event = StructureEvent(index, bar.ts, "BOS", Direction.BULL, self.last_high.price)
            self.trend = Direction.BULL
        elif self.last_low and bar.close < self.last_low.price:
            if self.trend == Direction.BULL:
                event = StructureEvent(index, bar.ts, "CHOCH", Direction.BEAR, self.last_low.price)
            elif self.trend == Direction.BEAR:
                event = StructureEvent(index, bar.ts, "BOS", Direction.BEAR, self.last_low.price)
            self.trend = Direction.BEAR

        if event:
            self.events.append(event)
        return event


def premium_discount(bars: list[Bar], lookback: int = 50) -> tuple[float, float, float]:
    """Return (low, equilibrium, high) of the recent dealing range.

    Price above equilibrium = premium (favor shorts); below = discount (favor longs).
    """
    window = bars[-lookback:] if len(bars) > lookback else bars
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    return lo, (hi + lo) / 2.0, hi
