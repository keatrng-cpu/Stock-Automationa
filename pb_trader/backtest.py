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
from .brain import TradingBrain
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
    checkpoints: list = field(default_factory=list)   # periodic snapshots (e.g. weekly)
    halt_days: int = 0                                 # days the daily circuit breaker tripped
    skips: list = field(default_factory=list)          # counterfactual skip records (veto calibration)


def _hypo_r(setup, series: list, i: int, retest_window: int) -> float | None:
    """Counterfactual: what R would this SKIPPED setup have made? Fills the same limit on a
    later-bar retest (no look-ahead), then resolves stop vs target pessimistically (stop
    first if both touch). Returns R, or None if it never would have filled. Used to calibrate
    whether the brain's vetoes actually help — the core 'is our learning right?' check."""
    entry, stop = setup.entry, setup.stop
    target = setup.targets[0] if setup.targets else None
    if target is None or stop is None or entry == stop:
        return None
    risk = abs(entry - stop)
    rr = abs(target - entry) / risk if risk else 0.0
    long = setup.side.value == "long"
    filled = False
    # Look forward over the retest window to fill, then to resolution.
    for j in range(i + 1, min(len(series), i + 1 + retest_window * 4)):
        b = series[j]
        if not filled:
            if b.low <= entry <= b.high:
                filled = True
            elif j - i > retest_window:
                return None                    # limit expired unfilled — veto was moot
            else:
                continue
        if filled:
            hit_stop = b.low <= stop if long else b.high >= stop
            hit_tgt = b.high >= target if long else b.low <= target
            if hit_stop:
                return -1.0                    # pessimistic: stop first if both
            if hit_tgt:
                return round(rr, 2)
    return None                                 # unresolved within the window


def load_series(symbols, source_name="synthetic", bars=5000, start=None, end=None,
                timeframe="1m", seed: int | None = None) -> dict:
    """Load bar series once; reusable across many backtests (e.g. the optimizer).

    `seed` selects a different randomized market from a generator source — pass a range of
    seeds to test robustness across many independent markets (see montecarlo.py)."""
    from .data import GENERATORS
    from .timeframes import parse_tf
    if source_name in GENERATORS:
        kw = {"bars": bars, "tf_seconds": parse_tf(timeframe)}
        if seed is not None:
            kw["seed"] = seed
        source = get_source(source_name, **kw)
    else:
        source = get_source(source_name)
    return {s: source.history(s, start, end, timeframe) for s in symbols}


def run_backtest(symbols: list[str], source_name: str = "synthetic",
                 bars: int = 5000, start=None, end=None, timeframe="1m",
                 use_micros: bool | None = None, verbose: bool = True,
                 model_kwargs: dict | None = None, series: dict | None = None,
                 equity_csv: str | None = None,
                 start_equity: float | None = None,
                 brain: TradingBrain | None = None,
                 use_brain: bool = True,
                 checkpoint_bars: int | None = None,
                 profile: str | None = None,
                 seed: int | None = None,
                 mtf: bool = False,
                 track_skips: bool = False) -> BacktestResult:
    if use_micros is None:
        use_micros = settings.use_micros
    if profile:
        from .profiles import get_profile
        model_kwargs = {**get_profile(profile).model_kwargs(), **(model_kwargs or {})}
    if use_brain and brain is None:
        brain = TradingBrain(base_threshold=settings.confluence_threshold)
    if series is None:
        series = load_series(symbols, source_name, bars, start, end, timeframe, seed=seed)
    symbols = list(series.keys())
    n = min(len(v) for v in series.values())

    mk = model_kwargs or {}
    threshold = mk.pop("confluence_threshold", settings.confluence_threshold)
    mk.setdefault("tp_max_r", settings.tp_max_r)
    # Master any base timeframe: auto-select the top-down HTFs from the ladder.
    from .timeframes import htf_minutes_for
    h1, h2 = htf_minutes_for(timeframe)
    mk.setdefault("htf_minutes", h1)
    mk.setdefault("htf2_minutes", h2)
    mk.setdefault("timeframe", timeframe)
    if mtf:
        from .mtf import MultiTimeframeModel
        models = {s: MultiTimeframeModel(s, threshold, **mk) for s in symbols}
    else:
        models = {s: PBModel(s, threshold, **mk) for s in symbols}
    broker = PaperBroker(start_equity or settings.account_equity, settings.slippage_ticks,
                         manage=settings.trade_mgmt, scale_at_r=settings.scale_at_r,
                         scale_frac=settings.scale_frac,
                         max_stop_slippage_r=settings.max_stop_slippage_r)
    from .governor import SessionGovernor
    governor = SessionGovernor(
        strong_threshold=settings.strong_threshold,
        medium_threshold=settings.confluence_threshold,
        weekly_strong_target=settings.weekly_strong_target,
        weekly_medium_target=settings.weekly_medium_target,
        daily_cap=settings.max_setups_per_session,
        daily_loss_limit_pct=settings.daily_loss_limit_pct)
    last_session = None
    # Pending LIMIT orders: a signal at bar i places a limit at setup.entry that only
    # fills if price RETESTS it on a LATER bar (no look-ahead), expiring after a window.
    pending: dict = {s: [] for s in symbols}
    RETEST_WINDOW = 20
    checkpoints: list = []
    skips: list = []          # counterfactual veto calibration (when track_skips)

    for i in range(n):
        if checkpoint_bars and i > 0 and i % checkpoint_bars == 0:
            ad = brain.adaptive if brain else None
            checkpoints.append({
                "bar": i, "period": i // checkpoint_bars, "equity": broker.equity,
                "trades": len(broker.trades),
                "risk_mult": ad.risk_multiplier() if ad else 1.0,
                "thr_bump": ad.threshold_bump() if ad else 0.0,
                "loss_streak": ad.loss_streak if ad else 0,
                "win_streak": ad.win_streak if ad else 0,
                "drawdown": ad.drawdown if ad else 0.0,
            })
        if brain:
            brain.tick()                        # per-bar heartbeat (anti-deadlock thaw)
        for s in symbols:
            bar = series[s][i]
            governor.roll(bar.ts, broker.equity)   # day/week rollover + breaker reset

            for trade in broker.on_bar(bar):    # process exits; brain learns from closes
                if brain:
                    brain.learn(trade, broker.equity)

            # Fill any pending limit whose price the CURRENT bar trades through (the
            # retest happens after the signal bar — realistic, no look-ahead).
            still: list = []
            for p in pending[s]:
                if i > p["expiry"]:
                    continue                    # expired unfilled
                if bar.low <= p["order"].price <= bar.high:
                    broker.submit_at(p["order"], p["order"].price, bar.ts)
                else:
                    still.append(p)
            pending[s] = still

            setup = models[s].on_bar(bar)
            if setup is None:
                continue
            setup.tag = f"{setup.confluence:.0%}"
            # Cadence + daily circuit breaker (a CEILING, never a forcer): blocks new entries
            # when halted for the day or the weekly cadence is already met. Quality unchanged.
            allowed, _gov_reason = governor.can_enter(setup.confluence, broker.equity)
            if not allowed:
                if track_skips:
                    tag = "breaker" if "breaker" in _gov_reason else \
                          ("cadence" if "cadence" in _gov_reason else "daily-cap")
                    skips.append({"reason": f"gov-{tag}", "conf": setup.confluence,
                                  "hypo_r": _hypo_r(setup, series[s], i, RETEST_WINDOW)})
                continue

            other = [o for o in symbols if o != s]
            if other:
                lo = max(0, i - 60)
                smt = smt_divergence(series[s][lo:i + 1], series[other[0]][lo:i + 1])
                if smt.diverging and smt.superior and smt.superior != s:
                    if track_skips:
                        skips.append({"reason": "smt-veto", "conf": setup.confluence,
                                      "hypo_r": _hypo_r(setup, series[s], i, RETEST_WINDOW)})
                    continue

            ok, _ = validate_setup(setup, settings.min_rr)
            if not ok:
                continue
            sized = position_size(setup, broker.equity, settings.risk_pct, use_micros)
            if sized.qty < 1:
                continue

            qty = sized.qty
            if brain:
                dec = brain.decide(setup, broker.equity)
                if not dec.take:
                    if track_skips:
                        reason = "brain-veto" if dec.edge <= brain.edge_veto else "below-bar"
                        skips.append({"reason": reason, "conf": setup.confluence,
                                      "hypo_r": _hypo_r(setup, series[s], i, RETEST_WINDOW)})
                    continue
                qty = max(0, int(round(sized.qty * dec.size_mult)))
                if qty < 1:
                    continue

            order = Order(symbol=sized.symbol, side=setup.side, qty=qty,
                          type=OrderType.LIMIT, price=setup.entry, stop=setup.stop,
                          targets=setup.targets, tag=f"{setup.confluence:.0%}",
                          features=setup.features)
            pending[s].append({"order": order, "expiry": i + RETEST_WINDOW})
            governor.record_entry(setup.confluence)   # count toward the weekly cadence

    metrics = compute_metrics(broker.trades, broker.start_equity)
    result = BacktestResult(metrics, broker.trades, broker.start_equity,
                            broker.equity, broker.total_commission, broker.total_slippage,
                            checkpoints=checkpoints, halt_days=governor.halt_day_count,
                            skips=skips)

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
    if settings.risk_is_aggressive:
        print(f"  \033[91m⚠ RISK {settings.risk_pct:.0%}/trade — aggressive. A normal 5-8 "
              f"loss streak\033[0m")
        print(f"  \033[91m  can cut this account ~40-60%. Reduce PB_RISK_PCT to de-risk.\033[0m")
        print("-" * 56)
    print(f"  Start equity      : ${r.start_equity:,.2f}")
    print(f"  End equity        : ${r.end_equity:,.2f}")
    print(f"  Net P&L           : ${r.end_equity - r.start_equity:,.2f}")
    print(f"  Commissions paid  : ${r.commission:,.2f}")
    print(f"  Slippage cost     : ${r.slippage:,.2f}")
    print(f"  Fills (legs)      : {m.trades}")
    print(f"  Round-trips       : {m.round_trips}  (positions, partials collapsed)")
    print(f"  Win rate (RT)     : {m.rt_win_rate:.1%}   expectancy {m.rt_expectancy_r:+.2f}R")
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
    from .timeframes import LADDER
    p.add_argument("--timeframe", default="1m", choices=LADDER,
                   help="base timeframe (30s..240m); HTFs auto-selected")
    p.add_argument("--micros", action="store_true", default=None,
                   help="force micro contracts (default: per PB_USE_MICROS / config)")
    p.add_argument("--equity-csv", default=None, help="write the equity curve to CSV")
    p.add_argument("--profile", default=None,
                   choices=["blake", "ronan", "patty", "patty_scalp", "default"],
                   help="PB trader profile (setup/execution style)")
    args = p.parse_args()
    run_backtest(args.symbols, args.source, args.bars, args.start, args.end,
                 args.timeframe, args.micros, equity_csv=args.equity_csv,
                 profile=args.profile)


if __name__ == "__main__":
    main()
