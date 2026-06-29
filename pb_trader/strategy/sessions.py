"""Session levels, PDH/PDL, and opening-price bias — ICT time-and-price references.

The liquidity that matters most sits at *significant* levels: previous day high/low,
session highs/lows (Asia/London/NY), the true day open (midnight) and the 08:30 open.
Price relative to the day open is ICT's opening-price bias. Tracked incrementally so
it's O(1) per bar. Assumes bar timestamps are in exchange/NY time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import Bar, Direction

_INF = float("inf")


def session_name(hour: int) -> Optional[str]:
    if hour < 2 or hour >= 18:
        return "Asia"
    if 2 <= hour < 8:
        return "London"
    if 8 <= hour < 16:
        return "NY"
    return None


@dataclass
class SessionTracker:
    day: object = None
    day_open: Optional[float] = None       # true day open (first bar / midnight)
    ny_open: Optional[float] = None        # 08:30 open
    cur_high: float = float("-inf")
    cur_low: float = _INF
    pdh: Optional[float] = None            # previous day high / low
    pdl: Optional[float] = None
    sessions: dict = field(default_factory=dict)   # name -> (high, low) for current day
    # Weekly / monthly PD arrays.
    week: object = None
    month: object = None
    wk_high: float = float("-inf")
    wk_low: float = _INF
    mo_high: float = float("-inf")
    mo_low: float = _INF
    pwh: Optional[float] = None            # previous week high / low
    pwl: Optional[float] = None
    pmh: Optional[float] = None            # previous month high / low
    pml: Optional[float] = None

    def update(self, bar: Bar) -> None:
        d = bar.ts.date()
        if d != self.day:
            if self.day is not None and self.cur_high > float("-inf"):
                self.pdh, self.pdl = self.cur_high, self.cur_low
            self.day = d
            self.day_open = bar.open
            self.ny_open = None
            self.cur_high, self.cur_low = bar.high, bar.low
            self.sessions = {}
        else:
            self.cur_high = max(self.cur_high, bar.high)
            self.cur_low = min(self.cur_low, bar.low)

        # Weekly roll (ISO week) and monthly roll.
        wk = bar.ts.isocalendar()[:2]
        if wk != self.week:
            if self.week is not None and self.wk_high > float("-inf"):
                self.pwh, self.pwl = self.wk_high, self.wk_low
            self.week = wk
            self.wk_high, self.wk_low = bar.high, bar.low
        else:
            self.wk_high = max(self.wk_high, bar.high)
            self.wk_low = min(self.wk_low, bar.low)
        mo = (bar.ts.year, bar.ts.month)
        if mo != self.month:
            if self.month is not None and self.mo_high > float("-inf"):
                self.pmh, self.pml = self.mo_high, self.mo_low
            self.month = mo
            self.mo_high, self.mo_low = bar.high, bar.low
        else:
            self.mo_high = max(self.mo_high, bar.high)
            self.mo_low = min(self.mo_low, bar.low)

        h, m = bar.ts.hour, bar.ts.minute
        if self.ny_open is None and (h > 8 or (h == 8 and m >= 30)) and h < 16:
            self.ny_open = bar.open

        name = session_name(h)
        if name:
            hi, lo = self.sessions.get(name, (float("-inf"), _INF))
            self.sessions[name] = (max(hi, bar.high), min(lo, bar.low))

    def significant_levels(self) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        if self.pdh is not None:
            out += [("PDH", self.pdh), ("PDL", self.pdl)]
        if self.day_open is not None:
            out.append(("DayOpen", self.day_open))
        if self.ny_open is not None:
            out.append(("NYOpen", self.ny_open))
        for nm, (hi, lo) in self.sessions.items():
            if hi > float("-inf"):
                out += [(f"{nm}H", hi), (f"{nm}L", lo)]
        if self.pwh is not None:
            out += [("PWH", self.pwh), ("PWL", self.pwl)]
        if self.pmh is not None:
            out += [("PMH", self.pmh), ("PML", self.pml)]
        return out

    def weekly_pd_bias(self, price: float) -> Optional[Direction]:
        """Weekly premium/discount: below the weekly equilibrium favors longs (discount),
        above favors shorts (premium). Uses the previous week's range as the array."""
        if self.pwh is None or self.pwl is None or self.pwh <= self.pwl:
            return None
        eq = (self.pwh + self.pwl) / 2.0
        return Direction.BULL if price < eq else Direction.BEAR

    def is_significant(self, price: float, tol: float) -> Optional[str]:
        """Name of the significant level within `tol` of `price`, else None."""
        best, bestd = None, tol
        for nm, lvl in self.significant_levels():
            d = abs(price - lvl)
            if d <= bestd:
                best, bestd = nm, d
        return best

    def opening_bias(self, price: float) -> Optional[Direction]:
        if self.day_open is None:
            return None
        return Direction.BULL if price >= self.day_open else Direction.BEAR
