"""Backtest analytics: performance metrics, breakdowns, and an ASCII equity curve.

Stdlib-only so it runs anywhere. Computes the metrics that actually tell you whether
an edge is real: profit factor, expectancy, Sharpe, drawdown, and per-segment win rates.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .models import Trade


@dataclass
class Metrics:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0          # positive magnitude
    net_pnl: float = 0.0
    sum_r: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy_r: float = 0.0
    win_rate: float = 0.0
    # Honest round-trip stats: scale-out partials collapsed back into one position, so
    # a banked partial + breakeven runner counts as ONE outcome, not two "wins".
    round_trips: int = 0
    rt_win_rate: float = 0.0
    rt_expectancy_r: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "equity_curve"}


def compute_metrics(trades: list[Trade], start_equity: float) -> Metrics:
    m = Metrics()
    if not trades:
        m.equity_curve = [start_equity]
        return m

    equity = start_equity
    peak = start_equity
    curve = [start_equity]
    rets: list[float] = []

    for t in trades:
        m.trades += 1
        m.net_pnl += t.pnl
        m.sum_r += t.r_multiple
        if t.pnl >= 0:
            m.wins += 1
            m.gross_profit += t.pnl
        else:
            m.losses += 1
            m.gross_loss += -t.pnl
        prev = equity
        equity += t.pnl
        curve.append(equity)
        rets.append((equity - prev) / prev if prev else 0.0)
        peak = max(peak, equity)
        m.max_drawdown = max(m.max_drawdown, peak - equity)

    m.win_rate = m.wins / m.trades
    m.avg_win = m.gross_profit / m.wins if m.wins else 0.0
    m.avg_loss = m.gross_loss / m.losses if m.losses else 0.0
    m.expectancy_r = m.sum_r / m.trades
    m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 \
        else (float("inf") if m.gross_profit > 0 else 0.0)

    # Per-trade Sharpe (annualization left out — comparative measure across runs).
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        m.sharpe = (mean / sd * math.sqrt(len(rets))) if sd > 0 else 0.0

    m.equity_curve = curve

    # Collapse legs sharing (symbol, opened_ts) into round-trip positions for honest
    # win-rate / expectancy (a scale partial + its runner = one position outcome).
    rt: dict = {}
    for t in trades:
        key = (t.symbol, t.opened_ts)
        agg = rt.setdefault(key, [0.0, 0.0])
        agg[0] += t.pnl
        agg[1] += t.r_multiple
    m.round_trips = len(rt)
    if rt:
        rt_wins = sum(1 for pnl, _ in rt.values() if pnl >= 0)
        m.rt_win_rate = rt_wins / m.round_trips
        m.rt_expectancy_r = sum(r for _, r in rt.values()) / m.round_trips
    return m


def breakdown(trades: list[Trade], key: Callable[[Trade], str]) -> dict[str, Metrics]:
    """Group trades by a key function and compute per-group metrics."""
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    # Each group's equity starts at 0 so net_pnl/PF/win-rate are meaningful per segment.
    return {k: compute_metrics(v, 0.0) for k, v in sorted(groups.items())}


def ascii_equity(curve: list[float], width: int = 56, height: int = 9) -> str:
    """Render an equity curve as ASCII art."""
    if len(curve) < 2:
        return "  (no trades to plot)"
    lo, hi = min(curve), max(curve)
    rng = hi - lo or 1.0
    # Sample the curve down to `width` columns.
    step = max(1, len(curve) // width)
    sampled = curve[::step]
    rows = [[" "] * len(sampled) for _ in range(height)]
    for x, v in enumerate(sampled):
        y = int((v - lo) / rng * (height - 1))
        rows[height - 1 - y][x] = "•"
    body = "\n".join("  " + "".join(r) for r in rows)
    return f"  {hi:,.0f} ┐\n{body}\n  {lo:,.0f} ┘"


def confluence_bucket(t: Trade) -> str:
    """Group by the confluence tag (e.g. '77%') into coarse buckets."""
    try:
        pct = int(str(t.tag).rstrip("%"))
    except (ValueError, AttributeError):
        return "n/a"
    if pct >= 90:
        return "90%+"
    if pct >= 85:
        return "85-89%"
    if pct >= 80:
        return "80-84%"
    return "75-79%"


def format_report(metrics: Metrics, trades: list[Trade]) -> str:
    lines = []
    lines.append(ascii_equity(metrics.equity_curve))
    lines.append("")
    pf = "inf" if metrics.profit_factor == float("inf") else f"{metrics.profit_factor:.2f}"
    lines.append(f"  Profit factor     : {pf}")
    lines.append(f"  Sharpe (per-trade): {metrics.sharpe:.2f}")
    lines.append(f"  Avg win / loss    : ${metrics.avg_win:,.2f} / ${metrics.avg_loss:,.2f}")
    lines.append(f"  Expectancy        : {metrics.expectancy_r:+.2f} R")

    if trades:
        lines.append("\n  By side:")
        for k, m in breakdown(trades, lambda t: t.side.value).items():
            lines.append(f"    {k:<6} {m.trades:>3} trades  "
                         f"win {m.win_rate:>4.0%}  net ${m.net_pnl:>+9,.2f}")
        lines.append("  By confluence:")
        for k, m in breakdown(trades, confluence_bucket).items():
            lines.append(f"    {k:<7} {m.trades:>3} trades  "
                         f"win {m.win_rate:>4.0%}  exp {m.expectancy_r:>+.2f}R")
    return "\n".join(lines)
