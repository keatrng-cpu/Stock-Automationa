"""Risk management: position sizing and hard risk caps."""
from __future__ import annotations

from dataclasses import dataclass

from .config import MAX_RISK_PCT_CEILING
from .models import CONTRACTS, Setup


@dataclass
class SizedOrder:
    symbol: str
    qty: int
    risk_dollars: float
    stop_points: float
    point_value: float
    note: str = ""


def position_size(setup: Setup, equity: float, risk_pct: float,
                  use_micros: bool = False) -> SizedOrder:
    """Size so that hitting the stop loses ~risk_pct of equity, never more than the ceiling.

    qty = floor( (equity * risk_pct) / (stop_points * point_value) )
    """
    risk_pct = min(risk_pct, MAX_RISK_PCT_CEILING)
    symbol = setup.symbol
    spec = CONTRACTS.get(symbol)
    if spec is None:
        raise ValueError(f"unknown contract {symbol}")

    if use_micros and spec.get("micro") and spec["micro"] != symbol:
        symbol = spec["micro"]
        spec = CONTRACTS[symbol]

    point_value = spec["point_value"]
    stop_points = setup.risk_points
    risk_dollars = equity * risk_pct

    if stop_points <= 0:
        return SizedOrder(symbol, 0, 0.0, 0.0, point_value, "invalid stop distance")

    raw = risk_dollars / (stop_points * point_value)
    qty = int(raw)  # floor — round down to stay under the risk cap

    note = ""
    if qty < 1:
        note = (f"stop too wide for {symbol}: 1 contract risks "
                f"${stop_points * point_value:,.0f} > ${risk_dollars:,.0f} budget. "
                f"Use micros or skip.")
    return SizedOrder(symbol, max(qty, 0), risk_dollars, stop_points, point_value, note)


def validate_setup(setup: Setup, min_rr: float = 2.0) -> tuple[bool, str]:
    """Reject setups that violate non-negotiable rules before they reach execution."""
    if setup.risk_points <= 0:
        return False, "non-positive risk distance"
    if not setup.targets:
        return False, "no target defined"
    if setup.rr(0) < min_rr:
        return False, f"R:R {setup.rr(0):.2f} below {min_rr} minimum"
    return True, "ok"
