"""Load bars from CSV files: columns ts,open,high,low,close,volume."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from ..models import Bar


class CSVSource:
    def __init__(self, directory: str = "data_cache"):
        self.directory = Path(directory)

    def _path(self, symbol: str) -> Path:
        return self.directory / f"{symbol}.csv"

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        path = self._path(symbol)
        if not path.exists():
            raise FileNotFoundError(f"no CSV for {symbol} at {path}")
        out: list[Bar] = []
        with open(path) as fh:
            for row in csv.DictReader(fh):
                ts = datetime.fromisoformat(row["ts"])
                if start and ts < datetime.fromisoformat(start):
                    continue
                if end and ts > datetime.fromisoformat(end):
                    continue
                out.append(Bar(ts, float(row["open"]), float(row["high"]),
                               float(row["low"]), float(row["close"]),
                               float(row.get("volume", 0)), symbol))
        return out

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        series = {s: self.history(s) for s in symbols}
        n = min(len(v) for v in series.values())
        for i in range(n):
            for s in symbols:
                yield series[s][i]
