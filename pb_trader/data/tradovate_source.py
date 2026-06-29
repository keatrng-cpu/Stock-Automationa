"""Tradovate market-data source (demo or live), via the chart WebSocket.

History and live bars both come from `md/getChart` over the market-data WS gateway.
The bar PARSING is unit-tested offline (tradovate_parse.parse_chart_bars); the socket
plumbing must be validated against a Tradovate demo account before being trusted.

Requires `pip install pb-trader[tradovate]` and TRADOVATE_* env vars. Market data may
require a market-data subscription on the account — validate entitlements in demo first.
"""
from __future__ import annotations

import queue
from typing import Iterable, Iterator

from ..config import settings
from ..execution.tradovate import TradovateClient
from ..execution.tradovate_parse import parse_chart_bars
from ..execution.tradovate_ws import TradovateSocket
from ..models import Bar

_MD_URL = "wss://md.tradovateapi.com/v1/websocket"
# Tradovate getChart bar units.
_TF_UNITS = {"1m": (1, "MinuteBar"), "5m": (5, "MinuteBar"),
             "1h": (60, "MinuteBar"), "1d": (1, "DailyBar")}


class TradovateSource:
    def __init__(self, client: TradovateClient | None = None):
        self.client = client or TradovateClient()

    def _open_socket(self) -> TradovateSocket:
        self.client.ensure_auth()
        if not self.client.md_token:
            raise RuntimeError("No market-data token from Tradovate auth")
        sock = TradovateSocket(_MD_URL, self.client.md_token)
        sock.connect()
        return sock

    def _chart_body(self, symbol: str, timeframe: str, n_elements: int) -> dict:
        size, unit = _TF_UNITS.get(timeframe, (1, "MinuteBar"))
        return {
            "symbol": symbol,
            "chartDescription": {
                "underlyingType": unit,
                "elementSize": size,
                "elementSizeUnit": "UnderlyingUnits",
            },
            "timeRange": {"asMuchAsElements": n_elements},
        }

    def history(self, symbol: str, start: str | None = None,
                end: str | None = None, timeframe: str = "1m") -> list[Bar]:
        """Pull recent chart bars (up to ~`n` elements). Deeper history needs paging
        with closestTimestamp/asFarAsTimeStamp — extend when validated on demo."""
        bars: list[Bar] = []
        done = queue.Queue()

        def on_frame(frame: dict) -> None:
            d = frame.get("d", frame)
            if isinstance(d, dict) and (d.get("charts") or d.get("bars")):
                bars.extend(parse_chart_bars(d, symbol))
                if d.get("eoh"):              # end-of-history marker
                    done.put(True)

        sock = self._open_socket()
        sock.on_frame = on_frame
        sock.request("md/getChart", body=self._chart_body(symbol, timeframe, 500))
        try:
            done.get(timeout=20)
        except queue.Empty:
            pass
        finally:
            sock.close()
        return bars

    def stream(self, symbols: Iterable[str], timeframe: str = "1m") -> Iterator[Bar]:
        """Yield closed bars live as Tradovate pushes chart updates."""
        out: "queue.Queue[Bar]" = queue.Queue()
        symbols = list(symbols)

        def make_handler(sym: str):
            def on_frame(frame: dict) -> None:
                d = frame.get("d", frame)
                if isinstance(d, dict) and (d.get("charts") or d.get("bars")):
                    for b in parse_chart_bars(d, sym):
                        out.put(b)
            return on_frame

        sockets = []
        for sym in symbols:
            sock = self._open_socket()
            sock.on_frame = make_handler(sym)
            sock.request("md/getChart", body=self._chart_body(sym, timeframe, 1))
            sockets.append(sock)
        try:
            while True:
                yield out.get()
        finally:
            for s in sockets:
                s.close()
