"""Adaptive control — the system reacts to its own recent results and the market.

Two levers, both defensive (they protect capital; they never get reckless):
  - risk_multiplier: cut size after a losing streak / drawdown, recover to 1.0 as the
    account makes new highs. Never exceeds 1.0 by default (no martingale).
  - threshold_bump: temporarily raise the A+ confluence bar after consecutive losses,
    so the system gets pickier exactly when it's cold.

This is the trading equivalent of "stop pressing when you're tilted."
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .models import Trade


@dataclass
class AdaptiveRisk:
    window: int = 20
    max_threshold_bump: float = 0.06
    min_risk_mult: float = 0.4
    recent: deque = field(default_factory=lambda: deque(maxlen=20))
    loss_streak: int = 0
    win_streak: int = 0
    peak_equity: float = 0.0
    equity: float = 0.0

    def record(self, trade: Trade, equity: float | None = None) -> None:
        self.recent.append(1 if trade.pnl >= 0 else 0)
        if trade.pnl >= 0:
            self.win_streak += 1
            self.loss_streak = 0
        else:
            self.loss_streak += 1
            self.win_streak = 0
        if equity is not None:
            self.equity = equity
            self.peak_equity = max(self.peak_equity, equity)

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    def risk_multiplier(self) -> float:
        """Scale size down on a losing streak or in drawdown; never above 1.0."""
        mult = 1.0
        if self.loss_streak >= 2:
            mult -= 0.2 * (self.loss_streak - 1)      # -20% per loss beyond the first
        mult -= self.drawdown                          # extra cut proportional to drawdown
        return max(self.min_risk_mult, min(1.0, mult))

    def threshold_bump(self) -> float:
        """Raise the A+ bar after consecutive losses (get pickier when cold)."""
        if self.loss_streak < 2:
            return 0.0
        return min(self.max_threshold_bump, 0.02 * (self.loss_streak - 1))

    def state(self) -> str:
        return (f"streak: {'W'+str(self.win_streak) if self.win_streak else 'L'+str(self.loss_streak)}"
                f"  risk×{self.risk_multiplier():.2f}  +thr {self.threshold_bump():.2f}"
                f"  dd {self.drawdown:.0%}")
