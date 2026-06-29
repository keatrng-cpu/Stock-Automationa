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
    def __init__(self, equity: float = 10_000.0):
        self._equity = equity
        self.start_equity = equity
        self.positions: list[Position] = []
        self.trades: list[Trade] = []

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
        pos = Position(
            symbol=order.symbol, side=order.side, qty=order.qty,
            entry=fill_price, stop=order.stop, targets=list(order.targets),
            opened_ts=ts, tag=order.tag,
        )
        self.positions.append(pos)
        return pos

    def _point_value(self, symbol: str) -> float:
        return CONTRACTS.get(symbol, {"point_value": 1.0})["point_value"]

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
        pv = self._point_value(pos.symbol)
        direction = 1 if pos.side is Side.LONG else -1
        points = (exit_price - pos.entry) * direction
        pnl = points * pv * pos.qty
        self._equity += pnl
        risk_points = abs(pos.entry - pos.stop)
        r = (points / risk_points) if risk_points else 0.0
        return Trade(
            symbol=pos.symbol, side=pos.side, qty=pos.qty, entry=pos.entry,
            exit=round(exit_price, 2), opened_ts=pos.opened_ts, closed_ts=bar.ts,
            pnl=round(pnl, 2), r_multiple=round(r, 2), reason=reason, tag=pos.tag,
        )
