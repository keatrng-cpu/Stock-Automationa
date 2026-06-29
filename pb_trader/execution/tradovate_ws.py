"""Minimal Tradovate WebSocket client (framing + auth + heartbeat).

Tradovate's WS uses a custom text framing on top of the socket:
  - server 'o'                     -> socket opened
  - server 'h'                     -> heartbeat (and client must send '[]' ~every 2.5s)
  - server 'a[ ...json... ]'       -> array of frames (responses + events)
  - server 'c[code,"reason"]'      -> closed
  - client request                 -> "<endpoint>\n<id>\n<query>\n<body-json>"
  - client auth                    -> "authorize\n<id>\n\n<accessToken>"

Gateways:
  - trading/user : wss://{demo|live}.tradovateapi.com/v1/websocket
  - market data  : wss://md.tradovateapi.com/v1/websocket   (use the mdAccessToken)

⚠️ NOT yet validated against a live Tradovate demo socket — the framing follows the
documented protocol but must be confirmed end-to-end before being trusted with money.
Requires: pip install 'pb-trader[tradovate]' (websocket-client).
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional


class TradovateSocket:
    def __init__(self, url: str, token: str,
                 on_frame: Optional[Callable[[dict], None]] = None):
        try:
            import websocket  # websocket-client
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install 'pb-trader[tradovate]'") from e
        self._wsmod = websocket
        self.url = url
        self.token = token
        self.on_frame = on_frame or (lambda f: None)
        self.ws = None
        self._req_id = 0
        self._authorized = threading.Event()
        self._hb_stop = threading.Event()
        self._lock = threading.Lock()

    # ---- lifecycle ----
    def connect(self, timeout: float = 10.0) -> None:
        self.ws = self._wsmod.create_connection(self.url, timeout=timeout)
        # First server frame should be 'o'.
        self._pump_once()
        self._send_raw(f"authorize\n{self._next_id()}\n\n{self.token}")
        threading.Thread(target=self._heartbeat, daemon=True).start()
        threading.Thread(target=self._reader, daemon=True).start()
        if not self._authorized.wait(timeout):
            raise TimeoutError("Tradovate WS authorize timed out")

    def close(self) -> None:
        self._hb_stop.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass

    # ---- requests ----
    def request(self, endpoint: str, query: str = "", body: Optional[dict] = None) -> int:
        rid = self._next_id()
        payload = f"{endpoint}\n{rid}\n{query}\n{json.dumps(body) if body else ''}"
        self._send_raw(payload)
        return rid

    # ---- internals ----
    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _send_raw(self, text: str) -> None:
        self.ws.send(text)

    def _heartbeat(self) -> None:
        while not self._hb_stop.is_set():
            try:
                self._send_raw("[]")
            except Exception:  # noqa: BLE001
                return
            time.sleep(2.5)

    def _reader(self) -> None:
        while not self._hb_stop.is_set():
            try:
                self._pump_once()
            except Exception:  # noqa: BLE001
                return

    def _pump_once(self) -> None:
        msg = self.ws.recv()
        if not msg:
            return
        kind, body = msg[0], msg[1:]
        if kind == "o":
            return
        if kind == "h":
            return
        if kind == "c":
            self._hb_stop.set()
            return
        if kind == "a":
            for frame in json.loads(body):
                # The authorize response has status 200 and the original request id.
                if isinstance(frame, dict):
                    if frame.get("s") == 200 and not self._authorized.is_set():
                        self._authorized.set()
                    self.on_frame(frame)
