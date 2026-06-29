"""Loss journal — the brain writes down its mistakes and learns from them.

Every losing trade is a lesson. On each loss the brain introspects: which feature of the
trade (a concept, a regime, a volatility state, an instrument/side) has the worst track
record right now? That's the most likely culprit. We journalize a structured post-mortem
(persisted to JSONL so it survives sessions) and the memory layer already weighs losses
more heavily (`loss_emphasis`) so the same mistake is avoided faster next time.

This is the trader's journal, automated: not a black box, but a readable record of what
went wrong and what the system concluded — exactly what a disciplined human reviews nightly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .memory import TradeMemory
from .models import Trade


@dataclass
class Lesson:
    ts: str
    symbol: str
    side: str
    r: float
    regime: str
    volatility: str
    culprit: str          # the worst-edge feature present in the losing trade
    culprit_edge: float
    note: str

    def line(self) -> str:
        return (f"  {self.ts[:16]}  {self.symbol} {self.side:<5} {self.r:+.2f}R  "
                f"[{self.regime}/{self.volatility}]  culprit: {self.culprit} "
                f"({self.culprit_edge:+.2f}R) — {self.note}")


@dataclass
class LossJournal:
    path: Optional[str] = None          # JSONL persistence; None = in-memory only
    lessons: list = field(default_factory=list)

    def __post_init__(self):
        if self.path:
            self._load()

    def record_loss(self, trade: Trade, memory: TradeMemory) -> Optional[Lesson]:
        """Introspect a losing trade and journalize the mistake. No-op on wins."""
        if trade.r_multiple >= 0:
            return None
        feats = getattr(trade, "features", None) or {}
        culprit, edge = memory.worst_feature(trade)
        regime = feats.get("regime", "na")
        vol = feats.get("volatility", "na")
        if culprit.startswith("rv:") or culprit.startswith("regime:") or culprit.startswith("vol:"):
            note = "hostile environment — be pickier here / size down"
        elif culprit.startswith("concept:") or culprit.startswith("cr:"):
            note = "this concept keeps failing in context — demote it"
        elif culprit.startswith("sess:"):
            note = "weak session for this play — prefer killzones"
        else:
            note = "recurring loser — memory will down-weight it"
        lesson = Lesson(
            ts=trade.opened_ts.isoformat() if trade.opened_ts else "",
            symbol=trade.symbol, side=trade.side.value, r=round(trade.r_multiple, 2),
            regime=regime, volatility=vol, culprit=culprit or "n/a",
            culprit_edge=round(edge, 2), note=note)
        self.lessons.append(lesson)
        if self.path:
            self._append(lesson)
        return lesson

    def summary(self, top: int = 5) -> str:
        if not self.lessons:
            return "  Loss journal: clean — no losing trades recorded."
        out = [f"  Loss journal: {len(self.lessons)} lessons (most recent):"]
        for l in self.lessons[-top:]:
            out.append(l.line())
        return "\n".join(out)

    # ---- persistence ----
    def _append(self, lesson: Lesson) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as fh:
            fh.write(json.dumps(lesson.__dict__) + "\n")

    def _load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            if line.strip():
                self.lessons.append(Lesson(**json.loads(line)))
