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

# Micros track the same price as their full-size underlying, so positions on a micro
# contract must be filled/exited against the underlying's bars.
_UNDERLYING = {"MES": "ES", "MNQ": "NQ", "ES": "ES", "NQ": "NQ"}


def _price_key(symbol: str) -> str:
    return _UNDERLYING.get(symbol, symbol)


class PaperBroker:
    def __init__(self, equity: float = 10_000.0, slippage_ticks: float = 1.0,
                 manage: bool = True, scale_at_r: float = 1.0,
                 scale_frac: float = 0.5, be_at_r: float = 1.0):
        self._equity = equity
        self.start_equity = equity
        self.slippage_ticks = slippage_ticks
        # Trade management: at scale_at_r bank scale_frac of the position and move the
        # stop to breakeven; let the runner reach the final target (the draw).
        self.manage = manage
        self.scale_at_r = scale_at_r
        self.scale_frac = scale_frac
        self.be_at_r = be_at_r
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
            opened_ts=ts, tag=order.tag, init_qty=order.qty,
            init_risk=abs(entry - order.stop) if order.stop is not None else 0.0,
            features=dict(order.features),
        )
        self.positions.append(pos)
        return pos

    def _point_value(self, symbol: str) -> float:
        return self._spec(symbol)["point_value"]

    def on_bar(self, bar: Bar) -> list[Trade]:
        closed: list[Trade] = []
        still_open: list[Position] = []
        for pos in self.positions:
            if _price_key(pos.symbol) != _price_key(bar.symbol):
                still_open.append(pos)
                continue
            trades, keep = self._manage(pos, bar)
            for t in trades:
                self.trades.append(t)
                closed.append(t)
            if keep:
                still_open.append(pos)
        self.positions = still_open
        return closed

    def _manage(self, pos: Position, bar: Bar):
        """Process one position against a bar. Returns (closed_trades, keep_open).

        Order of events within a bar (pessimistic): stop first, then scale-out, then
        target. Scaling banks part of the position and moves the stop to breakeven.
        """
        trades = []
        long = pos.side is Side.LONG
        risk = pos.init_risk or abs(pos.entry - pos.stop)

        # 1) Stop hit (could be the original stop or the breakeven stop after scaling).
        if (long and bar.low <= pos.stop) or (not long and bar.high >= pos.stop):
            px = min(pos.stop, bar.open) if long else max(pos.stop, bar.open)
            trades.append(self._close(pos, px, bar, "be-stop" if pos.scaled else "stop"))
            return trades, False

        # 2) Scale-out + move to breakeven at scale_at_r (only once, needs >=2 lots).
        if self.manage and not pos.scaled and risk > 0:
            scale_px = pos.entry + self.scale_at_r * risk if long \
                else pos.entry - self.scale_at_r * risk
            reached = bar.high >= scale_px if long else bar.low <= scale_px
            if reached:
                part = int(pos.init_qty * self.scale_frac)
                if part >= 1 and pos.qty - part >= 1:
                    trades.append(self._close(pos, scale_px, bar, "scale", qty=part))
                    pos.qty -= part
                pos.stop = pos.entry          # breakeven on the runner
                pos.scaled = True

        # 3) Final target (the draw) for the remaining size.
        target = pos.targets[0] if pos.targets else None
        if target is not None:
            if (long and bar.high >= target) or (not long and bar.low <= target):
                trades.append(self._close(pos, target, bar, "target"))
                return trades, False

        return trades, True

    def _close(self, pos: Position, exit_price: float, bar: Bar, reason: str,
               qty: int | None = None) -> Trade:
        spec = self._spec(pos.symbol)
        pv = spec["point_value"]
        direction = 1 if pos.side is Side.LONG else -1
        close_qty = qty if qty is not None else pos.qty

        # Exit slippage: the fill goes against you by `slippage_ticks`.
        slip = self.slippage_ticks * spec["tick"]
        filled_exit = exit_price - slip if pos.side is Side.LONG else exit_price + slip

        gross_points = (filled_exit - pos.entry) * direction
        gross_pnl = gross_points * pv * close_qty
        commission = spec.get("commission", 0.0) * close_qty          # round-turn
        slippage_cost = (self.slippage_ticks * spec["tick"]) * pv * close_qty * 2
        pnl = gross_pnl - commission

        self._equity += pnl
        self.total_commission += commission
        self.total_slippage += slippage_cost

        # R is measured against the ORIGINAL risk (init_risk), so partials/runners
        # report honest R multiples even after the stop moves to breakeven.
        risk_points = pos.init_risk or abs(pos.entry - pos.stop)
        r = (gross_points / risk_points) if risk_points else 0.0
        return Trade(
            symbol=pos.symbol, side=pos.side, qty=close_qty, entry=round(pos.entry, 2),
            exit=round(filled_exit, 2), opened_ts=pos.opened_ts, closed_ts=bar.ts,
            pnl=round(pnl, 2), r_multiple=round(r, 2), reason=reason, tag=pos.tag,
            gross_pnl=round(gross_pnl, 2), commission=round(commission, 2),
            slippage_cost=round(slippage_cost, 2), features=dict(pos.features),
        )
