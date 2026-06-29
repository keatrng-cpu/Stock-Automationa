"""Account-growth milestone tracking — $1k → $10k → $50k → $100k.

Keeps the mission front-and-center: where the account is, distance to the next
milestone, and (since sizing is fixed-fractional) a rough trade-count estimate to get
there at the current expectancy. Honest math, no hype.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MILESTONES = [1_000, 10_000, 50_000, 100_000]


@dataclass
class GoalStatus:
    equity: float
    stage: int                 # 0-based index of the milestone just passed
    next_milestone: float | None
    pct_to_next: float         # 0..1 progress from current stage to next
    multiple_to_next: float    # x times current equity needed to reach next
    overall_pct: float         # progress across the whole $1k->$100k journey


def status(equity: float) -> GoalStatus:
    stage = 0
    for i, m in enumerate(MILESTONES):
        if equity >= m:
            stage = i
    nxt = MILESTONES[stage + 1] if stage + 1 < len(MILESTONES) else None
    base = MILESTONES[stage]
    if nxt:
        pct = (equity - base) / (nxt - base)
        mult = nxt / equity if equity > 0 else float("inf")
    else:
        pct, mult = 1.0, 1.0
    overall = min(1.0, max(0.0, math.log10(max(equity, 1) / MILESTONES[0]) /
                           math.log10(MILESTONES[-1] / MILESTONES[0])))
    return GoalStatus(equity, stage, nxt, pct, mult, overall)


def trades_to_next(equity: float, expectancy_r: float, risk_pct: float) -> float | None:
    """Rough estimate of winning-expectancy trades to reach the next milestone.

    Each trade grows equity by ~ (expectancy_r * risk_pct) on average (compounding).
    Returns None if expectancy is non-positive (can't get there losing).
    """
    g = status(equity)
    if g.next_milestone is None:
        return 0.0
    growth_per_trade = expectancy_r * risk_pct
    if growth_per_trade <= 0:
        return None
    # equity * (1+g)^n = next  ->  n = ln(next/equity)/ln(1+g)
    return math.log(g.next_milestone / equity) / math.log(1 + growth_per_trade)


def render(equity: float, expectancy_r: float = 0.0, risk_pct: float = 0.02) -> str:
    g = status(equity)
    bar_len = 24
    filled = int(g.overall_pct * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines = [
        f"  Account: ${equity:,.2f}   [{bar}] {g.overall_pct:.0%} of $1k→$100k",
    ]
    if g.next_milestone:
        lines.append(f"  Next milestone: ${g.next_milestone:,.0f} "
                     f"({g.pct_to_next:.0%} there, need {g.multiple_to_next:.2f}x)")
        n = trades_to_next(equity, expectancy_r, risk_pct)
        if n is not None and expectancy_r > 0:
            lines.append(f"  At {expectancy_r:+.2f}R expectancy & {risk_pct:.0%} risk: "
                         f"~{math.ceil(n)} winning-expectancy trades to next milestone")
        elif expectancy_r <= 0:
            lines.append("  Expectancy ≤ 0 — no positive path to the next milestone yet. "
                         "Validate the edge on real data before sizing up.")
    else:
        lines.append("  🏁 Final milestone reached — $100,000.")
    return "\n".join(lines)
