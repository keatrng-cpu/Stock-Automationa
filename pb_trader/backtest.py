"""Event-driven backtester for the PB Mechanical Model 2.0.

Usage:
    python -m pb_trader.backtest --symbols ES NQ --bars 5000
    python -m pb_trader.backtest --source databento --symbols ES NQ \
        --start 2026-01-01 --end 2026-06-26 --timeframe 1m
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from .config import settings
from .data import get_source
from .execution.paper import PaperBroker
from .models import Order, OrderType, Setup
from .risk import position_size, validate_setup
from .strategy.pb_model import PBModel
from .strategy.smt import smt_divergence


@dataclass
class Stats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    sum_r: float = 0.0
    max_dd: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def expectancy_r(self) -> float:
        return self.sum_r / self.trades if self.trades else 0.0


def run_backtest(symbols: list[str], source_name: str = "synthetic",
                 bars: int = 5000, start=None, end=None, timeframe="1m",
                 use_micros: bool = False, verbose: bool = True) -> Stats:
    source = get_source(source_name, bars=bars) if source_name == "synthetic" \
        else get_source(source_name)
    series = {s: source.history(s, start, end, timeframe) for s in symbols}
    n = min(len(v) for v in series.values())

    models = {s: PBModel(s, settings.confluence_threshold) for s in symbols}
    broker = PaperBroker(settings.account_equity)
    stats = Stats()
    peak = broker.equity
    setups_this_session = 0
    last_session = None

    for i in range(n):
        for s in symbols:
            bar = series[s][i]

            # Session A+ throttle.
            sess = bar.ts.date()
            if sess != last_session:
                last_session = sess
                setups_this_session = 0

            for trade in broker.on_bar(bar):
                _record(stats, trade)

            setup = models[s].on_bar(bar)
            if setup is None:
                continue
            if setups_this_session >= settings.max_setups_per_session:
                continue

            # SMT: only take the setup on the instrument SMT favors (if it has an opinion).
            other = [o for o in symbols if o != s]
            if other:
                smt = smt_divergence(series[s][:i + 1], series[other[0]][:i + 1])
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

        peak = max(peak, broker.equity)
        stats.max_dd = max(stats.max_dd, peak - broker.equity)

    if verbose:
        _print_report(stats, broker)
    return stats


def _record(stats: Stats, trade) -> None:
    stats.trades += 1
    stats.gross_pnl += trade.pnl
    stats.sum_r += trade.r_multiple
    if trade.pnl >= 0:
        stats.wins += 1
    else:
        stats.losses += 1


def _print_report(stats: Stats, broker: PaperBroker) -> None:
    print("\n" + "=" * 56)
    print("  PB MECHANICAL MODEL 2.0 — BACKTEST REPORT")
    print("=" * 56)
    print(f"  Start equity      : ${broker.start_equity:,.2f}")
    print(f"  End equity        : ${broker.equity:,.2f}")
    print(f"  Net P&L           : ${broker.equity - broker.start_equity:,.2f}")
    print(f"  Trades            : {stats.trades}")
    print(f"  Win rate          : {stats.win_rate:.1%}")
    print(f"  Expectancy        : {stats.expectancy_r:+.2f} R / trade")
    print(f"  Total R           : {stats.sum_r:+.2f}")
    print(f"  Max drawdown      : ${stats.max_dd:,.2f}")
    print("=" * 56)
    if stats.trades == 0:
        print("  No A+ setups met the 75% threshold on this data — that's the model")
        print("  doing its job (stand aside). Try more bars or a real data feed.")
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
    args = p.parse_args()
    run_backtest(args.symbols, args.source, args.bars, args.start, args.end,
                 args.timeframe, args.micros)


if __name__ == "__main__":
    main()
