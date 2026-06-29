"""Paper / simulated broker. Bracket orders filled against incoming bars.

Conservative fill model:
  - Market entries fill at the bar's close (the bar that triggered the signal).
  - Stops fill at the stop price if the bar's range touches it (gap-through fills at
    the worse of stop/open). Targets fill at the target price if touched.
  - If both stop and target are touched in the same bar, assume the STOP hits first
    (pessimistic — avoids flattering results).
"""
from __future__ import annotations

from ..models import CONTRACTS, Bar, Order, OrderType, Position, Side, Trade


class PaperBroker:
    def __init__(self, equity: float = 10_000.0, slippage_ticks: float = 1.0):
        self._equity = equity
        self.start_equity = equity
        self.slippage_ticks = slippage_ticks
        self.positions: list[Position] = []
        self.trades: list[Trade] = []
        self.total_commission = 0.0
        self.total_slippage = 0.0

    def _spec(self, symbol: str) -> dict:
        return CONTRACTS.get(symbol, {"point_value": 1.0, "tick": 0.25, "commission": 0.0})

    @property
    def equity(self) -> float:
        return self._equity

    def open_positions(self) -> list[Position]:
        return list(self.positions)

    def submit(self, order: Order) -> Position | None:
        if order.type is OrderType.MARKET and order.price is None:
            return None  # market entries are created via submit_at with a fill price
        return None

    def submit_at(self, order: Order, fill_price: float, ts) -> Position:
        # Entry slippage: market fills go against you by `slippage_ticks`.
        spec = self._spec(order.symbol)
        slip = self.slippage_ticks * spec["tick"]
        entry = fill_price + slip if order.side is Side.LONG else fill_price - slip
        pos = Position(
            symbol=order.symbol, side=order.side, qty=order.qty,
            entry=entry, stop=order.stop, targets=list(order.targets),
            opened_ts=ts, tag=order.tag,
        )
        self.positions.append(pos)
        return pos

    def _point_value(self, symbol: str) -> float:
        return self._spec(symbol)["point_value"]

    def on_bar(self, bar: Bar) -> list[Trade]:
        closed: list[Trade] = []
        still_open: list[Position] = []
        for pos in self.positions:
            if pos.symbol != bar.symbol:
                still_open.append(pos)
                continue
            exit_price, reason = self._check_exit(pos, bar)
            if exit_price is None:
                still_open.append(pos)
                continue
            closed.append(self._close(pos, exit_price, bar, reason))
        self.positions = still_open
        return closed

    def _check_exit(self, pos: Position, bar: Bar):
        target = pos.targets[0] if pos.targets else None
        if pos.side is Side.LONG:
            hit_stop = bar.low <= pos.stop
            hit_tgt = target is not None and bar.high >= target
            if hit_stop:
                return (min(pos.stop, bar.open), "stop")
            if hit_tgt:
                return (target, "target")
        else:
            hit_stop = bar.high >= pos.stop
            hit_tgt = target is not None and bar.low <= target
            if hit_stop:
                return (max(pos.stop, bar.open), "stop")
            if hit_tgt:
                return (target, "target")
        return (None, "")

    def _close(self, pos: Position, exit_price: float, bar: Bar, reason: str) -> Trade:
        spec = self._spec(pos.symbol)
        pv = spec["point_value"]
        direction = 1 if pos.side is Side.LONG else -1

        # Exit slippage: the fill goes against you by `slippage_ticks`.
        slip = self.slippage_ticks * spec["tick"]
        filled_exit = exit_price - slip if pos.side is Side.LONG else exit_price + slip

        gross_points = (filled_exit - pos.entry) * direction
        gross_pnl = gross_points * pv * pos.qty
        commission = spec.get("commission", 0.0) * pos.qty           # round-turn
        # Slippage cost = both legs (entry slip already in pos.entry, exit slip here).
        slippage_cost = (self.slippage_ticks * spec["tick"]) * pv * pos.qty * 2
        pnl = gross_pnl - commission

        self._equity += pnl
        self.total_commission += commission
        self.total_slippage += slippage_cost

        risk_points = abs(pos.entry - pos.stop)
        r = (gross_points / risk_points) if risk_points else 0.0
        return Trade(
            symbol=pos.symbol, side=pos.side, qty=pos.qty, entry=round(pos.entry, 2),
            exit=round(filled_exit, 2), opened_ts=pos.opened_ts, closed_ts=bar.ts,
            pnl=round(pnl, 2), r_multiple=round(r, 2), reason=reason, tag=pos.tag,
            gross_pnl=round(gross_pnl, 2), commission=round(commission, 2),
            slippage_cost=round(slippage_cost, 2),
        )
