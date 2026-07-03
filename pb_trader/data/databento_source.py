"""Databento data source — institutional CME (GLBX.MDP3) data for ES/NQ.

Requires `pip install 'pb-trader[databento]'` and DATABENTO_API_KEY in your env/.env.
Docs: https://databento.com/docs

Databento only publishes a few native OHLCV schemas — `ohlcv-1s`, `ohlcv-1m`, `ohlcv-1h`,
`ohlcv-1d`. There is NO native 5m/15m/etc., so this source fetches the finest sensible
NATIVE schema and RESAMPLES up to whatever ladder timeframe you asked for (1m→15m, 1s→30s).
That way `--timeframe 15m --source databento` just works on real data.

ES/NQ are continuous front-month futures; we request the front contract via `continuous`
symbology (e.g. "ES.c.0"). Prices come back as floats via `to_df()` (robust across versions).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

from ..config import settings
from ..models import Bar
from ..strategy.htf import resample
from ..timeframes import parse_tf

# Map our short symbols to Databento continuous front-month parents.
_SYMBOL = {"ES": "ES.c.0", "NQ": "NQ.c.0", "MES": "MES.c.0", "MNQ": "MNQ.c.0"}


def _resample_secs(bars: list[Bar], secs: int) -> list[Bar]:
    """Aggregate second-level bars into `secs`-second OHLCV candles (for sub-minute TFs)."""
    if not bars:
        return []
    out: list[Bar] = []
    bucket = None
    ts0 = bars[0].ts
    o = h = l = c = v = 0.0
    for b in bars:
        bk = int(b.ts.timestamp()) // secs
        if bk != bucket:
            if bucket is not None:
                out.append(Bar(ts0, o, h, l, c, v, bars[0].symbol))
            bucket = bk
            ts0, o, h, l, c, v = b.ts, b.open, b.high, b.low, b.close, b.volume
        else:
            h, l, c, v = max(h, b.high), min(l, b.low), b.close, v + b.volume
    out.append(Bar(ts0, o, h, l, c, v, bars[0].symbol))
    return out


class DatabentoSource:
    def __init__(self, api_key: str | None = None, dataset: str | None = None, **_ignore):
        try:
            import databento as db  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "databento not installed. Run: pip install 'pb-trader[databento]'"
            ) from e
        self._db = db
        self.api_key = api_key or settings.databento_api_key
        self.dataset = dataset or settings.databento_dataset
        if not self.api_key:
            raise RuntimeError("DATABENTO_API_KEY not set — add it to your .env")
        self.client = db.Historical(self.api_key)

    @staticmethod
    def _native_schema(timeframe: str) -> tuple[str, int]:
        """Pick the native Databento schema to fetch, and the target seconds to resample to."""
        secs = parse_tf(timeframe)
        return ("ohlcv-1s", secs) if secs < 60 else ("ohlcv-1m", secs)

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        # Default to a recent window so a bare command works (last ~10 days).
        if end is None:
            end = datetime.now(timezone.utc).date().isoformat()
        if start is None:
            start = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()

        schema, secs = self._native_schema(timeframe)
        ds_symbol = _SYMBOL.get(symbol, symbol)
        data = self.client.timeseries.get_range(
            dataset=self.dataset,
            symbols=[ds_symbol],
            schema=schema,
            stype_in="continuous",
            start=start,
            end=end,
        )
        # to_df() returns float prices (pretty_px) and a UTC Timestamp index — version-stable.
        df = data.to_df()
        native: list[Bar] = []
        for ts, row in df.iterrows():
            native.append(Bar(
                ts=ts.to_pydatetime().replace(tzinfo=None),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]), symbol=symbol,
            ))
        # Resample the native bars up to the requested ladder timeframe.
        if secs == 60:
            return native                       # native 1m already
        if secs < 60:
            return _resample_secs(native, secs)
        return resample(native, secs // 60)     # minutes

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        """Live stream via the Databento Live gateway (native 1s/1m).

        Yields native bars; the engine's own resampling (HTF bias, MTF) handles higher
        timeframes. Validate against your live entitlement before relying on it.
        """
        schema, _secs = self._native_schema(timeframe)
        live = self._db.Live(self.api_key)
        live.subscribe(
            dataset=self.dataset,
            schema=schema,
            stype_in="continuous",
            symbols=[_SYMBOL.get(s, s) for s in symbols],
        )
        rev = {v: k for k, v in _SYMBOL.items()}
        for rec in live:
            if not hasattr(rec, "close"):
                continue
            sym = rev.get(getattr(rec, "symbol", ""), getattr(rec, "symbol", ""))
            # Databento raw OHLCV prices are fixed-point in units of 1e-9 dollars.
            px = 1e-9
            yield Bar(
                ts=datetime.utcfromtimestamp(rec.ts_event / 1e9),
                open=rec.open * px, high=rec.high * px, low=rec.low * px,
                close=rec.close * px, volume=float(rec.volume), symbol=sym,
            )
