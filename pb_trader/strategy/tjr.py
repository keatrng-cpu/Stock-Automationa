"""TJR-model concepts fused into the engine.

TJR's framework (ICT-derived) leans on:
  - Killzones / sessions: only hunt in high-probability windows.
  - Power of Three (PO3 / AMD): Accumulation -> Manipulation (judas sweep) ->
    Distribution. The manipulation leg sets the daily bias (sweep lows => bullish).
  - Daily bias: directional lean for the day from PO3 + prior-day levels.
  - Market Structure Shift (MSS): a displacement break of a recent LTF swing in the
    new direction — the entry-timeframe confirmation.
  - Breaker blocks: an order block that price violated then reclaimed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from ..models import Bar, Direction


# Killzones in EXCHANGE/NY local time (hour, minute) -> assumes bar.ts is NY time.
KILLZONES = {
    "London":     ((2, 0), (5, 0)),
    "NY AM":      ((8, 30), (11, 0)),
    "Silver Bullet AM": ((10, 0), (11, 0)),
    "NY PM":      ((13, 30), (16, 0)),
}


def current_killzone(ts: datetime) -> Optional[str]:
    minutes = ts.hour * 60 + ts.minute
    for name, ((sh, sm), (eh, em)) in KILLZONES.items():
        if sh * 60 + sm <= minutes < eh * 60 + em:
            return name
    return None


def in_killzone(ts: datetime) -> bool:
    return current_killzone(ts) is not None


def detect_mss(bars: list[Bar], k: int = 2, displacement_mult: float = 1.3) -> Optional[Direction]:
    """Market Structure Shift on the entry timeframe.

    Find the most recent minor swing high/low; if the latest bar closes through it
    with an above-average range (displacement), that's an MSS in that direction.
    """
    if len(bars) < 3 * k + 5:
        return None
    avg_range = sum(b.range for b in bars[-11:-1]) / 10.0 if len(bars) >= 11 else 0.0
    last = bars[-1]
    displaced = avg_range > 0 and last.range >= displacement_mult * avg_range
    if not displaced:
        return None

    # Most recent minor swing high and low before the last bar.
    recent = bars[-(3 * k + 5):-1]
    swing_high = max((b.high for b in recent), default=None)
    swing_low = min((b.low for b in recent), default=None)
    if swing_high is not None and last.close > swing_high:
        return Direction.BULL
    if swing_low is not None and last.close < swing_low:
        return Direction.BEAR
    return None


@dataclass
class DailyPO3:
    """Tracks the Power-of-Three phases per session day and derives daily bias."""
    day: Optional[date] = None
    asia_high: float = float("-inf")
    asia_low: float = float("inf")
    manipulation: Optional[str] = None     # "up" | "down" (direction of the judas sweep)
    bias: Optional[Direction] = None
    prev_high: Optional[float] = None
    prev_low: Optional[float] = None
    _today_high: float = float("-inf")
    _today_low: float = float("inf")
    reasons: list[str] = field(default_factory=list)

    def _roll_day(self, d: date) -> None:
        # Carry prior session extremes as PDH/PDL.
        if self.day is not None:
            self.prev_high = self._today_high if self._today_high != float("-inf") else self.prev_high
            self.prev_low = self._today_low if self._today_low != float("inf") else self.prev_low
        self.day = d
        self.asia_high = float("-inf")
        self.asia_low = float("inf")
        self.manipulation = None
        self.bias = None
        self._today_high = float("-inf")
        self._today_low = float("inf")

    def update(self, bar: Bar) -> None:
        d = bar.ts.date()
        if d != self.day:
            self._roll_day(d)

        self._today_high = max(self._today_high, bar.high)
        self._today_low = min(self._today_low, bar.low)

        hour = bar.ts.hour
        # Accumulation: Asia/overnight range (roughly 18:00-02:00 ET; here pre-London).
        if hour < 2 or hour >= 18:
            self.asia_high = max(self.asia_high, bar.high)
            self.asia_low = min(self.asia_low, bar.low)
            return

        # Manipulation (judas swing): early-session sweep of the Asia range.
        if self.manipulation is None and self.asia_high > float("-inf"):
            if bar.high > self.asia_high and bar.close < self.asia_high:
                self.manipulation = "up"
                self.bias = Direction.BEAR     # swept highs -> expect distribution down
            elif bar.low < self.asia_low and bar.close > self.asia_low:
                self.manipulation = "down"
                self.bias = Direction.BULL     # swept lows -> expect distribution up

    def bias_aligns(self, direction: Direction) -> bool:
        return self.bias is not None and self.bias == direction


def detect_breaker(bars: list[Bar], direction: Direction, lookback: int = 30) -> Optional[tuple[float, float]]:
    """Simplified breaker block: last opposing-close candle before the displacement leg.

    For a bullish breaker, find the most recent down-close candle preceding an up
    displacement that took out a prior swing high; its body becomes support.
    Returns (bottom, top) of the breaker zone or None.
    """
    if len(bars) < 5:
        return None
    window = bars[-lookback:]
    if direction is Direction.BULL:
        for i in range(len(window) - 2, 0, -1):
            if window[i].close < window[i].open:  # down candle
                return (min(window[i].open, window[i].close),
                        max(window[i].open, window[i].close))
    else:
        for i in range(len(window) - 2, 0, -1):
            if window[i].close > window[i].open:  # up candle
                return (min(window[i].open, window[i].close),
                        max(window[i].open, window[i].close))
    return None
