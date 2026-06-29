"""Core domain models for the PB trading engine.

Pure dataclasses, no third-party deps, so the whole engine runs offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# Instrument contract specs (full-size + micro).
#   point_value = $ per 1.00 price move; tick = min price increment;
#   commission   = approx round-turn commission+fees per contract (USD, configurable).
CONTRACTS = {
    "ES": {"point_value": 50.0, "tick": 0.25, "micro": "MES", "commission": 4.0},
    "NQ": {"point_value": 20.0, "tick": 0.25, "micro": "MNQ", "commission": 4.0},
    "MES": {"point_value": 5.0, "tick": 0.25, "micro": "MES", "commission": 1.0},
    "MNQ": {"point_value": 2.0, "tick": 0.25, "micro": "MNQ", "commission": 1.0},
}


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class Direction(str, Enum):
    BULL = "bull"
    BEAR = "bear"


@dataclass(frozen=True)
class Bar:
    """A single OHLCV candle."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str

    @property
    def is_bull(self) -> bool:
        return self.close >= self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass
class FVG:
    """Fair Value Gap (3-candle imbalance).

    A bullish FVG spans [bottom, top] where bottom = high of the candle two bars
    back and top = low of the current bar (gap left by displacement up).
    `inverted` flips when price closes through it (iFVG).
    """
    direction: Direction
    top: float
    bottom: float
    ts: datetime
    index: int
    filled: bool = False
    inverted: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class SwingPoint:
    index: int
    ts: datetime
    price: float
    kind: str  # "high" | "low"


@dataclass
class StructureEvent:
    """Break of Structure (BOS) or Change of Character (CHOCH)."""
    index: int
    ts: datetime
    kind: str        # "BOS" | "CHOCH"
    direction: Direction
    level: float


@dataclass
class OrderBlock:
    """Smart-money order block: the last opposing candle before a displacement that
    breaks structure. Price often returns ("mitigates") to it before continuing."""
    direction: Direction       # BULL = demand block (support), BEAR = supply (resistance)
    top: float
    bottom: float
    ts: datetime
    index: int
    mitigated: bool = False
    broken: bool = False       # price closed through it -> flips to a breaker

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class BreakerBlock:
    """A failed order block: once an order block is violated (price closes through it),
    the broken zone flips polarity and acts as support/resistance on the retest."""
    direction: Direction       # the NEW polarity (BULL = now support)
    top: float
    bottom: float
    ts: datetime
    index: int
    tested: bool = False

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class LiquidityVoid:
    """A large single-direction imbalance (oversized displacement) that price tends to
    revisit to rebalance. Wider/stronger than a regular FVG."""
    direction: Direction
    top: float
    bottom: float
    ts: datetime
    index: int
    filled: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class LiquidityPool:
    price: float
    kind: str        # "BSL" | "SSL" | "EQH" | "EQL"
    ts: datetime
    swept: bool = False


@dataclass
class Setup:
    """An A+ trade setup emitted by the PB model."""
    symbol: str
    side: Side
    entry: float
    stop: float
    targets: list[float]
    ts: datetime
    confluence: float                 # 0..1
    reasons: list[str] = field(default_factory=list)
    session: str = ""
    tag: str = ""                     # confluence bucket label, set at decision time

    @property
    def risk_points(self) -> float:
        return abs(self.entry - self.stop)

    def rr(self, target_idx: int = 0) -> float:
        if not self.targets or self.risk_points == 0:
            return 0.0
        reward = abs(self.targets[target_idx] - self.entry)
        return reward / self.risk_points


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass
class Order:
    symbol: str
    side: Side
    qty: int
    type: OrderType
    price: Optional[float] = None     # for limit/stop
    stop: Optional[float] = None
    targets: list[float] = field(default_factory=list)
    tag: str = ""


@dataclass
class Position:
    symbol: str
    side: Side
    qty: int
    entry: float
    stop: float
    targets: list[float]
    opened_ts: datetime
    tag: str = ""


@dataclass
class Trade:
    """A closed round-trip trade. `pnl` is NET of commission + slippage."""
    symbol: str
    side: Side
    qty: int
    entry: float
    exit: float
    opened_ts: datetime
    closed_ts: datetime
    pnl: float
    r_multiple: float
    reason: str = ""
    tag: str = ""
    gross_pnl: float = 0.0
    commission: float = 0.0
    slippage_cost: float = 0.0
