"""PB Elite session report — morning & afternoon protocol.

Feeds recent bars through the model to produce a truthful, structured read: market
context, HTF bias, SMT instrument pick, key levels (FVGs / order blocks / liquidity /
draw), the best current A+ setup (or stand-aside), risk sizing, and goal progress.

    python -m pb_trader.report --session morning --source synthetic
    python -m pb_trader.report --session afternoon --source databento --symbols ES NQ

NOTE: with --source synthetic this is a DEMO of the format on fake data. For a real,
actionable read, use --source databento (real ES/NQ) — and never trust invented levels.
"""
from __future__ import annotations

import argparse

from . import goals
from .config import settings
from .data import get_source
from .models import Direction, Side
from .risk import position_size, validate_setup
from .strategy.liquidity_draw import classify_liquidity, draw_on_liquidity
from .strategy.pb_model import PBModel
from .strategy.smt import smt_divergence


def _warm(model: PBModel, bars: list) -> None:
    for b in bars:
        model.last_setup = model.on_bar(b)


def build_report(symbols, source_name="synthetic", bars=3000, session="morning",
                 start=None, end=None, timeframe="1m") -> str:
    from .data import GENERATORS
    source = get_source(source_name, bars=bars) if source_name in GENERATORS \
        else get_source(source_name)
    series = {s: source.history(s, start, end, timeframe) for s in symbols}

    models, setups = {}, {}
    for s in symbols:
        m = PBModel(s, settings.confluence_threshold, tp_max_r=settings.tp_max_r)
        last = None
        for b in series[s]:
            r = m.on_bar(b)
            if r is not None:
                last = r
        models[s], setups[s] = m, last

    title = "MORNING" if session == "morning" else "AFTERNOON"
    focus = "NY Open / London continuation" if session == "morning" \
        else "NY PM / afternoon continuation & reversals"
    L = []
    L.append("=" * 64)
    L.append(f"  PB ELITE — {title} REPORT   (focus: {focus})")
    L.append("=" * 64)
    if source_name == "synthetic":
        L.append("  ⚠ DEMO on synthetic data — illustrative format only, not real levels.")
        L.append("")

    # 1. Context + 2. HTF bias per instrument
    L.append("  1) CONTEXT & HTF BIAS")
    for s in symbols:
        m = models[s]
        last = m.bars[-1]
        htf = m.htf_trend.value if m.htf_trend else "unclear"
        htf2 = m.htf2_trend.value if m.htf2_trend else "unclear"
        cond = "; ".join(m.conditions.reasons[:1]) if m.conditions else "n/a"
        L.append(f"     {s}: last {last.close:.2f} | HTF({m.htf_minutes}m) {htf}, "
                 f"({m.htf2_minutes}m) {htf2} | {cond}")

    # 3. SMT instrument selection
    L.append("\n  2) SMT — INSTRUMENT SELECTION")
    if len(symbols) >= 2:
        smt = smt_divergence(series[symbols[0]][-80:], series[symbols[1]][-80:])
        pick = smt.superior or "no divergence — either"
        L.append(f"     {smt.note}  →  favor: {pick}")
    else:
        L.append("     (need ES & NQ for SMT)")

    # 4. Key levels per instrument
    L.append("\n  3) KEY LEVELS (fresh)")
    for s in symbols:
        m = models[s]
        price = m.bars[-1].close
        ifvgs = [f for f in m.fvgs if f.inverted][-3:]
        obs = [o for o in m.blocks if not o.mitigated][-3:]
        lo = m._range_low if m._range_low else price
        hi = m._range_high if m._range_high else price
        rl = classify_liquidity(m.pools, min(lo, hi), max(lo, hi))
        L.append(f"     {s}: dealing range {min(lo,hi):.2f}–{max(lo,hi):.2f}")
        if ifvgs:
            L.append("        iFVGs: " + ", ".join(f"[{f.bottom:.2f},{f.top:.2f}]" for f in ifvgs))
        if obs:
            L.append("        order blocks: " + ", ".join(f"[{o.bottom:.2f},{o.top:.2f}]" for o in obs))
        for d, name in ((Direction.BULL, "upside"), (Direction.BEAR, "downside")):
            dol = draw_on_liquidity(m.pools, price, d)
            if dol:
                L.append(f"        draw {name}: {dol.kind} @ {dol.price:.2f}")

    # 5/6/7. A+ setup, why, risk
    L.append("\n  4) A+ SETUP")
    best_sym = max(setups, key=lambda s: setups[s].confluence if setups[s] else 0)
    setup = setups.get(best_sym)
    if setup is None:
        L.append("     No A+ setup ≥75% right now — STAND ASIDE (process > FOMO).")
    else:
        ok, why = validate_setup(setup, settings.min_rr)
        sized = position_size(setup, settings.account_equity, settings.risk_pct,
                              settings.use_micros)
        L.append(f"     {setup.symbol} {setup.side.value.upper()} @ {setup.entry} "
                 f"| SL {setup.stop} | TP {setup.targets} "
                 f"| {setup.confluence:.0%} conf | R:R {setup.rr():.1f} | {setup.session}")
        L.append(f"     Size: {sized.qty} {sized.symbol} (risk {settings.risk_pct:.0%} "
                 f"= ${sized.risk_dollars:,.0f}){'  ⚠ '+sized.note if sized.note else ''}")
        L.append("     Why:")
        for r in setup.reasons:
            L.append(f"        - {r}")

    # 4b. Scenario map — be PREPARED for multiple paths, trade only the one that confirms
    L.append("\n  5) SCENARIO MAP (primary + alternates — pre-plan each branch)")
    sm = models[best_sym]
    price = sm.bars[-1].close
    scen = sm.project_scenarios()
    if scen:
        L.append(f"     {best_sym} @ {price:.2f} — if/then tree by probability:")
        for s in scen:
            L.append("   " + s.line(price))
    else:
        L.append("     (insufficient history to project scenarios)")

    # 8. What the system has learned (persistent trade memory)
    from .memory import TradeMemory
    mem = TradeMemory(path="journal/memory.jsonl")
    if mem.count:
        L.append("\n  6) WHAT THE SYSTEM HAS LEARNED (from your past trades)")
        for line in mem.summary(top=5).splitlines():
            L.append("   " + line)

    # 8b. Loss journal — mistakes the brain recorded and internalized
    from .lessons import LossJournal
    jrnl = LossJournal(path="journal/lessons.jsonl")
    if jrnl.lessons:
        L.append("\n  6b) LOSS JOURNAL (mistakes learned from)")
        for line in jrnl.summary(top=4).splitlines():
            L.append("   " + line)

    # 9. Goal progress
    L.append("\n  7) GOAL PROGRESS")
    for line in goals.render(settings.account_equity, risk_pct=settings.risk_pct).splitlines():
        L.append("   " + line)

    # Self-audit
    L.append("\n  SELF-AUDIT:")
    if session == "morning":
        L.append("     • Am I trading the condition, or forcing a setup that isn't A+?")
        L.append("     • If I have no verified levels, can I sit in cash without FOMO?")
    else:
        L.append("     • Did I follow the morning plan, or chase? Journal the difference.")
        L.append("     • Is the PM setup fresh, or am I re-entering a dead morning idea?")
    L.append("=" * 64)
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description="PB Elite session report")
    p.add_argument("--session", choices=["morning", "afternoon"], default="morning")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="synthetic",
                   choices=["synthetic", "csv", "databento", "tradovate"])
    p.add_argument("--bars", type=int, default=3000)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--timeframe", default="1m")
    args = p.parse_args()
    print(build_report(args.symbols, args.source, args.bars, args.session,
                       args.start, args.end, args.timeframe))


if __name__ == "__main__":
    main()
