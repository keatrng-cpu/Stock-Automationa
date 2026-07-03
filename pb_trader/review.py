"""Learning self-audit — review what the brain learned and find the WEAK SPOTS.

A great trader reviews the journal and asks hard questions: what do I actually know vs.
what am I fooling myself about? This module runs the engine, then audits its own learning:

  1. **Collinearity** — SMC/ICT concepts that always fire together carry identical stats, so
     the brain CANNOT tell them apart. It reports these clusters (an honesty check: "you
     didn't learn 8 concepts, you learned 1 blob").
  2. **Sample health** — how many learned buckets are actually TRUSTED (enough weight) vs
     undersampled noise the brain shouldn't lean on yet.
  3. **Blind spots** — regimes / volatility / sessions / timeframes with zero experience.
  4. **Trusted edges** — the best/worst edges the brain can actually stand behind.
  5. **Veto calibration** — the deepest check: of the setups the brain SKIPPED, how many
     would have won? If it vetoes winners it's over-filtering; if the ones it took lose while
     the ones it skipped win, the learning is inverted. (Counterfactual, no look-ahead.)

    python -m pb_trader.review --source neutral --weeks 4 --timeframe 1m

Honest by construction: it names what the system does NOT know, not just what it does.
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from .backtest import run_backtest
from .brain import TradingBrain
from .config import settings
from .memory import TradeMemory


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def audit(brain: TradingBrain, skips: list, top: int = 6) -> str:
    mem = brain.memory
    k = mem.shrink_k
    L = ["=" * 74, "  LEARNING SELF-AUDIT — what the brain knows, and where it's weak", "=" * 74]
    L.append(f"  trades learned: {mem.count}   buckets: {len(mem.buckets)}   "
             f"trust threshold: n≥{k:.0f}")

    # 1) Collinearity — concepts with identical stats can't be separated.
    groups = defaultdict(list)
    for key, st in mem.buckets.items():
        if key.startswith(("concept:", "cr:", "tf:")):
            groups[(round(st.n, 4), round(st.sum_r, 4))].append(key)
    collinear = {sig: ks for sig, ks in groups.items() if len(ks) > 1}
    L.append("\n  1) COLLINEARITY (concepts that always co-fire — NOT separable):")
    if collinear:
        for sig, ks in sorted(collinear.items(), key=lambda kv: -len(kv[1]))[:5]:
            names = ", ".join(sorted(kc.split(":", 1)[-1] for kc in ks)[:6])
            L.append(f"     n={sig[0]:<6} {len(ks):>2} concepts share one signal → {names}…")
        L.append("     ⚠ weak spot: per-concept edges inside a cluster are illusory. The brain "
                 "now\n       collapses these to one vote (no N× double-count), but it still "
                 "can't say\n       WHICH concept earned the edge until they're seen apart "
                 "(needs varied data).")
    else:
        L.append("     none — concepts vary independently (good).")

    # 2) Sample health.
    trusted = [(kk, st) for kk, st in mem.buckets.items() if st.n >= k]
    thin = [kk for kk, st in mem.buckets.items() if 0 < st.n < k]
    L.append(f"\n  2) SAMPLE HEALTH: {len(trusted)} trusted buckets (n≥{k:.0f}), "
             f"{len(thin)} undersampled.")
    if len(trusted) < 3:
        L.append("     ⚠ weak spot: almost nothing is trusted yet — the brain is running on "
                 "noise.\n       It needs far more closed trades (real data) before its edges "
                 "mean anything.")

    # 3) Blind spots — dimensions with no experience.
    def seen(prefix, values):
        return [v for v in values if any(kk == f"{prefix}{v}" for kk in mem.buckets)]
    regimes = seen("regime:", ["trending", "ranging", "dead"])
    vols = seen("vol:", ["high", "normal", "low"])
    L.append("\n  3) BLIND SPOTS (no experience in):")
    miss = []
    for name, allv, got in (("regime", ["trending", "ranging", "dead"], regimes),
                            ("volatility", ["high", "normal", "low"], vols)):
        gap = [v for v in allv if v not in got]
        if gap:
            miss.append(f"{name}={'/'.join(gap)}")
    L.append("     " + ("; ".join(miss) if miss else "none — has traded every regime & vol state."))

    # 4) Trusted edges — what it can actually stand behind.
    concept_edges = [(kk.split(":", 1)[1], st.expectancy, st.n)
                     for kk, st in trusted if kk.startswith("concept:")]
    concept_edges.sort(key=lambda x: x[1], reverse=True)
    L.append("\n  4) TRUSTED EDGES (n≥threshold):")
    if concept_edges:
        for name, e, n in concept_edges[:top]:
            L.append(f"     {name:<22} exp={e:+.2f}R  (n={n:.1f})")
    else:
        L.append("     (none trusted yet)")

    # 5) Veto calibration — were the skips right? (counterfactual, no look-ahead)
    L.append("\n  5) VETO CALIBRATION (of setups the brain SKIPPED, how many would have won?):")
    by_reason = defaultdict(list)
    for sk in skips:
        if sk.get("hypo_r") is not None:
            by_reason[sk["reason"]].append(sk["hypo_r"])
    if not by_reason:
        L.append("     no resolvable skipped setups to grade (either none skipped, or none "
                 "would have filled).")
    else:
        for reason, rs in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            wins = sum(1 for r in rs if r > 0)
            wr = wins / len(rs)
            avg = _mean(rs)
            verdict = "GOOD veto (skipped losers)" if avg < 0 else \
                      "⚠ COSTLY veto (skipped net winners — over-filtering)"
            L.append(f"     {reason:<12} skipped {len(rs):>3} | would-be win {wr:>4.0%} "
                     f"avg {avg:+.2f}R → {verdict}")
    L.append("=" * 74)
    return "\n".join(L)


def run(symbols, weeks=4, source="neutral", timeframe="1m", equity=None,
        start=None, end=None) -> None:
    from .timeframes import parse_tf
    equity = equity or settings.account_equity
    bars = max(1, (7 * 24 * 3600) // parse_tf(timeframe)) * weeks
    brain = TradingBrain(base_threshold=settings.confluence_threshold,
                         memory=TradeMemory(shrink_k=8.0))
    r = run_backtest(symbols, source, bars, start=start, end=end, timeframe=timeframe,
                     verbose=False, start_equity=equity, brain=brain, track_skips=True)
    print(f"\n(context: {r.metrics.round_trips} trades taken, {len(r.skips)} setups skipped, "
          f"end ${r.end_equity:,.0f} on '{source}' {timeframe} {weeks}wk)")
    print(audit(brain, r.skips))
    if brain.journal.lessons:
        print("\n  Recent loss lessons:")
        for line in brain.journal.summary(top=4).splitlines()[1:]:
            print("  " + line)


def main() -> None:
    from .timeframes import LADDER
    p = argparse.ArgumentParser(description="Audit the brain's learning for weak spots")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="neutral",
                   choices=["synthetic", "neutral", "adversarial", "csv", "databento"])
    p.add_argument("--start", default=None, help="ISO date (real-data sources)")
    p.add_argument("--end", default=None, help="ISO date (real-data sources)")
    p.add_argument("--weeks", type=int, default=4)
    p.add_argument("--timeframe", default="1m", choices=LADDER)
    p.add_argument("--equity", type=float, default=None)
    args = p.parse_args()
    run(args.symbols, args.weeks, args.source, args.timeframe, args.equity,
        start=args.start, end=args.end)


if __name__ == "__main__":
    main()
