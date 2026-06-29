"""One-command validation suite: backtest → optimizer → walk-forward → verdict.

Runs the whole "is this edge real?" pipeline and prints a single GO / NO-GO read,
so you never have to remember the individual commands.

    python -m pb_trader.validate --bars 16000
    python -m pb_trader.validate --source databento --start 2026-01-01 --end 2026-06-26

The verdict is driven by the WALK-FORWARD (out-of-sample) result — the only number
that isn't curve-fit. On synthetic data it's a plumbing demo; on real data it's a
genuine go/no-go.
"""
from __future__ import annotations

import argparse

from . import goals
from .backtest import run_backtest
from .config import settings
from .optimize import optimize
from .walkforward import walk_forward


def run(symbols, source="synthetic", bars=16000, start=None, end=None,
        timeframe="1m") -> dict:
    print("\n" + "#" * 64)
    print("  PB TRADER — FULL VALIDATION SUITE")
    print("#" * 64)
    real = source != "synthetic"
    if not real:
        print("  (synthetic data — this is a plumbing demo, not an edge verdict)")

    # 1) Baseline backtest with default params.
    print("\n[1/3] Baseline backtest (default params)...")
    bt = run_backtest(symbols, source, bars, start, end, timeframe, verbose=False)
    m = bt.metrics
    print(f"      trades={m.trades}  win={m.win_rate:.0%}  "
          f"PF={_pf(m.profit_factor)}  expectancy={m.expectancy_r:+.2f}R  "
          f"net=${bt.end_equity-bt.start_equity:+,.2f}")

    # 2) Optimizer — best robust params (train/test).
    print("\n[2/3] Optimizing parameters (train/test robust)...")
    best = optimize(symbols, bars, source, "expectancy_r", min_trades=3, top=3,
                    start=start, end=end, timeframe=timeframe)
    if best:
        b = best[0]
        print(f"      best robust expectancy={b.robust_score:+.2f}  params={b.params}")
    else:
        print("      no parameter set cleared the sample bar")

    # 3) Walk-forward — out-of-sample verdict.
    print("\n[3/3] Walk-forward (out-of-sample, the honest test)...")
    wf = walk_forward(symbols, bars, source, folds=4, metric="expectancy_r",
                      min_trades=3, start=start, end=end, timeframe=timeframe)
    agg = wf.aggregate
    print(f"      OOS trades={agg.trades}  win={agg.win_rate:.0%}  "
          f"PF={_pf(agg.profit_factor)}  expectancy={agg.expectancy_r:+.2f}R")

    # Verdict (driven by out-of-sample).
    print("\n" + "=" * 64)
    verdict, why = _verdict(agg, real)
    print(f"  VERDICT: {verdict}")
    print(f"  {why}")
    print("\n" + goals.render(settings.account_equity, agg.expectancy_r, settings.risk_pct))
    print("=" * 64 + "\n")
    return {"backtest": m, "best_params": best, "walkforward": wf, "verdict": verdict}


def _pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def _verdict(agg, real: bool) -> tuple[str, str]:
    if agg.trades < 5:
        return "INSUFFICIENT DATA", ("Too few out-of-sample trades to judge — "
                                     "use more --bars or a longer real-data range.")
    pf = agg.profit_factor
    if agg.expectancy_r > 0 and pf > 1.2:
        base = "GO ✅" if real else "GO (on synthetic — re-run on real data to confirm)"
        return base, (f"Out-of-sample expectancy {agg.expectancy_r:+.2f}R, PF {_pf(pf)} — "
                      "the edge held up on unseen data.")
    if agg.expectancy_r > 0:
        return "MARGINAL ⚠", (f"OOS positive ({agg.expectancy_r:+.2f}R) but thin (PF {_pf(pf)}). "
                              "Edge is weak — keep risk minimal, gather more data.")
    return "NO-GO ❌", (f"Out-of-sample expectancy {agg.expectancy_r:+.2f}R — the edge did not "
                        "survive unseen data. Do not trade this live; refine first.")


def main() -> None:
    p = argparse.ArgumentParser(description="Full validation suite + verdict")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="synthetic",
                   choices=["synthetic", "csv", "databento", "tradovate"])
    p.add_argument("--bars", type=int, default=16000)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--timeframe", default="1m")
    args = p.parse_args()
    run(args.symbols, args.source, args.bars, args.start, args.end, args.timeframe)


if __name__ == "__main__":
    main()
