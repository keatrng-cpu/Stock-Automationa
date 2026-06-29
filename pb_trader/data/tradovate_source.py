"""Tradovate market-data source (demo or live).

Tradovate exposes REST for auth/history and a WebSocket for live quotes/charts.
Requires `pip install pb-trader[tradovate]` and TRADOVATE_* env vars.
Docs: https://api.tradovate.com/

NOTE: Tradovate market data may require a market-data subscription on your account.
Validate entitlements in the DEMO environment first.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator

from ..config import settings
from ..execution.tradovate import TradovateClient
from ..models import Bar


class TradovateSource:
    def __init__(self, client: TradovateClient | None = None):
        self.client = client or TradovateClient()

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        """Pull chart bars via Tradovate's getChart endpoint.

        TODO: map `timeframe` to Tradovate chart units (e.g. {underlyingType:'MinuteBar'})
        and paginate. Stubbed here until your demo credentials are connected.
        """
        self.client.ensure_auth()
        raise NotImplementedError(
            "Tradovate history wiring is stubbed. Use Databento for backtests; "
            "connect demo creds to enable live Tradovate charts."
        )

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        """Subscribe to Tradovate chart WebSocket and yield closed bars.

        TODO: implement md/subscribeQuote + chart subscription over the WS gateway.
        """
        self.client.ensure_auth()
        raise NotImplementedError(
            "Tradovate live stream is stubbed pending demo-credential validation."
        )
