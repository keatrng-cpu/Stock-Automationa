"""Walk-forward analysis — the gold standard for proving an edge isn't curve-fit.

Slides a rolling window across the data: optimize parameters on an in-sample (IS)
window, then trade them UNTOUCHED on the next out-of-sample (OOS) window, step
forward, repeat. The stitched OOS results — compounding equity fold to fold — are
the honest "what you'd actually have made trading this forward" answer. If OOS
performance collapses vs IS, the parameters were overfit.

    python -m pb_trader.walkforward --bars 20000 --folds 5 --metric expectancy_r
"""
from __future__ import annotations

import argparse
import itertools
import os
from dataclasses import dataclass, field

from .analytics import Metrics, compute_metrics, format_report
from .backtest import load_series, run_backtest
from .config import settings
from .models import Trade
from .optimize import _objective

# Walk-forward runs the grid once PER FOLD, so use a coarser grid than the full
# optimizer (folds × grid backtests adds up fast). Override via the `grid` arg.
WF_GRID = {
    "htf_minutes": [15, 30],
    "swing_k": [2, 3],
    "confluence_threshold": [0.75, 0.80],
}


@dataclass
class Fold:
    index: int
    params: dict
    is_score: float
    oos: Metrics
    oos_trades: int
    oos_net: float


@dataclass
class WalkForwardResult:
    folds: list[Fold] = field(default_factory=list)
    aggregate: Metrics = None
    all_oos_trades: list[Trade] = field(default_factory=list)


# ---- IS parameter search (parallel), worker globals pickled once per process ----
_WF: dict = {}


def _wf_init(series, symbols, source, bars, metric, min_trades):
    _WF.update(series=series, symbols=symbols, source=source, bars=bars,
               metric=metric, min_trades=min_trades)


def _wf_eval(params: dict):
    m = run_backtest(_WF["symbols"], _WF["source"], _WF["bars"], verbose=False,
                     model_kwargs=dict(params), series=_WF["series"]).metrics.as_dict()
    return params, _objective(m, _WF["metric"], _WF["min_trades"])


def _best_params(is_series, symbols, source, bars, grid, metric, min_trades, jobs):
    keys = list(grid.keys())
    combos = [dict(zip(keys, c)) for c in itertools.product(*(grid[k] for k in keys))]
    combos = [p for p in combos if p.get("ote_low", 0) < p.get("ote_high", 1)]
    args = (is_series, symbols, source, bars, metric, min_trades)

    scored = []
    if jobs > 1:
        try:
            import multiprocessing as mp
            with mp.Pool(jobs, initializer=_wf_init, initargs=args) as pool:
                scored = pool.map(_wf_eval, combos)
        except Exception:  # noqa: BLE001
            scored = []
    if not scored:
        _wf_init(*args)
        scored = [_wf_eval(p) for p in combos]

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0]  # (params, is_score)


def _slice(series: dict, lo: int, hi: int) -> dict:
    return {s: bars[lo:hi] for s, bars in series.items()}


def walk_forward(symbols, bars=20000, source="synthetic", folds=5, is_ratio=3,
                 metric="expectancy_r", min_trades=3, grid: dict | None = None,
                 jobs: int | None = None, start=None, end=None,
                 timeframe="1m") -> WalkForwardResult:
    grid = grid or WF_GRID
    series = load_series(symbols, source, bars, start, end, timeframe)
    n = min(len(v) for v in series.values())

    # Rolling geometry: IS = is_ratio * OOS; folds step forward by one OOS length.
    oos_len = n // (is_ratio + folds)
    is_len = is_ratio * oos_len
    if oos_len < 50:
        raise ValueError("not enough bars for this fold configuration — use more --bars "
                         "or fewer --folds")

    jobs = jobs or min(os.cpu_count() or 1, 8)
    result = WalkForwardResult(aggregate=None)
    equity = settings.account_equity

    for k in range(folds):
        is_lo = k * oos_len
        is_hi = is_lo + is_len
        oos_hi = is_hi + oos_len
        is_series = _slice(series, is_lo, is_hi)
        oos_series = _slice(series, is_hi, oos_hi)

        params, is_score = _best_params(is_series, symbols, source, bars, grid,
                                        metric, min_trades, jobs)
        # Trade the chosen params forward on OOS, compounding equity across folds.
        res = run_backtest(symbols, source, bars, verbose=False,
                           model_kwargs=dict(params), series=oos_series,
                           start_equity=equity)
        equity = res.end_equity
        result.all_oos_trades.extend(res.trades)
        result.folds.append(Fold(k + 1, params, is_score, res.metrics,
                                 res.metrics.trades, res.end_equity - res.start_equity))

    result.aggregate = compute_metrics(result.all_oos_trades, settings.account_equity)
    return result


def _print(result: WalkForwardResult, metric: str) -> None:
    print("\n" + "=" * 72)
    print("  WALK-FORWARD ANALYSIS — stitched OUT-OF-SAMPLE performance")
    print("=" * 72)
    print(f"  {'Fold':<5}{'IS '+metric:<16}{'OOS trades':<12}{'OOS net':<12}{'params'}")
    for f in result.folds:
        compact = {k: f.params[k] for k in list(f.params)[:3]}
        print(f"  #{f.index:<4}{f.is_score:<16.2f}{f.oos_trades:<12}"
              f"${f.oos_net:<11,.2f}{compact}...")

    agg = result.aggregate
    print("\n  --- Aggregate OOS (the honest forward-test result) ---")
    if agg.trades == 0:
        print("  No OOS trades — widen the grid / data, or lower --min-trades.\n")
        return
    print(format_report(agg, result.all_oos_trades))
    print(f"\n  OOS net P&L (compounded): "
          f"${agg.equity_curve[-1] - agg.equity_curve[0]:+,.2f}")
    print("  Read: if aggregate OOS expectancy/PF stays positive across folds, the")
    print("  edge is robust. If IS looks great but OOS collapses, it was overfit.\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Walk-forward analysis")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="synthetic")
    p.add_argument("--bars", type=int, default=20000)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--is-ratio", type=int, default=3, help="IS window = ratio * OOS window")
    p.add_argument("--metric", default="expectancy_r",
                   choices=["expectancy_r", "profit_factor", "sharpe", "net_pnl"])
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    args = p.parse_args()
    res = walk_forward(args.symbols, args.bars, args.source, args.folds, args.is_ratio,
                       args.metric, args.min_trades, jobs=args.jobs,
                       start=args.start, end=args.end)
    _print(res, args.metric)


if __name__ == "__main__":
    main()
