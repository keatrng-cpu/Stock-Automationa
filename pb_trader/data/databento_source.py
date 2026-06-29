"""Databento data source — institutional CME (GLBX.MDP3) data for ES/NQ.

Requires `pip install pb-trader[databento]` and DATABENTO_API_KEY in your env.
Docs: https://databento.com/docs

ES/NQ are continuous front-month futures. Use the parent symbology (e.g. "ES.FUT")
or a specific contract (e.g. "ESU6"). OHLCV is the `ohlcv-1m` / `ohlcv-1h` schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator

from ..config import settings
from ..models import Bar

_SCHEMA = {"1m": "ohlcv-1m", "5m": "ohlcv-5m", "1h": "ohlcv-1h", "1d": "ohlcv-1d"}
# Map our short symbols to Databento continuous front-month parents.
_SYMBOL = {"ES": "ES.c.0", "NQ": "NQ.c.0", "MES": "MES.c.0", "MNQ": "MNQ.c.0"}


class DatabentoSource:
    def __init__(self, api_key: str | None = None, dataset: str | None = None):
        try:
            import databento as db  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "databento not installed. Run: pip install pb-trader[databento]"
            ) from e
        self._db = db
        self.api_key = api_key or settings.databento_api_key
        self.dataset = dataset or settings.databento_dataset
        if not self.api_key:
            raise RuntimeError("DATABENTO_API_KEY not set — add it to your .env")
        self.client = db.Historical(self.api_key)

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        schema = _SCHEMA.get(timeframe, "ohlcv-1m")
        ds_symbol = _SYMBOL.get(symbol, symbol)
        data = self.client.timeseries.get_range(
            dataset=self.dataset,
            symbols=[ds_symbol],
            schema=schema,
            stype_in="continuous",
            start=start,
            end=end,
        )
        # to_df() returns float prices (pretty_px) and a UTC Timestamp index —
        # the robust, version-stable way to read OHLCV. Databento bundles pandas.
        df = data.to_df()
        out: list[Bar] = []
        for ts, row in df.iterrows():
            out.append(Bar(
                ts=ts.to_pydatetime().replace(tzinfo=None),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]), symbol=symbol,
            ))
        return out

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        """Live stream via Databento Live gateway.

        TODO: validate against your live entitlement before relying on this in paper.
        Until validated, paper-trade off `history()` replays or the Tradovate feed.
        """
        schema = _SCHEMA.get(timeframe, "ohlcv-1m")
        live = self._db.Live(self.api_key)
        live.subscribe(
            dataset=self.dataset,
            schema=schema,
            stype_in="continuous",
            symbols=[_SYMBOL.get(s, s) for s in symbols],
        )
        rev = {v: k for k, v in _SYMBOL.items()}
        for rec in live:
            sym = rev.get(getattr(rec, "symbol", ""), getattr(rec, "symbol", ""))
            if not hasattr(rec, "close"):
                continue
            px = 1e-9
            yield Bar(
                ts=datetime.utcfromtimestamp(rec.ts_event / 1e9),
                open=rec.open * px, high=rec.high * px, low=rec.low * px,
                close=rec.close * px, volume=float(rec.volume), symbol=sym,
            )
