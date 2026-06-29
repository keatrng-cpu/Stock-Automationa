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
        hi = bars[i].high
        lo = bars[i].low
        # Direct neighbor comparison (no per-bar max()/min() generators — much faster).
        is_high = hi > bars[i - 1].high
        is_low = lo < bars[i - 1].low
        if is_high:
            for j in range(1, k + 1):
                if bars[i - j].high > hi or bars[i + j].high > hi:
                    is_high = False
                    break
        if is_low:
            for j in range(1, k + 1):
                if bars[i - j].low < lo or bars[i + j].low < lo:
                    is_low = False
                    break
        if is_high:
            swings.append(SwingPoint(i, bars[i].ts, hi, "high"))
        if is_low:
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


def detect_cisd(bars: list[Bar], direction: Direction, lookback: int = 12) -> bool:
    """Change in State of Delivery: price closes back through the open of the most
    recent opposite-direction candle run — the moment delivery flips.

    Bullish CISD: after a down-run, the latest close exceeds the OPEN of the first
    down candle of that run (the down sequence has been reclaimed). Bearish is the
    mirror. A precise confirmation that the algo has switched sides.
    """
    if len(bars) < 3:
        return False
    last = bars[-1]
    window = bars[-lookback:]
    if direction is Direction.BULL:
        # Find the most recent contiguous run of down candles ending before `last`.
        i = len(window) - 2
        while i >= 0 and window[i].close >= window[i].open:
            i -= 1
        if i < 0:
            return False
        run_start = i
        while run_start - 1 >= 0 and window[run_start - 1].close < window[run_start - 1].open:
            run_start -= 1
        return last.close > window[run_start].open
    else:
        i = len(window) - 2
        while i >= 0 and window[i].close <= window[i].open:
            i -= 1
        if i < 0:
            return False
        run_start = i
        while run_start - 1 >= 0 and window[run_start - 1].close > window[run_start - 1].open:
            run_start -= 1
        return last.close < window[run_start].open


def detect_rejection_block(bars: list[Bar], direction: Direction,
                           lookback: int = 5, wick_mult: float = 2.0) -> bool:
    """Rejection block: a recent candle with a long wick rejecting price in the trade
    direction (a bullish rejection = long lower wick; bearish = long upper wick).
    """
    for b in bars[-lookback:]:
        body = b.body or 0.0001
        upper = b.high - max(b.open, b.close)
        lower = min(b.open, b.close) - b.low
        if direction is Direction.BULL and lower >= wick_mult * body and lower > upper:
            return True
        if direction is Direction.BEAR and upper >= wick_mult * body and upper > lower:
            return True
    return False


def premium_discount(bars: list[Bar], lookback: int = 50) -> tuple[float, float, float]:
    """Return (low, equilibrium, high) of the recent dealing range.

    Price above equilibrium = premium (favor shorts); below = discount (favor longs).
    """
    window = bars[-lookback:] if len(bars) > lookback else bars
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    return lo, (hi + lo) / 2.0, hi
