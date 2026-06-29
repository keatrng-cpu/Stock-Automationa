"""Scenario projection — be PREPARED for several market paths, not just one.

Elite traders don't predict a single outcome; they map the **decision tree** and pre-plan
a reaction to each branch ("if price sweeps PDH and fails → I'm short to PDL; if it
displaces through and retests → I'm long the continuation"). This module turns the live
context (price, significant liquidity, HTF bias, regime, premium/discount) into a ranked
set of `Scenario` objects — each an if/then with a trigger, an invalidation, a draw-on-
liquidity target, and a probability. The engine then trades only the branch that actually
confirms, with the others already rehearsed.

Pure and deterministic: feed it state, get scenarios. No look-ahead, no fabrication —
every level it names comes from the real levels you pass in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import Direction


@dataclass
class Scenario:
    name: str                      # "Bullish continuation", "Bearish reversal", "Range rotation"
    bias: Optional[Direction]      # the direction the branch trades (None = two-sided range)
    probability: float             # 0..1, normalized across the projected set
    trigger: str                   # the if/then condition that ARMS this branch
    invalidation: Optional[float]  # price that kills the branch
    target: Optional[float]        # draw on liquidity (where price is reaching for)
    target_name: str = ""          # the liquidity pool's label (e.g. "PDH")
    narrative: str = ""            # short PB/ICT read of the path

    def line(self, price: float) -> str:
        arrow = {Direction.BULL: "↑", Direction.BEAR: "↓"}.get(self.bias, "↔")
        tgt = f"{self.target_name} {self.target:.2f}" if self.target is not None else "—"
        inv = f"{self.invalidation:.2f}" if self.invalidation is not None else "—"
        return (f"  {self.probability:>4.0%} {arrow} {self.name:<22} "
                f"trigger: {self.trigger}  → draw {tgt}  (invalid {inv})")


def _split_levels(price: float, levels: list[tuple[str, float]]):
    """Liquidity above (BSL) and below (SSL), each sorted by distance from price."""
    above = sorted([(n, v) for n, v in levels if v > price], key=lambda x: x[1])
    below = sorted([(n, v) for n, v in levels if v < price], key=lambda x: x[1], reverse=True)
    return above, below


def _bias_vote(htf_bias, htf2_bias, weekly_bias, opening_bias) -> int:
    """Net directional conviction from the stacked top-down reads (+bull / -bear)."""
    score = 0
    for b, w in ((htf_bias, 2), (htf2_bias, 2), (weekly_bias, 1), (opening_bias, 1)):
        if b == Direction.BULL:
            score += w
        elif b == Direction.BEAR:
            score -= w
    return score


def project_scenarios(price: float, levels: list[tuple[str, float]],
                      htf_bias: Optional[Direction] = None,
                      htf2_bias: Optional[Direction] = None,
                      weekly_bias: Optional[Direction] = None,
                      opening_bias: Optional[Direction] = None,
                      regime: str = "na", volatility: str = "na",
                      buffer: float = 0.0) -> list[Scenario]:
    """Project the primary + alternate market scenarios from the live context.

    Returns scenarios sorted by probability (highest first). The probabilities encode:
    top-down bias conviction, regime (trending favors continuation, ranging favors
    rotation), and which side liquidity rests on (the draw)."""
    above, below = _split_levels(price, levels)
    near_bsl = above[0] if above else None       # nearest pool above (buy-side liquidity)
    near_ssl = below[0] if below else None        # nearest pool below (sell-side liquidity)
    ext_bsl = above[-1] if above else None        # external draw above
    ext_ssl = below[-1] if below else None         # external draw below

    vote = _bias_vote(htf_bias, htf2_bias, weekly_bias, opening_bias)
    trending = regime == "trending"
    ranging = regime in ("ranging", "dead")

    scenarios: list[Scenario] = []

    # --- Continuation in the direction of conviction (the primary when trend+bias agree) ---
    cont_dir = Direction.BULL if vote >= 0 else Direction.BEAR
    if cont_dir == Direction.BULL:
        sweep = near_ssl                          # grab discount liquidity first
        draw = ext_bsl or near_bsl                # then reach for buy-side draw
        trig = (f"sweep {sweep[0]} {sweep[1]:.2f} then bullish displacement / iFVG reclaim"
                if sweep else "bullish displacement + iFVG reclaim from discount")
        scenarios.append(Scenario(
            "Bullish continuation", Direction.BULL, 0.0, trig,
            invalidation=(sweep[1] if sweep else None),
            target=(draw[1] if draw else None), target_name=(draw[0] if draw else ""),
            narrative="Top-down bias up: take sell-side, then deliver to buy-side draw."))
    else:
        sweep = near_bsl
        draw = ext_ssl or near_ssl
        trig = (f"sweep {sweep[0]} {sweep[1]:.2f} then bearish displacement / iFVG reclaim"
                if sweep else "bearish displacement + iFVG reclaim from premium")
        scenarios.append(Scenario(
            "Bearish continuation", Direction.BEAR, 0.0, trig,
            invalidation=(sweep[1] if sweep else None),
            target=(draw[1] if draw else None), target_name=(draw[0] if draw else ""),
            narrative="Top-down bias down: take buy-side, then deliver to sell-side draw."))

    # --- Reversal against conviction (the alternate to keep you honest) ---
    if cont_dir == Direction.BULL:
        grab = near_bsl
        draw = near_ssl or ext_ssl
        trig = (f"sweep {grab[0]} {grab[1]:.2f} and FAIL (MSS down) — liquidity grab"
                if grab else "failure swing at premium + MSS down")
        scenarios.append(Scenario(
            "Bearish reversal", Direction.BEAR, 0.0, trig,
            invalidation=(grab[1] if grab else None),
            target=(draw[1] if draw else None), target_name=(draw[0] if draw else ""),
            narrative="Alternate: buy-side raid fails, structure shifts down."))
    else:
        grab = near_ssl
        draw = near_bsl or ext_bsl
        trig = (f"sweep {grab[0]} {grab[1]:.2f} and FAIL (MSS up) — liquidity grab"
                if grab else "failure swing at discount + MSS up")
        scenarios.append(Scenario(
            "Bullish reversal", Direction.BULL, 0.0, trig,
            invalidation=(grab[1] if grab else None),
            target=(draw[1] if draw else None), target_name=(draw[0] if draw else ""),
            narrative="Alternate: sell-side raid fails, structure shifts up."))

    # --- Range rotation (dominant when there's no clean trend) ---
    if near_bsl and near_ssl:
        scenarios.append(Scenario(
            "Range rotation", None, 0.0,
            f"fade {near_bsl[0]} {near_bsl[1]:.2f} / {near_ssl[0]} {near_ssl[1]:.2f} extremes",
            invalidation=None, target=None,
            narrative="No clean displacement: rotate between local pools, fade the edges."))

    # --- Probability assignment from conviction strength + regime, then normalize ---
    conv = min(1.0, abs(vote) / 6.0)              # 0 (balanced) .. 1 (fully stacked)
    weights = []
    for s in scenarios:
        if s.name.endswith("continuation"):
            w = 0.45 + 0.30 * conv + (0.10 if trending else -0.10)
        elif s.name.endswith("reversal"):
            w = 0.30 - 0.15 * conv + (0.05 if ranging else 0.0)
        else:  # range rotation
            w = 0.20 + (0.35 if ranging else -0.10)
        weights.append(max(0.05, w))
    total = sum(weights) or 1.0
    for s, w in zip(scenarios, weights):
        s.probability = w / total

    scenarios.sort(key=lambda s: s.probability, reverse=True)
    return scenarios
