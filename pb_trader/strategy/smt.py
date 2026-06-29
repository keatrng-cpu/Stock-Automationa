"""SMT divergence between correlated indices (ES vs NQ) for instrument selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Bar


@dataclass
class SMTSignal:
    diverging: bool
    direction: str          # "bullish" | "bearish" | "none"
    superior: Optional[str]  # symbol to trade, or None to stand aside
    note: str


def _swing_extremes(bars: list[Bar], lookback: int) -> tuple[float, float]:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    return max(b.high for b in window), min(b.low for b in window)


def smt_divergence(es: list[Bar], nq: list[Bar], lookback: int = 20) -> SMTSignal:
    """Classic SMT: correlated instruments should make matching higher-highs / lower-lows.

    - Bearish SMT: one makes a higher high while the other fails (lower high) -> the
      laggard is the *weaker* instrument; favor shorts on it.
    - Bullish SMT: one makes a lower low while the other holds (higher low) -> the
      stronger instrument; favor longs on it.
    """
    if len(es) < 4 or len(nq) < 4:
        return SMTSignal(False, "none", None, "insufficient data")

    es_hi, es_lo = _swing_extremes(es, lookback)
    nq_hi, nq_lo = _swing_extremes(nq, lookback)
    es_prev_hi, es_prev_lo = _swing_extremes(es[:-lookback // 2 or None], lookback)
    nq_prev_hi, nq_prev_lo = _swing_extremes(nq[:-lookback // 2 or None], lookback)

    es_hh, nq_hh = es_hi > es_prev_hi, nq_hi > nq_prev_hi
    es_ll, nq_ll = es_lo < es_prev_lo, nq_lo < nq_prev_lo

    # Bearish divergence at highs.
    if es_hh != nq_hh:
        laggard = "NQ" if es_hh else "ES"  # the one that failed to make HH
        return SMTSignal(True, "bearish", laggard,
                         f"bearish SMT: {'ES' if es_hh else 'NQ'} made HH, {laggard} failed")

    # Bullish divergence at lows.
    if es_ll != nq_ll:
        strong = "NQ" if es_ll else "ES"   # the one that held (no LL) is stronger
        return SMTSignal(True, "bullish", strong,
                         f"bullish SMT: {'ES' if es_ll else 'NQ'} made LL, {strong} held")

    return SMTSignal(False, "none", None, "indices in agreement — no SMT edge")
