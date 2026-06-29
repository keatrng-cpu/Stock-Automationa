"""Broker protocol."""
from __future__ import annotations

from typing import Protocol

from ..models import Bar, Order, Position, Trade


class Broker(Protocol):
    def submit(self, order: Order) -> Position | None:
        """Place a bracket order (entry + stop + targets). Returns the open position."""
        ...

    def on_bar(self, bar: Bar) -> list[Trade]:
        """Feed a new bar; returns any trades closed by stop/target this bar."""
        ...

    def open_positions(self) -> list[Position]:
        ...

    @property
    def equity(self) -> float:
        ...
