"""Market conditions / context gate — "read the condition before the setup" (PB).

A pattern is necessary but not sufficient. PB filters by *environment*:
  - Regime: is price trending (clean displacement) or chopping (mean-reverting)?
  - Volatility: is range alive, or dead/illiquid where stops get chewed?
  - News: are we inside a high-impact event blackout?
This module produces a verdict the model uses as a hard gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..models import Bar


def atr(bars: list[Bar], n: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    window = trs[-n:]
    return sum(window) / len(window) if window else 0.0


def efficiency_ratio(bars: list[Bar], n: int = 20) -> float:
    """Kaufman efficiency ratio in [0,1]: net move / path length.

    ~1.0 = clean trend (PB/TJR want this for displacement); ~0 = chop.
    """
    if len(bars) <= n:
        return 0.0
    window = bars[-(n + 1):]
    net = abs(window[-1].close - window[0].close)
    path = sum(abs(window[i].close - window[i - 1].close) for i in range(1, len(window)))
    return net / path if path else 0.0


@dataclass
class MarketConditions:
    regime: str                # "trending" | "ranging" | "dead"
    volatility: str            # "high" | "normal" | "low"
    tradeable: bool
    er: float
    atr_ratio: float
    reasons: list[str] = field(default_factory=list)


def assess_conditions(bars: list[Bar], er_n: int = 20, atr_n: int = 14,
                      er_trend: float = 0.30, min_atr_ratio: float = 0.4,
                      max_atr_ratio: float = 3.0) -> MarketConditions:
    """Classify the current environment and decide if it's tradeable."""
    if len(bars) < max(er_n, atr_n) + 5:
        return MarketConditions("dead", "low", False, 0.0, 0.0, ["insufficient history"])

    er = efficiency_ratio(bars, er_n)
    cur_atr = atr(bars[-atr_n - 1:], atr_n)
    base_atr = atr(bars, min(len(bars) - 1, 200))
    atr_ratio = (cur_atr / base_atr) if base_atr else 0.0

    reasons: list[str] = []
    regime = "trending" if er >= er_trend else ("ranging" if er >= er_trend / 2 else "dead")
    if atr_ratio >= 1.5:
        volatility = "high"
    elif atr_ratio <= 0.6:
        volatility = "low"
    else:
        volatility = "normal"

    tradeable = True
    if regime == "dead":
        tradeable = False
        reasons.append(f"dead regime (efficiency {er:.2f}) — chop, stand aside")
    if atr_ratio < min_atr_ratio:
        tradeable = False
        reasons.append(f"volatility too low (ATR ratio {atr_ratio:.2f}) — illiquid")
    if atr_ratio > max_atr_ratio:
        tradeable = False
        reasons.append(f"volatility too high (ATR ratio {atr_ratio:.2f}) — erratic/news")
    if tradeable:
        reasons.append(f"{regime} regime, {volatility} volatility — environment OK")

    return MarketConditions(regime, volatility, tradeable, round(er, 3),
                            round(atr_ratio, 3), reasons)


class NewsCalendar:
    """High-impact news blackout windows. Pluggable — no feed required to function.

    Add (start, end) datetime windows (e.g. FOMC, CPI, NFP) and the model will refuse
    to trade inside them. Wire a real feed (e.g. ForexFactory / econ API) later.
    """

    def __init__(self, windows: Optional[list[tuple[datetime, datetime]]] = None,
                 pad_minutes: int = 2):
        self.windows = windows or []
        self.pad_minutes = pad_minutes

    def in_blackout(self, ts: datetime) -> bool:
        from datetime import timedelta
        pad = timedelta(minutes=self.pad_minutes)
        return any(s - pad <= ts <= e + pad for s, e in self.windows)
