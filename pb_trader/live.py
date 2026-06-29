"""Paper/live trading loop.

    python -m pb_trader.live --mode paper                 # synthetic feed, sim fills
    python -m pb_trader.live --mode paper --source tradovate   # demo live data, sim fills
    python -m pb_trader.live --mode live                  # REAL orders (gated by config)

Live orders require PB_MODE=live AND full Tradovate creds — otherwise the broker
refuses. Always paper-validate first.
"""
from __future__ import annotations

import argparse

from .config import settings
from .data import get_source
from .execution import get_broker
from .execution.paper import PaperBroker
from .journal import log_event
from .models import Order, OrderType
from .risk import position_size, validate_setup
from .strategy.pb_model import PBModel
from .strategy.smt import smt_divergence


def run_live(symbols: list[str], mode: str = "paper", source_name: str = "synthetic",
             bars: int = 3000, use_micros: bool | None = None) -> None:
    print(f"PB Trader live loop — mode={mode}, source={source_name}, symbols={symbols}")
    if use_micros is None:
        use_micros = settings.use_micros
    if settings.risk_is_aggressive:
        print(f"  \033[91m⚠ RISK {settings.risk_pct:.0%}/trade is aggressive — a routine "
              f"5-8 loss streak can halve the account. (PB_RISK_PCT)\033[0m")
    if mode == "live" and not settings.live_enabled:
        print("  [!] PB_MODE=live but creds incomplete — refusing live. Running paper.")
        mode = "paper"

    source = get_source(source_name, bars=bars) if source_name == "synthetic" \
        else get_source(source_name)
    broker = get_broker("paper" if mode == "paper" else "live",
                        **({"equity": settings.account_equity,
                            "slippage_ticks": settings.slippage_ticks}
                           if mode == "paper" else {}))
    models = {s: PBModel(s, settings.confluence_threshold, tp_max_r=settings.tp_max_r)
              for s in symbols}
    history: dict[str, list] = {s: [] for s in symbols}
    setups_today = 0
    last_day = None

    for bar in source.stream(symbols, timeframe="1m"):
        history[bar.symbol].append(bar)

        if isinstance(broker, PaperBroker):
            for trade in broker.on_bar(bar):
                log_event("trade", trade)
                print(f"  CLOSED {trade.symbol} {trade.side.value} "
                      f"{trade.r_multiple:+.2f}R  P&L ${trade.pnl:+,.2f}  ({trade.reason})")

        if bar.ts.date() != last_day:
            last_day = bar.ts.date()
            setups_today = 0

        setup = models[bar.symbol].on_bar(bar)
        if setup is None or setups_today >= settings.max_setups_per_session:
            continue

        # SMT instrument selection.
        other = [o for o in symbols if o != bar.symbol]
        if other and len(history[other[0]]) > 20:
            smt = smt_divergence(history[bar.symbol][-60:], history[other[0]][-60:])
            if smt.diverging and smt.superior and smt.superior != bar.symbol:
                continue

        ok, why = validate_setup(setup, settings.min_rr)
        if not ok:
            continue
        sized = position_size(setup, broker.equity, settings.risk_pct, use_micros)
        if sized.qty < 1:
            print(f"  [skip] {setup.symbol}: {sized.note}")
            continue

        order = Order(symbol=sized.symbol, side=setup.side, qty=sized.qty,
                      type=OrderType.MARKET, price=setup.entry, stop=setup.stop,
                      targets=setup.targets, tag=f"{setup.confluence:.0%}")
        log_event("signal", setup)
        print(f"\n  >>> A+ SETUP  {setup.symbol} {setup.side.value.upper()} "
              f"@ {setup.entry}  SL {setup.stop}  TP {setup.targets}  "
              f"conf {setup.confluence:.0%}  R:R {setup.rr():.1f}  [{setup.session}]")
        for r in setup.reasons:
            print(f"        - {r}")

        if isinstance(broker, PaperBroker):
            broker.submit_at(order, setup.entry, bar.ts)
        else:
            try:
                broker.submit(order)
                print("        >> LIVE order sent to Tradovate.")
            except PermissionError as e:
                print(f"        [blocked] {e}")
        setups_today += 1

    if isinstance(broker, PaperBroker):
        print(f"\nFinal paper equity: ${broker.equity:,.2f} "
              f"(start ${broker.start_equity:,.2f})")


def main() -> None:
    p = argparse.ArgumentParser(description="PB Trader paper/live loop")
    p.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    p.add_argument("--mode", default="paper", choices=["paper", "live"])
    p.add_argument("--source", default="synthetic",
                   choices=["synthetic", "csv", "databento", "tradovate"])
    p.add_argument("--bars", type=int, default=3000)
    p.add_argument("--micros", action="store_true", default=None,
                   help="force micro contracts (default: per PB_USE_MICROS / config)")
    args = p.parse_args()
    run_live(args.symbols, args.mode, args.source, args.bars, args.micros)


if __name__ == "__main__":
    main()
