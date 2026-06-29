"""Trade memory — the system remembers past trades and learns from them.

Every closed trade is recorded (optionally persisted to JSONL so it survives across
sessions). For each feature dimension of a trade (instrument, side, session,
confluence bucket) we track sample count and total R. The `edge()` of a prospective
setup is the sample-shrunk average expectancy of its matching features — so the brain
leans toward the kinds of trades that have actually worked for YOU, and away from the
kinds that haven't. Shrinkage toward neutral means small samples barely move the needle
(no overfitting to a handful of trades).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Side, Trade


def session_of(ts: datetime) -> str:
    h = ts.hour
    if 9 <= h < 11:
        return "NY_Open"
    if 11 <= h < 13:
        return "NY_Lunch"
    if 13 <= h < 16:
        return "NY_PM"
    if 3 <= h < 9:
        return "London"
    return "Asia"


def conf_bucket(tag: str) -> str:
    try:
        pct = int(str(tag).rstrip("%"))
    except (ValueError, AttributeError):
        return "na"
    if pct >= 90:
        return "90+"
    if pct >= 85:
        return "85-89"
    if pct >= 80:
        return "80-84"
    return "75-79"


@dataclass
class Stat:
    n: int = 0
    sum_r: float = 0.0

    @property
    def expectancy(self) -> float:
        return self.sum_r / self.n if self.n else 0.0


@dataclass
class TradeMemory:
    path: Optional[str] = None         # JSONL persistence; None = in-memory only
    shrink_k: float = 8.0              # samples needed before a feature is ~half-trusted
    buckets: dict = field(default_factory=dict)
    count: int = 0

    def __post_init__(self):
        if self.path:
            self.load()

    # ---- feature extraction ----
    def _features(self, symbol: str, side: Side, ts: datetime, tag: str) -> list[str]:
        return [
            f"sym:{symbol}",
            f"side:{side.value}",
            f"sess:{session_of(ts)}",
            f"conf:{conf_bucket(tag)}",
            f"sym_side:{symbol}:{side.value}",
        ]

    # ---- learning ----
    def record(self, trade: Trade, persist: bool = True) -> None:
        self.count += 1
        for f in self._features(trade.symbol, trade.side, trade.opened_ts, trade.tag):
            st = self.buckets.setdefault(f, Stat())
            st.n += 1
            st.sum_r += trade.r_multiple
        if persist and self.path:
            self._append(trade)

    def edge(self, symbol: str, side: Side, ts: datetime, tag: str) -> float:
        """Sample-shrunk average expectancy (R) across the setup's matching features."""
        vals = []
        for f in self._features(symbol, side, ts, tag):
            st = self.buckets.get(f)
            if st and st.n > 0:
                trust = st.n / (st.n + self.shrink_k)     # 0..1, grows with sample size
                vals.append(st.expectancy * trust)
        return sum(vals) / len(vals) if vals else 0.0

    # ---- persistence ----
    def _append(self, trade: Trade) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as fh:
            fh.write(json.dumps({
                "symbol": trade.symbol, "side": trade.side.value,
                "opened_ts": trade.opened_ts.isoformat() if trade.opened_ts else None,
                "tag": trade.tag, "r": trade.r_multiple, "pnl": trade.pnl,
            }) + "\n")

    def load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            ts = datetime.fromisoformat(d["opened_ts"]) if d.get("opened_ts") else datetime.utcnow()
            side = Side(d["side"])
            self.count += 1
            for f in self._features(d["symbol"], side, ts, d.get("tag", "")):
                st = self.buckets.setdefault(f, Stat())
                st.n += 1
                st.sum_r += d.get("r", 0.0)

    def summary(self, top: int = 6) -> str:
        rows = sorted(self.buckets.items(), key=lambda kv: kv[1].n, reverse=True)[:top]
        out = [f"  Trade memory: {self.count} trades recorded"]
        for k, st in rows:
            out.append(f"    {k:<22} n={st.n:<4} exp={st.expectancy:+.2f}R")
        return "\n".join(out)
