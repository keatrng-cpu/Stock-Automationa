"""Draw on Liquidity (DOL) and IRL/ERL — where price is *drawn to* next.

Core ICT idea: price is always seeking liquidity. Distinguishing liquidity that sits
*inside* the current dealing range (IRL — FVGs, internal pools) from liquidity at the
*edges* (ERL — old highs/lows, equal highs/lows) tells you the true target. The DOL is
the dominant external pool in the trade direction — the logical magnet for the move.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Direction, LiquidityPool


@dataclass
class RangeLiquidity:
    internal: list[LiquidityPool]   # IRL — pools inside the dealing range
    external: list[LiquidityPool]   # ERL — pools at/beyond the range edges


def classify_liquidity(pools: list[LiquidityPool], low: float, high: float) -> RangeLiquidity:
    """Split pools into internal (inside [low, high]) vs external (outside)."""
    irl, erl = [], []
    for p in pools:
        (irl if low <= p.price <= high else erl).append(p)
    return RangeLiquidity(irl, erl)


def draw_on_liquidity(pools: list[LiquidityPool], price: float,
                      direction: Direction) -> Optional[LiquidityPool]:
    """The nearest unswept external pool in the trade direction = the draw/target.

    Bull → nearest buy-side pool above; Bear → nearest sell-side pool below.
    """
    if direction is Direction.BULL:
        cands = [p for p in pools if not p.swept and p.price > price
                 and p.kind in ("BSL", "EQH")]
        return min(cands, key=lambda p: p.price - price) if cands else None
    cands = [p for p in pools if not p.swept and p.price < price
             and p.kind in ("SSL", "EQL")]
    return max(cands, key=lambda p: p.price) if cands else None


def std_dev_projection(sweep_price: float, origin: float, multiple: float) -> float:
    """ICT standard-deviation target: project the manipulation leg by `multiple`.

    leg = |origin - sweep_price|; target = origin +/- multiple*leg in the move's
    direction (origin above sweep ⇒ bullish projection upward).
    """
    leg = abs(origin - sweep_price)
    return origin + multiple * leg if origin >= sweep_price else origin - multiple * leg
