"""Trade memory — the system remembers past trades and learns from them.

Every closed trade is recorded (optionally persisted to JSONL so it survives across
sessions). For each feature dimension of a trade (instrument, side, session,
confluence bucket, SMC/ICT concept, regime, volatility) we track a sample weight and
total R. The `edge()` of a prospective setup is the sample-shrunk average expectancy of
its matching features — so the brain leans toward the kinds of trades that have actually
worked for YOU, and away from the kinds that haven't. Shrinkage toward neutral means
small samples barely move the needle (no overfitting to a handful of trades).

Markets are non-stationary, so memory is RECENCY-WEIGHTED (EWMA): on each new sample a
bucket's prior weight decays by `recency_decay`, so recent trades dominate and stale
edges fade. This is what lets the brain adapt to the market it's in *now* rather than the
market it saw months ago.
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
    n: float = 0.0                     # EWMA-effective sample weight (not a raw count)
    sum_r: float = 0.0

    @property
    def expectancy(self) -> float:
        return self.sum_r / self.n if self.n else 0.0


@dataclass
class TradeMemory:
    path: Optional[str] = None         # JSONL persistence; None = in-memory only
    shrink_k: float = 8.0              # samples needed before a feature is ~half-trusted
    recency_decay: float = 0.98        # EWMA: prior weight kept per new sample (0.98 ~ 34-trade half-life)
    loss_emphasis: float = 1.5         # losses weigh more — the brain learns from mistakes faster
    buckets: dict = field(default_factory=dict)
    count: int = 0

    def __post_init__(self):
        if self.path:
            self.load()

    # ---- feature extraction ----
    def _features(self, symbol: str, side: Side, ts: datetime, tag: str,
                  feats: dict | None = None) -> list[str]:
        keys = [
            f"sym:{symbol}",
            f"side:{side.value}",
            f"sess:{session_of(ts)}",
            f"conf:{conf_bucket(tag)}",
            f"sym_side:{symbol}:{side.value}",
        ]
        # Concept + context awareness: learn how each SMC/ICT/PB concept performs, how it
        # performs in the current REGIME, and how the broad market CONDITION (regime +
        # volatility) treats us — so the brain knows WHAT works and exactly WHEN.
        if feats:
            regime = feats.get("regime", "na")
            vol = feats.get("volatility", "na")
            keys.append(f"regime:{regime}")
            keys.append(f"vol:{vol}")
            keys.append(f"rv:{regime}:{vol}")          # market-condition bucket
            for c in feats.get("concepts", []):
                keys.append(f"concept:{c}")
                keys.append(f"cr:{c}:{regime}")         # concept-in-regime (context)
        return keys

    def _bump(self, key: str, r: float, weight: float = 1.0) -> None:
        """Fold one trade's R into a bucket as an exponentially-weighted estimate:
        recent trades dominate, stale edges decay toward irrelevance. `weight` lets a
        sample count for more (losses are emphasized so mistakes are absorbed faster)."""
        st = self.buckets.setdefault(key, Stat())
        st.n = st.n * self.recency_decay + weight
        st.sum_r = st.sum_r * self.recency_decay + weight * r

    # ---- learning ----
    def record(self, trade: Trade, persist: bool = True) -> None:
        self.count += 1
        feats = getattr(trade, "features", None)
        w = self.loss_emphasis if trade.r_multiple < 0 else 1.0
        for f in self._features(trade.symbol, trade.side, trade.opened_ts, trade.tag, feats):
            self._bump(f, trade.r_multiple, w)
        if persist and self.path:
            self._append(trade)

    def worst_feature(self, trade: Trade) -> tuple[str, float]:
        """The single matching feature with the worst current expectancy — i.e. the most
        likely CULPRIT behind a loss. Used by the loss journal to name the mistake."""
        feats = getattr(trade, "features", None)
        worst, worst_e = "", 0.0
        for f in self._features(trade.symbol, trade.side, trade.opened_ts, trade.tag, feats):
            st = self.buckets.get(f)
            if st and st.n > 0 and st.expectancy < worst_e:
                worst, worst_e = f, st.expectancy
        return worst, worst_e

    def _shrunk(self, keys: list[str]) -> float:
        vals = []
        for f in keys:
            st = self.buckets.get(f)
            if st and st.n > 0:
                trust = st.n / (st.n + self.shrink_k)     # 0..1, grows with sample weight
                vals.append(st.expectancy * trust)
        return sum(vals) / len(vals) if vals else 0.0

    def edge(self, symbol: str, side: Side, ts: datetime, tag: str,
             feats: dict | None = None) -> float:
        """Sample-shrunk, recency-weighted expectancy (R) across the setup's matching
        features — its SMC/ICT/PB concepts and the current regime/volatility context."""
        return self._shrunk(self._features(symbol, side, ts, tag, feats))

    def condition_edge(self, regime: str, volatility: str = "na") -> float:
        """How the current MARKET CONDITION (regime + volatility) has treated us lately —
        a recency-weighted read used to get pickier when the environment is hostile."""
        return self._shrunk([f"regime:{regime}", f"vol:{volatility}",
                             f"rv:{regime}:{volatility}"])

    # ---- persistence ----
    def _append(self, trade: Trade) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as fh:
            fh.write(json.dumps({
                "symbol": trade.symbol, "side": trade.side.value,
                "opened_ts": trade.opened_ts.isoformat() if trade.opened_ts else None,
                "tag": trade.tag, "r": trade.r_multiple, "pnl": trade.pnl,
                "features": getattr(trade, "features", {}) or {},
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
            r = d.get("r", 0.0)
            w = self.loss_emphasis if r < 0 else 1.0
            # Replay chronologically through the same EWMA fold so reloaded memory keeps
            # its recency profile (later lines in the journal weigh more).
            for f in self._features(d["symbol"], side, ts, d.get("tag", ""), d.get("features")):
                self._bump(f, r, w)

    def summary(self, top: int = 6) -> str:
        rows = sorted(self.buckets.items(), key=lambda kv: kv[1].n, reverse=True)[:top]
        out = [f"  Trade memory: {self.count} trades recorded"]
        for k, st in rows:
            out.append(f"    {k:<22} n={st.n:<4.1f} exp={st.expectancy:+.2f}R")
        return "\n".join(out)
