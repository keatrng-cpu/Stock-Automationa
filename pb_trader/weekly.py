"""Week-by-week ledger — watch the brain evolve in small increments.

Runs one continuous backtest (so structure/memory/adaptation carry forward) but reports
a snapshot at the end of every week: equity, trades that week, and the brain's adaptive
state (size multiplier, raised bar, streak, drawdown). At the end it prints what the
brain has learned per concept. This is the "small week-by-week increments" view.

    python -m pb_trader.weekly --weeks 12 --source neutral
    python -m pb_trader.weekly --weeks 8 --source synthetic --timeframe 5m
"""
from __future__ import annotations

import argparse

from .backtest import load_series, run_backtest
from .brain import TradingBrain
from .config import settings
from .memory import TradeMemory
from .timeframes import parse_tf


def week_bars(timeframe: str) -> int:
    """Bars in one (continuous) week at the given base timeframe."""
    return max(1, (7 * 24 * 3600) // parse_tf(timeframe))


def run(symbols, weeks=12, source="neutral", timeframe="1m") -> None:
    wb = week_bars(timeframe)
    total = wb * weeks
    brain = TradingBrain(base_threshold=settings.confluence_threshold,
                         memory=TradeMemory(shrink_k=8.0))
    series = load_series(symbols, source, total, timeframe=timeframe)
    n = min(len(v) for v in series.values())
    weeks = n // wb
    r = run_backtest(symbols, source, total, timeframe=timeframe, verbose=False,
                     series=series, brain=brain, checkpoint_bars=wb)

    print("\n" + "=" * 74)
    print(f"  WEEK-BY-WEEK LEDGER  '{source}' {timeframe}  ${settings.account_equity:,.0f} start, "
          f"{weeks} weeks")
    print("=" * 74)
    print(f"  {'Wk':>3} {'Equity':>11} {'Δ$ wk':>9} {'trades':>7} {'risk×':>6} "
          f"{'+bar':>5} {'streak':>7} {'dd':>5}")
    prev_eq = settings.account_equity
    prev_tr = 0
    for c in r.checkpoints:
        d_eq = c["equity"] - prev_eq
        d_tr = c["trades"] - prev_tr
        streak = (f"W{c['win_streak']}" if c["win_streak"] else f"L{c['loss_streak']}")
        print(f"  {c['period']:>3} {c['equity']:>11,.0f} {d_eq:>+9,.0f} {d_tr:>7} "
              f"{c['risk_mult']:>6.2f} {c['thr_bump']:>5.2f} {streak:>7} {c['drawdown']:>4.0%}")
        prev_eq, prev_tr = c["equity"], c["trades"]
    # Final week (tail after the last checkpoint).
    m = r.metrics
    print("  " + "-" * 70)
    print(f"  END {r.end_equity:>11,.0f} {r.end_equity-settings.account_equity:>+9,.0f} "
          f"{m.round_trips:>7} round-trips total | RT win {m.rt_win_rate:.0%}  exp {m.rt_expectancy_r:+.2f}R")

    rows = [(k, v) for k, v in brain.memory.buckets.items()
            if k.startswith("concept:") and v.n >= 4]
    rows.sort(key=lambda kv: kv[1].expectancy, reverse=True)
    if rows:
        print("\n  What the brain learned (concept edges, n>=4):")
        for k, v in rows[:4] + rows[-4:]:
            print(f"     {k:<20} n={v.n:<4} exp={v.expectancy:+.2f}R")
    print(f"  Final adaptive state: {brain.adaptive.state()}\n")


def main() -> None:
    from .timeframes import LADDER
    p = argparse.ArgumentParser(description="Week-by-week brain ledger")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="neutral",
                   choices=["synthetic", "neutral", "adversarial", "csv", "databento"])
    p.add_argument("--weeks", type=int, default=12)
    p.add_argument("--timeframe", default="1m", choices=LADDER)
    args = p.parse_args()
    run(args.symbols, args.weeks, args.source, args.timeframe)


if __name__ == "__main__":
    main()
