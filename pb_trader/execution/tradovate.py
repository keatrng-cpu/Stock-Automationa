"""Tradovate execution adapter (REST). Demo by default; live is explicitly gated.

Auth flow (https://api.tradovate.com/):
  POST /auth/accessTokenRequest  -> accessToken (+ md token)
Orders:
  POST /order/placeOrder         -> place a market/limit order
  POST /order/placeOSO           -> order-sends-order (entry + bracket)

This adapter is intentionally conservative: it will REFUSE to place live orders
unless settings.live_enabled is true (PB_MODE=live AND full creds present).
Run everything in TRADOVATE_ENV=demo until you have paper-validated the strategy.
"""
from __future__ import annotations

from ..config import settings
from ..models import Bar, Order, OrderType, Position, Side, Trade

_BASE = {
    "demo": "https://demo.tradovateapi.com/v1",
    "live": "https://live.tradovateapi.com/v1",
}


class TradovateClient:
    """Thin REST client handling auth + token caching."""

    def __init__(self):
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ImportError("Run: pip install pb-trader[tradovate]") from e
        self._requests = requests
        self.base = _BASE.get(settings.tradovate_env, _BASE["demo"])
        self.access_token: str | None = None
        self.md_token: str | None = None
        self.account_id: int | None = None

    def ensure_auth(self) -> None:
        if self.access_token:
            return
        if not settings.tradovate_configured:
            raise RuntimeError(
                "Tradovate credentials missing. Fill TRADOVATE_* in .env "
                "(start with TRADOVATE_ENV=demo)."
            )
        payload = {
            "name": settings.tradovate_username,
            "password": settings.tradovate_password,
            "appId": settings.tradovate_app_id,
            "appVersion": settings.tradovate_app_version,
            "cid": settings.tradovate_cid,
            "sec": settings.tradovate_secret,
            "deviceId": settings.tradovate_device_id,
        }
        resp = self._requests.post(f"{self.base}/auth/accessTokenRequest",
                                   json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data.get("accessToken")
        self.md_token = data.get("mdAccessToken")
        if not self.access_token:
            raise RuntimeError(f"Tradovate auth failed: {data}")
        self._load_account()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _load_account(self) -> None:
        resp = self._requests.get(f"{self.base}/account/list",
                                  headers=self._headers(), timeout=15)
        resp.raise_for_status()
        accts = resp.json()
        if accts:
            self.account_id = accts[0]["id"]

    def get(self, path: str) -> list | dict:
        """GET a REST endpoint (e.g. /fillPair/list)."""
        self.ensure_auth()
        resp = self._requests.get(f"{self.base}{path}",
                                  headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def place_oso(self, symbol: str, side: Side, qty: int, stop: float,
                  target: float) -> dict:
        """Place an entry market order with attached stop + target (bracket)."""
        self.ensure_auth()
        action = "Buy" if side is Side.LONG else "Sell"
        opp = "Sell" if side is Side.LONG else "Buy"
        body = {
            "accountId": self.account_id,
            "accountSpec": settings.tradovate_username,
            "symbol": symbol,
            "orderQty": qty,
            "action": action,
            "orderType": "Market",
            "isAutomated": True,
            "bracket1": {"action": opp, "orderType": "Stop", "stopPrice": stop},
            "bracket2": {"action": opp, "orderType": "Limit", "price": target},
        }
        resp = self._requests.post(f"{self.base}/order/placeOSO",
                                   json=body, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()


class TradovateBroker:
    """Broker interface backed by Tradovate. Live orders are hard-gated."""

    def __init__(self, client: TradovateClient | None = None):
        self.client = client or TradovateClient()
        self.positions: list[Position] = []
        self._seen_pairs: set = set()        # fillPair ids already turned into Trades
        self._contract_symbol: dict = {}     # contractId -> our symbol (from placed orders)

    @property
    def equity(self) -> float:
        # TODO: pull real cashBalance via /cashBalance/getCashBalanceSnapshot
        return settings.account_equity

    def open_positions(self) -> list[Position]:
        return list(self.positions)

    def submit(self, order: Order) -> Position | None:
        if not settings.live_enabled:
            raise PermissionError(
                "Live trading is OFF. Set PB_MODE=live with full Tradovate creds to "
                "enable real orders. (Paper-validate first — this guard is intentional.)"
            )
        target = order.targets[0] if order.targets else None
        if order.stop is None or target is None:
            raise ValueError("Tradovate bracket requires both stop and target")
        result = self.client.place_oso(order.symbol, order.side, order.qty,
                                       order.stop, target)
        pos = Position(order.symbol, order.side, order.qty,
                       entry=order.price or 0.0, stop=order.stop,
                       targets=list(order.targets), opened_ts=None, tag=str(result.get("orderId", "")))
        self.positions.append(pos)
        return pos

    def on_bar(self, bar: Bar) -> list[Trade]:
        # Tradovate manages bracket exits server-side, so detect closes by polling
        # matched fill pairs and emitting a Trade for each newly-closed pair.
        return self.reconcile_fills()

    def reconcile_fills(self) -> list[Trade]:
        """Fetch closed fill pairs and return any not yet seen as Trades."""
        from .tradovate_parse import parse_fill_pairs
        try:
            pairs = self.client.get("/fillPair/list")
        except Exception:  # noqa: BLE001 — network/poll errors shouldn't crash the loop
            return []
        fresh = [p for p in pairs if not p.get("active", False)
                 and p.get("id") not in self._seen_pairs]
        for p in fresh:
            self._seen_pairs.add(p.get("id"))
        return parse_fill_pairs(fresh, self._contract_symbol)
