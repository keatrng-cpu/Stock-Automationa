"""Event-driven backtester for the PB Mechanical Model 2.0.

Usage:
    python -m pb_trader.backtest --symbols ES NQ --bars 5000
    python -m pb_trader.backtest --source databento --symbols ES NQ \
        --start 2026-01-01 --end 2026-06-26 --timeframe 1m
    python -m pb_trader.backtest --bars 8000 --equity-csv journal/equity.csv
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from .analytics import Metrics, compute_metrics, format_report
from .config import settings
from .data import get_source
from .execution.paper import PaperBroker
from .models import Order, OrderType, Trade
from .risk import position_size, validate_setup
from .strategy.pb_model import PBModel
from .strategy.smt import smt_divergence


@dataclass
class BacktestResult:
    metrics: Metrics
    trades: list[Trade] = field(default_factory=list)
    start_equity: float = 0.0
    end_equity: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0


def load_series(symbols, source_name="synthetic", bars=5000, start=None, end=None,
                timeframe="1m") -> dict:
    """Load bar series once; reusable across many backtests (e.g. the optimizer)."""
    source = get_source(source_name, bars=bars) if source_name == "synthetic" \
        else get_source(source_name)
    return {s: source.history(s, start, end, timeframe) for s in symbols}


def run_backtest(symbols: list[str], source_name: str = "synthetic",
                 bars: int = 5000, start=None, end=None, timeframe="1m",
                 use_micros: bool = False, verbose: bool = True,
                 model_kwargs: dict | None = None, series: dict | None = None,
                 equity_csv: str | None = None) -> BacktestResult:
    if series is None:
        series = load_series(symbols, source_name, bars, start, end, timeframe)
    symbols = list(series.keys())
    n = min(len(v) for v in series.values())

    mk = model_kwargs or {}
    threshold = mk.pop("confluence_threshold", settings.confluence_threshold)
    models = {s: PBModel(s, threshold, **mk) for s in symbols}
    broker = PaperBroker(settings.account_equity, settings.slippage_ticks)
    setups_this_session = 0
    last_session = None

    for i in range(n):
        for s in symbols:
            bar = series[s][i]
            sess = bar.ts.date()
            if sess != last_session:
                last_session = sess
                setups_this_session = 0

            broker.on_bar(bar)  # process exits; trades retained on broker.trades

            setup = models[s].on_bar(bar)
            if setup is None or setups_this_session >= settings.max_setups_per_session:
                continue

            other = [o for o in symbols if o != s]
            if other:
                # Bounded recent window — SMT only compares recent swings, so slicing
                # the full history each bar would be needless O(n^2).
                lo = max(0, i - 60)
                smt = smt_divergence(series[s][lo:i + 1], series[other[0]][lo:i + 1])
                if smt.diverging and smt.superior and smt.superior != s:
                    continue

            ok, _ = validate_setup(setup)
            if not ok:
                continue
            sized = position_size(setup, broker.equity, settings.risk_pct, use_micros)
            if sized.qty < 1:
                continue

            order = Order(symbol=sized.symbol, side=setup.side, qty=sized.qty,
                          type=OrderType.MARKET, price=setup.entry, stop=setup.stop,
                          targets=setup.targets, tag=f"{setup.confluence:.0%}")
            broker.submit_at(order, setup.entry, bar.ts)
            setups_this_session += 1

    metrics = compute_metrics(broker.trades, broker.start_equity)
    result = BacktestResult(metrics, broker.trades, broker.start_equity,
                            broker.equity, broker.total_commission, broker.total_slippage)

    if equity_csv:
        _write_equity_csv(metrics.equity_curve, equity_csv)
    if verbose:
        _print_report(result)
    return result


def _write_equity_csv(curve, path: str) -> None:
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("step,equity\n")
        for i, v in enumerate(curve):
            fh.write(f"{i},{v:.2f}\n")
    print(f"  equity curve written to {path}")


def _print_report(r: BacktestResult) -> None:
    m = r.metrics
    print("\n" + "=" * 56)
    print("  PB MECHANICAL MODEL 2.0 — BACKTEST REPORT")
    print("=" * 56)
    print(f"  Start equity      : ${r.start_equity:,.2f}")
    print(f"  End equity        : ${r.end_equity:,.2f}")
    print(f"  Net P&L           : ${r.end_equity - r.start_equity:,.2f}")
    print(f"  Commissions paid  : ${r.commission:,.2f}")
    print(f"  Slippage cost     : ${r.slippage:,.2f}")
    print(f"  Trades            : {m.trades}")
    print(f"  Win rate          : {m.win_rate:.1%}")
    print(f"  Total R           : {m.sum_r:+.2f}")
    print(f"  Max drawdown      : ${m.max_drawdown:,.2f}")
    print("=" * 56)
    if m.trades == 0:
        print("  No A+ setups met the 75% threshold on this data — that's the model")
        print("  doing its job (stand aside). Try more bars or a real data feed.\n")
        return
    print(format_report(m, r.trades))
    print()


def main() -> None:
    p = argparse.ArgumentParser(description="PB Mechanical Model 2.0 backtester")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--source", default="synthetic",
                   choices=["synthetic", "csv", "databento", "tradovate"])
    p.add_argument("--bars", type=int, default=5000)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--micros", action="store_true", help="size in micro contracts")
    p.add_argument("--equity-csv", default=None, help="write the equity curve to CSV")
    args = p.parse_args()
    run_backtest(args.symbols, args.source, args.bars, args.start, args.end,
                 args.timeframe, args.micros, equity_csv=args.equity_csv)


if __name__ == "__main__":
    main()
