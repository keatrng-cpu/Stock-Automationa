"""Monte-Carlo robustness — test across MANY randomized markets, not one lucky seed.

A strategy that prints money on one synthetic market may be curve-fit to that market's
quirks. The honest question is the *distribution* of outcomes across many independent
randomized markets: what's the median result, how often is it profitable, how bad is the
worst drawdown? This harness runs the backtest over a range of seeds and reports that
distribution.

    python -m pb_trader.montecarlo --seeds 30 --source neutral --weeks 4 --equity 20000
    python -m pb_trader.montecarlo --seeds 30 --source neutral --weeks 4 --mtf --carry

⚠️ HONESTY: searching seeds until one is profitable is overfitting, not edge. Read the
MEDIAN and the % profitable across ALL seeds — a real edge shows up as a distribution
centered above breakeven, not as one cherry-picked winner. On driftless/fair random data
the honest expectation is a distribution centered near zero.
"""
from __future__ import annotations

import argparse

from .backtest import run_backtest
from .brain import TradingBrain
from .config import settings
from .memory import TradeMemory


def _pct(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    i = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
    return s[i]


def run(symbols, seeds=30, source="neutral", weeks=4, timeframe="1m", profile=None,
        equity=None, mtf=False, carry=False) -> None:
    from .timeframes import parse_tf
    equity = equity or settings.account_equity
    bars = max(1, (7 * 24 * 3600) // parse_tf(timeframe)) * weeks
    base_thr = settings.confluence_threshold
    if profile:
        from .profiles import get_profile
        base_thr = get_profile(profile).threshold

    # One brain carried across all markets (continual learning) or a fresh brain per market.
    shared = TradingBrain(base_threshold=base_thr, memory=TradeMemory(shrink_k=8.0)) if carry else None

    rows = []
    print("=" * 78)
    print(f"  MONTE-CARLO  {seeds} markets × {weeks}wk  '{source}' {timeframe}  "
          f"${equity:,.0f}  {'+MTF ' if mtf else ''}{'+carry-brain' if carry else ''}")
    print("=" * 78)
    print(f"  {'seed':>4} {'end$':>10} {'Δ%':>7} {'RTs':>4} {'win':>5} {'exp R':>6} {'maxDD':>7}")
    for sd in range(seeds):
        brain = shared or TradingBrain(base_threshold=base_thr, memory=TradeMemory(shrink_k=8.0))
        r = run_backtest(symbols, source, bars, timeframe=timeframe, verbose=False,
                         start_equity=equity, brain=brain, profile=profile,
                         seed=sd, mtf=mtf)
        m = r.metrics
        d_pct = (r.end_equity - equity) / equity * 100.0
        dd_pct = m.max_drawdown / equity if equity else 0.0
        rows.append((sd, r.end_equity, d_pct, m.round_trips, m.rt_win_rate,
                     m.rt_expectancy_r, dd_pct))
        print(f"  {sd:>4} {r.end_equity:>10,.0f} {d_pct:>+6.1f}% {m.round_trips:>4} "
              f"{m.rt_win_rate:>4.0%} {m.rt_expectancy_r:>+5.2f} {dd_pct:>6.1%}")

    ends = [x[1] for x in rows]
    deltas = [x[2] for x in rows]
    exps = [x[5] for x in rows]
    rts = sum(x[3] for x in rows)
    profitable = sum(1 for d in deltas if d > 0)
    print("  " + "-" * 74)
    print(f"  AGGREGATE over {seeds} markets ({rts} round-trips total):")
    print(f"    end equity   median ${_pct(ends,0.5):,.0f}   mean ${sum(ends)/len(ends):,.0f}")
    print(f"    return %     median {_pct(deltas,0.5):+.1f}%   worst {min(deltas):+.1f}%   best {max(deltas):+.1f}%")
    print(f"    expectancy   median {_pct(exps,0.5):+.2f}R   mean {sum(exps)/len(exps):+.2f}R")
    print(f"    profitable   {profitable}/{seeds} markets ({profitable/seeds:.0%})")
    print(f"    worst drawdown across all markets: {max(x[6] for x in rows):.0%}")
    verdict = ("EDGE-POSITIVE distribution" if _pct(deltas, 0.5) > 0 and profitable / seeds >= 0.55
               else "NO demonstrated edge — distribution ~breakeven/negative (expected on fair random data)")
    print(f"    VERDICT: {verdict}")
    print("=" * 78)


def main() -> None:
    from .timeframes import LADDER
    p = argparse.ArgumentParser(description="Monte-Carlo robustness across randomized markets")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--seeds", type=int, default=30)
    p.add_argument("--source", default="neutral", choices=["synthetic", "neutral", "adversarial"])
    p.add_argument("--weeks", type=int, default=4)
    p.add_argument("--timeframe", default="1m", choices=LADDER)
    p.add_argument("--profile", default=None,
                   choices=["blake", "ronan", "patty", "patty_scalp", "default"])
    p.add_argument("--equity", type=float, default=None)
    p.add_argument("--mtf", action="store_true", help="multi-timeframe conjunction gating")
    p.add_argument("--carry", action="store_true", help="carry one brain across all markets")
    args = p.parse_args()
    run(args.symbols, args.seeds, args.source, args.weeks, args.timeframe,
        args.profile, args.equity, args.mtf, args.carry)


if __name__ == "__main__":
    main()
