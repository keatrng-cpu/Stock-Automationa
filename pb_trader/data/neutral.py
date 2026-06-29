"""Neutral market data — a FAIR test generator (no SMC patterns injected).

Unlike `synthetic.py` (which deliberately injects trends, displacement candles and
sweeps that the model is designed to detect), this produces a pure driftless random
walk with two *incidental*, realistic features that are NOT aligned to any setup:
  - volatility clustering (calm and wild periods), and
  - occasional symmetric jumps ("news").

There is no predictable structure here. A strategy with no genuine edge should come out
roughly breakeven-minus-costs on this data; if it prints large gains, that points to a
look-ahead/fill bug, not skill. This is the honest null hypothesis.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from ..models import Bar

_START_PRICE = {"ES": 5500.0, "NQ": 19800.0, "MES": 5500.0, "MNQ": 19800.0}


class NeutralSource:
    def __init__(self, bars: int = 5000, seed: int = 7, tf_minutes: int = 1,
                 substeps: int = 12, tf_seconds: int | None = None):
        self.bars = bars
        self.seed = seed
        self.tf_seconds = tf_seconds if tf_seconds is not None else tf_minutes * 60
        self.substeps = substeps

    def _gen(self, symbol: str, n: int) -> list[Bar]:
        rnd = random.Random(self.seed + sum(ord(c) for c in symbol))
        price = _START_PRICE.get(symbol, 5000.0)
        t = datetime(2026, 6, 26, 0, 0)
        # Per-minute baseline vol (~ typical ES 1-min range), as a fraction of price.
        base_sigma = price * 0.0006
        log_sig = math.log(base_sigma)
        out: list[Bar] = []
        for _ in range(n):
            # Volatility clustering: mean-reverting log-vol, NO directional drift.
            log_sig = 0.985 * log_sig + 0.015 * math.log(base_sigma) + rnd.gauss(0, 0.05)
            sigma = math.exp(log_sig)
            step = sigma / math.sqrt(self.substeps)
            o = price
            p = price
            hi = lo = price
            for _s in range(self.substeps):
                p += rnd.gauss(0.0, step)                 # driftless increment
                if rnd.random() < 0.002:                  # rare symmetric jump (news)
                    p += rnd.choice([-1, 1]) * sigma * rnd.uniform(3, 7)
                hi = max(hi, p)
                lo = min(lo, p)
            c = p
            v = abs(rnd.gauss(1000, 350)) + 1
            out.append(Bar(t, round(o, 2), round(hi, 2), round(lo, 2),
                           round(c, 2), round(v, 0), symbol))
            price = c
            t += timedelta(seconds=self.tf_seconds)
        return out

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        return self._gen(symbol, self.bars)

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        series = {s: self._gen(s, self.bars) for s in symbols}
        for idx in range(self.bars):
            for s in series:
                yield series[s][idx]
