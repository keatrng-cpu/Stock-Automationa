"""Parameter tuning harness with train/test robustness.

Grid-searches model parameters (HTF timeframes, swing-k, OTE thresholds, confluence
threshold), but ranks by *out-of-sample* performance and consistency — not in-sample
fit — so we find robust settings, not overfit ones.

    python -m pb_trader.optimize --bars 12000 --metric expectancy_r --min-trades 8

For each combo it splits the data in half: optimize-on-train, validate-on-test, and
scores by the WORSE of the two (penalizing combos that only work on one slice).
"""
from __future__ import annotations

import argparse
import itertools
import os
from dataclasses import dataclass

from .backtest import load_series, run_backtest


# The search space. Keep it small and meaningful — bigger grids overfit faster.
GRID = {
    "htf_minutes": [10, 15, 30],
    "swing_k": [2, 3],
    "ote_low": [0.5, 0.62],
    "ote_high": [0.79, 0.9],
    "confluence_threshold": [0.75, 0.80],
}


@dataclass
class ComboResult:
    params: dict
    train: dict
    test: dict
    robust_score: float
    train_trades: int
    test_trades: int


def _slice(series: dict, lo: float, hi: float) -> dict:
    out = {}
    for s, bars in series.items():
        n = len(bars)
        out[s] = bars[int(n * lo):int(n * hi)]
    return out


def _objective(metrics_dict: dict, metric: str, min_trades: int) -> float:
    """Score a single run; heavily penalize undersampled results."""
    trades = metrics_dict.get("trades", 0)
    if trades < min_trades:
        return -1e9 + trades  # still order by trade count among the disqualified
    val = metrics_dict.get(metric, 0.0)
    if val == float("inf"):
        val = 10.0
    # Mild sample-size reward so 30 good trades beats 8 great-looking ones.
    return val


# Worker-side globals (populated per process via the Pool initializer) so the large
# train/test bar series are pickled once per worker, not once per task.
_W: dict = {}


def _init_worker(train, test, symbols, source, bars, metric, min_trades):
    _W.update(train=train, test=test, symbols=symbols, source=source, bars=bars,
              metric=metric, min_trades=min_trades)


def _eval_combo(params: dict) -> ComboResult:
    tr = run_backtest(_W["symbols"], _W["source"], _W["bars"], verbose=False,
                      model_kwargs=dict(params), series=_W["train"]).metrics.as_dict()
    te = run_backtest(_W["symbols"], _W["source"], _W["bars"], verbose=False,
                      model_kwargs=dict(params), series=_W["test"]).metrics.as_dict()
    s_tr = _objective(tr, _W["metric"], _W["min_trades"])
    s_te = _objective(te, _W["metric"], _W["min_trades"])
    return ComboResult(params, tr, te, min(s_tr, s_te),
                       tr.get("trades", 0), te.get("trades", 0))


def optimize(symbols, bars=12000, source="synthetic", metric="expectancy_r",
             min_trades=8, top=10, start=None, end=None, timeframe="1m",
             grid: dict | None = None, jobs: int | None = None) -> list[ComboResult]:
    grid = grid or GRID
    series = load_series(symbols, source, bars, start, end, timeframe)
    train = _slice(series, 0.0, 0.5)
    test = _slice(series, 0.5, 1.0)

    keys = list(grid.keys())
    combos = [dict(zip(keys, c)) for c in itertools.product(*(grid[k] for k in keys))]
    combos = [p for p in combos if p.get("ote_low", 0) < p.get("ote_high", 1)]

    jobs = jobs or min(os.cpu_count() or 1, len(combos))
    print(f"Optimizing {len(combos)} parameter combinations across {jobs} core(s) "
          f"(train/test split, metric={metric}, min_trades={min_trades})...\n")

    args = (train, test, symbols, source, bars, metric, min_trades)
    results: list[ComboResult] = []
    if jobs > 1:
        try:
            import multiprocessing as mp
            with mp.Pool(jobs, initializer=_init_worker, initargs=args) as pool:
                results = pool.map(_eval_combo, combos)
        except Exception:  # noqa: BLE001 — fall back to serial if no fork/spawn
            results = []
    if not results:
        _init_worker(*args)
        results = [_eval_combo(p) for p in combos]

    results.sort(key=lambda r: r.robust_score, reverse=True)
    return results[:top]


def _fmt(d: dict, metric: str) -> str:
    pf = d.get("profit_factor", 0.0)
    pf = "inf" if pf == float("inf") else f"{pf:.2f}"
    return (f"tr={d.get('trades',0):>3} win={d.get('win_rate',0):>4.0%} "
            f"PF={pf:>4} {metric}={d.get(metric,0):>+.2f}")


def main() -> None:
    p = argparse.ArgumentParser(description="PB model parameter optimizer")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="synthetic")
    p.add_argument("--bars", type=int, default=12000)
    p.add_argument("--metric", default="expectancy_r",
                   choices=["expectancy_r", "profit_factor", "sharpe", "net_pnl"])
    p.add_argument("--min-trades", type=int, default=8)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--jobs", type=int, default=None, help="parallel workers (default: all cores)")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    args = p.parse_args()

    best = optimize(args.symbols, args.bars, args.source, args.metric,
                    args.min_trades, args.top, args.start, args.end, jobs=args.jobs)

    print("=" * 78)
    print(f"  TOP {len(best)} ROBUST PARAMETER SETS (ranked by worse of train/test)")
    print("=" * 78)
    for i, r in enumerate(best, 1):
        print(f"\n  #{i}  robust {args.metric} = {r.robust_score:+.2f}")
        print(f"      params: {r.params}")
        print(f"      train : {_fmt(r.train, args.metric)}")
        print(f"      test  : {_fmt(r.test, args.metric)}")
    if best and best[0].robust_score < -1e8:
        print("\n  (No combo cleared the min-trades bar on both halves — "
              "lower --min-trades or use more --bars / real data.)")
    print()


if __name__ == "__main__":
    main()
