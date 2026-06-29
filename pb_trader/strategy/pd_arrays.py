"""Premium/Discount array refinements: Consequent Encroachment + Balanced Price Range.

- Consequent Encroachment (CE): the 50% of a fair value gap. ICT teaches that the CE is
  the optimal fill — entering at the gap's midpoint rather than its edge gives a better
  price and tighter risk.
- Balanced Price Range (BPR): where a bullish FVG and a bearish FVG overlap. That shared
  zone has been delivered in both directions and is a high-probability reversal area.
"""
from __future__ import annotations

from ..models import Direction, FVG


def consequent_encroachment(fvg: FVG) -> float:
    """The 50% level of the gap — the CE / mean threshold."""
    return (fvg.top + fvg.bottom) / 2.0


def detect_bpr(fvgs: list[FVG], lookback: int = 20) -> list[tuple[float, float]]:
    """Overlapping bull/bear FVGs → balanced price ranges (returns (bottom, top) zones)."""
    recent = fvgs[-lookback:]
    bulls = [f for f in recent if not f.inverted and f.direction is Direction.BULL]
    bears = [f for f in recent if not f.inverted and f.direction is Direction.BEAR]
    out: list[tuple[float, float]] = []
    for a in bulls:
        for b in bears:
            lo = max(a.bottom, b.bottom)
            hi = min(a.top, b.top)
            if lo < hi:                     # genuine overlap
                out.append((lo, hi))
    return out


def in_bpr(price: float, bprs: list[tuple[float, float]]) -> bool:
    return any(lo <= price <= hi for lo, hi in bprs)
