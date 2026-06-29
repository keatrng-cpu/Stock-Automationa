"""Optimal Trade Entry (OTE) — the ICT fib retracement entry zone.

After a displacement leg, smart money typically re-enters on a deep retracement,
classically the 0.62–0.79 region of the impulse leg (the "OTE"). Entering there
gives the best risk:reward against the leg's origin.
"""
from __future__ import annotations

from typing import Optional

from ..models import Bar, Direction, Side
from .structure import find_swings


OTE_LOW = 0.62
OTE_HIGH = 0.79


def dealing_range(bars: list[Bar], swing_k: int = 2) -> Optional[tuple[float, float]]:
    """Most recent swing low/high pair defining the current dealing range."""
    swings = find_swings(bars, swing_k)
    last_high = next((s.price for s in reversed(swings) if s.kind == "high"), None)
    last_low = next((s.price for s in reversed(swings) if s.kind == "low"), None)
    if last_high is None or last_low is None or last_high <= last_low:
        return None
    return last_low, last_high


def in_ote(entry: float, low: float, high: float, side: Side,
           ote_low: float = OTE_LOW, ote_high: float = OTE_HIGH) -> bool:
    """Is `entry` inside the [ote_low, ote_high] retracement of the leg [low, high]?"""
    rng = high - low
    if rng <= 0:
        return False
    if side is Side.LONG:
        # Retracing down from the high: deeper retrace = lower price.
        hi_z = high - ote_low * rng
        lo_z = high - ote_high * rng
        return lo_z <= entry <= hi_z
    else:
        # Retracing up from the low.
        lo_z = low + ote_low * rng
        hi_z = low + ote_high * rng
        return lo_z <= entry <= hi_z


def ote_check(bars: list[Bar], entry: float, side: Side, swing_k: int = 2,
              ote_low: float = OTE_LOW, ote_high: float = OTE_HIGH) -> bool:
    rng = dealing_range(bars, swing_k)
    if rng is None:
        return False
    return in_ote(entry, rng[0], rng[1], side, ote_low, ote_high)
