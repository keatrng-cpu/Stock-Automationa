"""The executive brain — judgment on top of the model's perception.

The PBModel sees setups; the brain decides whether to ACT, and learns. For each
candidate A+ setup it fuses three intelligences:
  - News    : blackout high-impact windows, caution around medium.
  - Adaptive: raise the bar + cut size when cold (recent losing streak / drawdown).
  - Memory  : nudge by how the setup's features have actually performed for you.

It returns a Decision (take?, size multiplier, effective threshold, reasons), and
`learn()` feeds the closed trade back into memory + adaptive. Everything is explainable
— no black box.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .adaptive import AdaptiveRisk
from .memory import TradeMemory
from .models import Setup, Trade
from .news import EconomicCalendar


@dataclass
class Decision:
    take: bool
    size_mult: float
    threshold: float
    edge: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class TradingBrain:
    base_threshold: float = 0.75
    memory: TradeMemory = field(default_factory=TradeMemory)
    adaptive: AdaptiveRisk = field(default_factory=AdaptiveRisk)
    news: EconomicCalendar = field(default_factory=EconomicCalendar)
    # How strongly memory edge nudges size: size *= (1 + edge_gain * edge), clamped.
    edge_gain: float = 0.5
    edge_veto: float = -0.5        # if memory edge is worse than this, stand aside
    # Market-condition gate: how hard a hostile regime/volatility raises the A+ bar.
    condition_gain: float = 0.10
    max_condition_bump: float = 0.05

    def decide(self, setup: Setup, equity: float) -> Decision:
        reasons: list[str] = []
        threshold = self.base_threshold
        size_mult = 1.0

        # --- News reaction ---
        rx = self.news.reaction(setup.ts)
        if rx.mode == "blackout":
            return Decision(False, 0.0, threshold, 0.0,
                            [f"news blackout: {rx.event} — stand aside"])
        if rx.mode == "caution":
            threshold += rx.threshold_add
            size_mult *= rx.size_mult
            reasons.append(f"news caution: {rx.event} (bar +{rx.threshold_add:.2f}, size ×{rx.size_mult:.1f})")

        # --- Adaptive reaction (cold streak / drawdown) ---
        bump = self.adaptive.threshold_bump()
        if bump > 0:
            threshold += bump
            reasons.append(f"cold streak — bar +{bump:.2f}")
        rmult = self.adaptive.risk_multiplier()
        if rmult < 1.0:
            size_mult *= rmult
            reasons.append(f"defensive sizing ×{rmult:.2f} (dd {self.adaptive.drawdown:.0%})")

        # --- Market-condition adaptability ---
        # Read the LIVE environment (regime + volatility) and consult how that exact
        # condition has treated us lately. Defensive-only: a hostile environment raises
        # the bar (get pickier) — it never loosens it.
        feats = setup.features or {}
        regime = feats.get("regime", "na")
        vol = feats.get("volatility", "na")
        cond = self.memory.condition_edge(regime, vol)
        if cond < 0:
            cbump = min(self.max_condition_bump, -self.condition_gain * cond)
            threshold += cbump
            reasons.append(f"hostile {regime}/{vol} env ({cond:+.2f}R) — bar +{cbump:.2f}")

        # --- Memory edge (learned from your past trades) ---
        # Aware of EVERYTHING: instrument/side/session/confluence AND which SMC/ICT/PB
        # concepts fired AND the current regime/volatility — so it knows what works and WHEN.
        edge = self.memory.edge(setup.symbol, setup.side, setup.ts, setup.tag or "",
                                setup.features)
        if edge != 0.0:
            reasons.append(f"memory edge {edge:+.2f}R (concepts+regime context)")
        if edge <= self.edge_veto:
            return Decision(False, 0.0, threshold, edge,
                            reasons + ["memory: this setup type has lost for you — skip"])
        size_mult *= max(0.25, 1.0 + self.edge_gain * edge)

        # --- Final A+ gate (effective, possibly raised) ---
        take = setup.confluence >= threshold
        if not take:
            reasons.append(f"below effective bar {threshold:.0%} (setup {setup.confluence:.0%})")
        return Decision(take, max(0.0, min(1.5, size_mult)), threshold, edge, reasons)

    def learn(self, trade: Trade, equity: Optional[float] = None) -> None:
        self.memory.record(trade)
        self.adaptive.record(trade, equity)

    def tick(self) -> None:
        """Per-bar heartbeat so the defensive posture can thaw when idle (anti-deadlock)."""
        self.adaptive.tick()

    def state(self) -> str:
        return self.adaptive.state()
