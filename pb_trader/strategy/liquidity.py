"""Liquidity engineering: BSL/SSL pools, EQH/EQL, and sweep detection."""
from __future__ import annotations

from ..models import Bar, LiquidityPool, SwingPoint


def build_pools(swings: list[SwingPoint], eq_tol: float = 1.0) -> list[LiquidityPool]:
    """Buy-side liquidity rests above swing highs, sell-side below swing lows.

    Clusters of near-equal highs/lows (within `eq_tol`) are tagged EQH/EQL — the
    juiciest resting liquidity for a PB sweep.
    """
    pools: list[LiquidityPool] = []
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]

    for s in highs:
        kind = "EQH" if any(abs(s.price - o.price) <= eq_tol and s.index != o.index
                            for o in highs) else "BSL"
        pools.append(LiquidityPool(s.price, kind, s.ts))
    for s in lows:
        kind = "EQL" if any(abs(s.price - o.price) <= eq_tol and s.index != o.index
                            for o in lows) else "SSL"
        pools.append(LiquidityPool(s.price, kind, s.ts))
    return pools


def detect_sweep(pools: list[LiquidityPool], bar: Bar):
    """A sweep = wick takes liquidity beyond a pool but the candle closes back inside.

    Returns the swept pool (and marks it) or None. This is the PB trigger: the raid,
    not the breakout.
    """
    for p in pools:
        if p.swept:
            continue
        if p.kind in ("BSL", "EQH"):
            if bar.high > p.price and bar.close < p.price:
                p.swept = True
                return p
        else:  # SSL / EQL
            if bar.low < p.price and bar.close > p.price:
                p.swept = True
                return p
    return None


def next_liquidity(pools: list[LiquidityPool], price: float, direction: str):
    """Nearest unswept pool in the trade direction — the logical first target."""
    if direction == "up":
        cands = [p for p in pools if not p.swept and p.price > price]
        return min(cands, key=lambda p: p.price - price) if cands else None
    cands = [p for p in pools if not p.swept and p.price < price]
    return max(cands, key=lambda p: p.price) if cands else None
