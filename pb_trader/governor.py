"""Session governor — keeps the engine ACTIVE at a sane cadence, and SAFE within the day.

Two jobs, both about discipline rather than perception:

1. **Cadence**: aim for ~3 STRONG or ~5 MEDIUM A+ trades per week. This is a CEILING, not a
   quota — it NEVER forces a trade or lowers the bar to hit a number. Both tiers stay at/above
   the documented 0.75 confluence floor — "strong" is the high-conviction A+ (≥ strong bar),
   "medium" is a still-valid A+ a notch below. Strong is always preferred; mediums are merely
   *permitted* so a quiet stretch isn't dark for a month. If no genuine A+ prints, it takes
   none. Weekly caps stop overtrading; nothing below the floor ever trades.

2. **Daily-loss circuit breaker**: if the account gives back more than `daily_loss_limit_pct`
   of the day's starting equity, halt NEW entries until the next session. Standard prop-firm
   discipline — protect the day, live to trade tomorrow. (Open positions still manage out.)

The governor is pure bookkeeping the backtest/live loop consults; every block is explainable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionGovernor:
    strong_threshold: float = 0.80     # "strong" A+ (high conviction)
    medium_threshold: float = 0.75     # "medium" A+ (documented floor)
    weekly_strong_target: int = 3      # aim: 3 strong …
    weekly_medium_target: int = 5      # … OR 5 medium per week
    daily_cap: int = 2                 # hard ceiling on entries per day
    daily_loss_limit_pct: float = 0.06 # halt new entries after this daily drawdown

    # --- state ---
    _day: object = None
    _week: object = None
    day_start_equity: float = 0.0
    halted_today: bool = False
    halt_day_count: int = 0            # how many days the breaker tripped (telemetry)
    today_entries: int = 0
    wk_strong: int = 0
    wk_medium: int = 0
    reasons: list = field(default_factory=list)

    def roll(self, ts, equity: float) -> None:
        """Call each bar: detect day/week rollover and reset the right counters."""
        d = ts.date()
        wk = ts.isocalendar()[:2]            # (ISO year, ISO week)
        if d != self._day:
            self._day = d
            self.day_start_equity = equity
            self.halted_today = False
            self.today_entries = 0
        if wk != self._week:
            self._week = wk
            self.wk_strong = 0
            self.wk_medium = 0

    def classify(self, confluence: float) -> Optional[str]:
        if confluence >= self.strong_threshold:
            return "strong"
        if confluence >= self.medium_threshold:
            return "medium"
        return None                          # below the floor — not an A+ at all

    def _weekly_budget_left(self, grade: str) -> bool:
        """Cadence: strong up to its target; medium up to its target, but the two share a
        combined ceiling so '3 strong OR 5 medium' doesn't become '3 strong AND 5 medium'."""
        # Express the week as 'strong-equivalents': a medium is worth 0.6 of a strong
        # (5 medium ≈ 3 strong). Allow a new trade while under the strong target budget.
        used = self.wk_strong + 0.6 * self.wk_medium
        if grade == "strong":
            return self.wk_strong < self.weekly_strong_target and used < self.weekly_strong_target
        return self.wk_medium < self.weekly_medium_target and used < self.weekly_strong_target

    def breaker_tripped(self, equity: float) -> bool:
        if self.day_start_equity <= 0:
            return False
        dd = (self.day_start_equity - equity) / self.day_start_equity
        return dd >= self.daily_loss_limit_pct

    def can_enter(self, confluence: float, equity: float) -> tuple[bool, str]:
        """Decide whether a fresh entry is allowed right now, with an explainable reason."""
        if self.halted_today or self.breaker_tripped(equity):
            if not self.halted_today:
                self.halt_day_count += 1        # first trip today
            self.halted_today = True
            return False, (f"daily circuit breaker — down ≥{self.daily_loss_limit_pct:.0%} "
                           f"on the day, no new entries")
        if self.today_entries >= self.daily_cap:
            return False, f"daily cap reached ({self.daily_cap} trades)"
        grade = self.classify(confluence)
        if grade is None:
            return False, f"below A+ floor {self.medium_threshold:.0%}"
        if not self._weekly_budget_left(grade):
            return False, (f"weekly cadence met ({self.wk_strong} strong / {self.wk_medium} "
                           f"medium) — quality over quantity")
        return True, f"{grade} A+ — within weekly cadence"

    def record_entry(self, confluence: float) -> str:
        grade = self.classify(confluence) or "medium"
        if grade == "strong":
            self.wk_strong += 1
        else:
            self.wk_medium += 1
        self.today_entries += 1
        return grade

    def state(self) -> str:
        return (f"week: {self.wk_strong} strong / {self.wk_medium} medium  "
                f"today: {self.today_entries}/{self.daily_cap}"
                f"{'  ⛔ HALTED' if self.halted_today else ''}")
