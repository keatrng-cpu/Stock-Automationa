"""Adversarial market data — actively HOSTILE to the model (the stress test).

Starts from the neutral random walk, then injects the things that hurt SMC traders:
  - Fakeout sweeps: price pokes a recent high/low (looks like a setup trigger) then
    reverses AGAINST the expected direction — the classic trap.
  - Failed displacement: a strong move that immediately mean-reverts.
  - Chop bursts: tight, directionless ranges that grind out stops.

If the model/brain still survives here, the adaptive + memory layers are doing real
work. This is the opposite of the friendly synthetic generator.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from ..models import Bar
from .neutral import NeutralSource


class AdversarialSource:
    def __init__(self, bars: int = 5000, seed: int = 13, tf_minutes: int = 1,
                 tf_seconds: int | None = None):
        self.bars = bars
        self.seed = seed
        self._neutral = NeutralSource(bars=bars, seed=seed, tf_minutes=tf_minutes,
                                      tf_seconds=tf_seconds)

    def _gen(self, symbol: str, n: int) -> list[Bar]:
        base = self._neutral._gen(symbol, n)
        rnd = random.Random(self.seed * 31 + sum(ord(c) for c in symbol))
        out: list[Bar] = list(base)
        i = 25
        while i < n - 3:
            roll = rnd.random()
            recent = out[i - 20:i]
            hh = max(b.high for b in recent)
            ll = min(b.low for b in recent)
            atr = sum(b.high - b.low for b in recent) / len(recent)
            if roll < 0.04:
                # Fakeout: spike beyond a recent extreme, then snap back through it.
                up = rnd.random() < 0.5
                spike = (hh + atr) if up else (ll - atr)
                o = out[i].open
                close = o - atr if up else o + atr     # closes AGAINST the breakout
                hi = max(o, close, spike)              # enclose all points (valid OHLC)
                lo = min(o, close, spike)
                trap = Bar(out[i].ts, o, hi, lo, close, out[i].volume * 2, symbol)
                out[i] = trap
                # follow-through against the trapped breakout
                base_p = trap.close
                for j in range(1, 3):
                    if i + j < n:
                        step = (-atr if up else atr) * rnd.uniform(0.5, 1.2)
                        np = base_p + step
                        out[i + j] = Bar(out[i + j].ts, base_p, max(base_p, np) + 0.1,
                                         min(base_p, np) - 0.1, np, out[i + j].volume, symbol)
                        base_p = np
                i += 4
            elif roll < 0.07:
                # Chop burst: several tight directionless bars that grind stops.
                mid = out[i].close
                for j in range(6):
                    if i + j >= n:
                        break
                    c = mid + rnd.uniform(-0.4, 0.4) * atr
                    o = out[i + j].open
                    out[i + j] = Bar(out[i + j].ts, o, max(o, c) + 0.15 * atr,
                                     min(o, c) - 0.15 * atr, c, out[i + j].volume, symbol)
                i += 6
            else:
                i += 1
        return out

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        return self._gen(symbol, self.bars)

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        series = {s: self._gen(s, self.bars) for s in symbols}
        for idx in range(self.bars):
            for s in series:
                yield series[s][idx]
