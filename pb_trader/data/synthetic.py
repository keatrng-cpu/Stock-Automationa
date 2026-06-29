"""Deterministic synthetic OHLCV generator so the engine runs with zero accounts.

Produces a plausible intraday random walk with engineered sweeps + displacement so
the PB pipeline has something to find. NOT a market simulator — for plumbing tests only.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from ..models import Bar

_START_PRICE = {"ES": 5500.0, "NQ": 19800.0, "MES": 5500.0, "MNQ": 19800.0}


class SyntheticSource:
    def __init__(self, bars: int = 5000, seed: int = 42, tf_minutes: int = 1):
        self.bars = bars
        self.seed = seed
        self.tf_minutes = tf_minutes

    def _gen(self, symbol: str, n: int) -> list[Bar]:
        rnd = random.Random(self.seed + hash(symbol) % 1000)
        price = _START_PRICE.get(symbol, 5000.0)
        t = datetime(2026, 6, 26, 0, 0)
        vol_unit = price * 0.0004
        out: list[Bar] = []
        trend = 0.0
        for i in range(n):
            # Slowly varying drift + occasional displacement bursts.
            if i % 120 == 0:
                trend = rnd.uniform(-1, 1) * vol_unit * 0.3
            shock = 0.0
            if rnd.random() < 0.03:                # displacement candle
                shock = rnd.choice([-1, 1]) * vol_unit * rnd.uniform(3, 6)
            drift = trend + rnd.gauss(0, vol_unit)
            o = price
            c = price + drift + shock
            wick = abs(rnd.gauss(0, vol_unit)) + abs(shock) * 0.2
            h = max(o, c) + wick * rnd.uniform(0.2, 1.0)
            lo = min(o, c) - wick * rnd.uniform(0.2, 1.0)
            v = abs(rnd.gauss(1000, 300)) + abs(shock) * 50
            out.append(Bar(t, round(o, 2), round(h, 2), round(lo, 2),
                           round(c, 2), round(v, 0), symbol))
            price = c
            t += timedelta(minutes=self.tf_minutes)
        return out

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        return self._gen(symbol, self.bars)

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        # Pre-generate per symbol, then interleave by timestamp to mimic a live feed.
        series = {s: self._gen(s, self.bars) for s in symbols}
        for idx in range(self.bars):
            for s in series:
                yield series[s][idx]
