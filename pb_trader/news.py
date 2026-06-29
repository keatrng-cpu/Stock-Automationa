"""Economic-calendar awareness — the system reacts to news instead of ignoring it.

Pluggable: load events from a JSON file (or wire a real feed later). Each event has an
impact level; the reaction policy is:
  high   -> BLACKOUT  (stand aside around the event)
  medium -> CAUTION   (raise the A+ bar + cut size)
  low    -> CLEAR
No live feed is bundled — populate events.json or call add(); high-impact reactions
keep you out of the chop that prints around FOMC/CPI/NFP.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass
class NewsEvent:
    ts: datetime
    impact: str          # "low" | "medium" | "high"
    name: str


@dataclass
class NewsReaction:
    mode: str            # "blackout" | "caution" | "clear"
    event: Optional[str]
    threshold_add: float
    size_mult: float


class EconomicCalendar:
    def __init__(self, events: Optional[list[NewsEvent]] = None,
                 high_pad_min: int = 5, med_pad_min: int = 2):
        self.events = events or []
        self.high_pad = timedelta(minutes=high_pad_min)
        self.med_pad = timedelta(minutes=med_pad_min)

    @classmethod
    def from_json(cls, path: str, **kw) -> "EconomicCalendar":
        p = Path(path)
        if not p.exists():
            return cls([], **kw)
        raw = json.loads(p.read_text())
        events = [NewsEvent(datetime.fromisoformat(e["ts"]),
                            e.get("impact", "medium"), e.get("name", "event"))
                  for e in raw]
        return cls(events, **kw)

    def add(self, ts: datetime, impact: str, name: str) -> None:
        self.events.append(NewsEvent(ts, impact, name))

    def impact_at(self, ts: datetime) -> Optional[NewsEvent]:
        """Highest-impact event whose window contains `ts`."""
        hit: Optional[NewsEvent] = None
        for e in self.events:
            pad = self.high_pad if e.impact == "high" else self.med_pad
            if e.ts - pad <= ts <= e.ts + pad:
                if hit is None or IMPACT_RANK[e.impact] > IMPACT_RANK[hit.impact]:
                    hit = e
        return hit

    def reaction(self, ts: datetime) -> NewsReaction:
        e = self.impact_at(ts)
        if e is None:
            return NewsReaction("clear", None, 0.0, 1.0)
        if e.impact == "high":
            return NewsReaction("blackout", e.name, 1.0, 0.0)   # stand aside
        if e.impact == "medium":
            return NewsReaction("caution", e.name, 0.05, 0.5)   # tighter + smaller
        return NewsReaction("clear", e.name, 0.0, 1.0)
