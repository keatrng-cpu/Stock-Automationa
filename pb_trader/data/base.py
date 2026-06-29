"""Data source protocol."""
from __future__ import annotations

from typing import Iterable, Iterator, Protocol

from ..models import Bar


class DataSource(Protocol):
    """Any source that can yield historical and/or live bars for a symbol."""

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        """Return historical bars (oldest first)."""
        ...

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        """Yield live bars as they close (for paper/live loops)."""
        ...
