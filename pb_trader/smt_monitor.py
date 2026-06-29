"""SMT monitor — automatically compare ES vs NQ for Smart-Money-Technique divergences.

ES and NQ are correlated: they should make matching higher-highs and lower-lows. When one
makes a new extreme and the other FAILS to confirm, that divergence (SMT) exposes the
weaker instrument — institutional footprints. This monitor scans the two streams bar-by-bar
and emits a timeline of confirmed divergence events, each with the instrument to favor and
the directional read, so the engine (and you) always know which index is leading.

    python -m pb_trader.smt_monitor --source neutral --bars 3000 --timeframe 1m

It reuses `strategy.smt.smt_divergence` (the same logic the backtester uses for instrument
selection) but runs it as a continuous, deduplicated event stream rather than a one-shot.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from .models import Bar
from .strategy.smt import SMTSignal, smt_divergence


@dataclass
class SMTEvent:
    ts: object               # bar timestamp at detection
    direction: str           # "bullish" | "bearish"
    favor: str               # instrument to trade (strong for longs / weak for shorts)
    note: str

    def line(self) -> str:
        bias = "LONG" if self.direction == "bullish" else "SHORT"
        return f"  {str(self.ts)[:16]}  {self.direction:<8} → favor {bias} {self.favor:<3} | {self.note}"


def scan(es: list[Bar], nq: list[Bar], lookback: int = 20,
         warmup: int = 40, step: int = 1) -> list[SMTEvent]:
    """Walk the two aligned series and collect deduplicated SMT divergence events.

    A new event is emitted only when the (direction, favored instrument) pair CHANGES, so a
    persistent divergence isn't double-counted every bar."""
    events: list[SMTEvent] = []
    n = min(len(es), len(nq))
    last_key = None
    for i in range(warmup, n, step):
        sig: SMTSignal = smt_divergence(es[:i + 1], nq[:i + 1], lookback)
        if not sig.diverging:
            last_key = None
            continue
        key = (sig.direction, sig.superior)
        if key != last_key:
            events.append(SMTEvent(es[i].ts, sig.direction, sig.superior or "?", sig.note))
            last_key = key
    return events


def current(es: list[Bar], nq: list[Bar], lookback: int = 20) -> SMTSignal:
    """The live SMT read right now — what the engine should respect this instant."""
    return smt_divergence(es, nq, lookback)


def render(es: list[Bar], nq: list[Bar], lookback: int = 20, top: int = 12) -> str:
    events = scan(es, nq, lookback)
    cur = current(es, nq, lookback)
    L = ["=" * 66, "  ES ⇄ NQ  SMT DIVERGENCE MONITOR", "=" * 66]
    L.append(f"  LIVE: {cur.note}" + (f"  → favor {cur.superior}" if cur.superior else ""))
    L.append(f"  {len(events)} divergence events detected (most recent {min(top,len(events))}):")
    if events:
        for e in events[-top:]:
            L.append(e.line())
    else:
        L.append("  (indices in agreement throughout — no SMT edge)")
    L.append("=" * 66)
    return "\n".join(L)


def main() -> None:
    from .data import GENERATORS, get_source
    from .timeframes import LADDER, parse_tf
    p = argparse.ArgumentParser(description="Automatic ES/NQ SMT divergence monitor")
    p.add_argument("--symbols", nargs=2, default=["ES", "NQ"])
    p.add_argument("--source", default="neutral",
                   choices=["synthetic", "neutral", "adversarial", "csv", "databento"])
    p.add_argument("--bars", type=int, default=3000)
    p.add_argument("--timeframe", default="1m", choices=LADDER)
    p.add_argument("--lookback", type=int, default=20)
    args = p.parse_args()
    src = get_source(args.source, bars=args.bars, tf_seconds=parse_tf(args.timeframe)) \
        if args.source in GENERATORS else get_source(args.source)
    es = src.history(args.symbols[0], None, None, args.timeframe)
    nq = src.history(args.symbols[1], None, None, args.timeframe)
    print(render(es, nq, args.lookback))


if __name__ == "__main__":
    main()
