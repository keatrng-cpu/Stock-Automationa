"""Pure parsers for Tradovate payloads -> our domain models.

These are isolated and unit-tested offline (no network), because they're the part
most likely to be subtly wrong against the documented schema. The WebSocket/REST
plumbing that *feeds* them must still be validated against the Tradovate demo.

Schema references: https://api.tradovate.com/  (md/getChart, fillPair/list)
"""
from __future__ import annotations

from datetime import datetime

from ..models import CONTRACTS, Bar, Side, Trade

# Tradovate symbols carry an expiry suffix (e.g. ESM6). Map root -> our symbol.
_ROOTS = {"ES": "ES", "NQ": "NQ", "MES": "MES", "MNQ": "MNQ"}


def root_symbol(tradovate_symbol: str) -> str:
    """ESM6 -> ES, MNQU6 -> MNQ. Matches the longest known root prefix."""
    for root in sorted(_ROOTS, key=len, reverse=True):
        if tradovate_symbol.upper().startswith(root):
            return root
    return tradovate_symbol


def _parse_ts(ts) -> datetime:
    if isinstance(ts, (int, float)):           # epoch millis
        return datetime.utcfromtimestamp(ts / 1000.0)
    s = str(ts).replace("Z", "+00:00")
    return datetime.fromisoformat(s).replace(tzinfo=None)


def parse_chart_bars(packet: dict, symbol: str) -> list[Bar]:
    """Parse a Tradovate `md/getChart` chart packet into Bars.

    Expected shape: {"charts": [{"id":.., "bars": [{timestamp, open, high, low,
    close, upVolume, downVolume, ...}]}]}. Volume = upVolume + downVolume.
    """
    out: list[Bar] = []
    charts = packet.get("charts") or packet.get("d", {}).get("charts") or []
    for chart in charts:
        for b in chart.get("bars", []):
            vol = float(b.get("upVolume", 0)) + float(b.get("downVolume", 0))
            if "volume" in b:
                vol = float(b["volume"])
            out.append(Bar(
                ts=_parse_ts(b["timestamp"]),
                open=float(b["open"]), high=float(b["high"]),
                low=float(b["low"]), close=float(b["close"]),
                volume=vol, symbol=symbol,
            ))
    out.sort(key=lambda x: x.ts)
    return out


def parse_fill_pairs(pairs: list[dict], contract_symbol: dict[int, str]) -> list[Trade]:
    """Parse Tradovate `fillPair/list` entries into closed Trades.

    A fillPair matches an entry and exit fill. `contract_symbol` maps contractId ->
    our symbol (e.g. {12345: "MES"}). P&L = (sell - buy) * qty * point_value.
    Only inactive (closed) pairs become Trades.
    """
    out: list[Trade] = []
    for p in pairs:
        if p.get("active", False):             # still open — skip
            continue
        cid = p.get("contractId")
        symbol = contract_symbol.get(cid, "ES")
        pv = CONTRACTS.get(symbol, {"point_value": 1.0})["point_value"]
        qty = int(p.get("qty", 1))
        buy = float(p.get("buyPrice"))
        sell = float(p.get("sellPrice"))
        pnl = (sell - buy) * qty * pv
        # buyFillId/sellFillId timestamps tell us direction & timing if present.
        opened = _parse_ts(p.get("timestamp")) if p.get("timestamp") else datetime.utcnow()
        # If the buy happened first it was a long; else a short.
        bt, st = p.get("buyFillTimestamp"), p.get("sellFillTimestamp")
        side = Side.LONG
        if bt and st:
            side = Side.LONG if _parse_ts(bt) <= _parse_ts(st) else Side.SHORT
        out.append(Trade(
            symbol=symbol, side=side, qty=qty,
            entry=buy if side is Side.LONG else sell,
            exit=sell if side is Side.LONG else buy,
            opened_ts=opened, closed_ts=opened,
            pnl=round(pnl, 2), r_multiple=0.0,        # R unknown from fills alone
            reason="tradovate-fill", tag=str(p.get("id", "")),
        ))
    return out
