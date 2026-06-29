"""PB Mechanical Model 2.0 orchestrator (PB + ICT/SMC + TJR, condition-aware).

Fuses HTF bias + market conditions + liquidity sweep + LTF iFVG confirmation +
displacement + TJR concepts (MSS, killzone, PO3 daily bias) into a scored A+ setup.
Only setups at/above the confluence threshold are emitted, and only when the market
*condition* itself is tradeable.

Confluence scoring (each component contributes weight toward 1.0):
    HTF structure alignment (BOS/CHOCH).......... 0.18
    Premium/discount alignment................... 0.10
    Liquidity sweep present...................... 0.18
    iFVG inversion + retest...................... 0.18
    Displacement quality......................... 0.08
    TJR market structure shift (MSS)............. 0.10
    TJR killzone / session....................... 0.08
    TJR PO3 daily-bias alignment................. 0.10

Hard gates (independent of score): market conditions must be tradeable and we must
not be inside a news blackout — otherwise stand aside regardless of pattern quality.
"""
from __future__ import annotations

from typing import Optional

from ..models import Bar, Direction, Setup, Side
from .conditions import MarketConditions, NewsCalendar, assess_conditions
from .fib import ote_check
from .fvg import active_ifvgs, detect_fvgs, update_fvg_states
from .htf import htf_bias
from .liquidity import build_pools, detect_sweep, next_liquidity
from .order_blocks import order_blocks_from_fvgs, retesting_block, update_block_states
from .structure import StructureState, find_swings, premium_discount
from .tjr import DailyPO3, current_killzone, detect_mss

# SMC-grade confluence stack (sums to 1.0). Top-down: HTF bias is weighted heavily
# and also gates entries; entry-zone quality stacks iFVG + order block + OTE.
WEIGHTS = {
    "structure": 0.15,    # LTF BOS/CHOCH aligned
    "htf_bias": 0.15,     # higher-timeframe bias aligned (top-down)
    "pd": 0.08,           # premium/discount of the dealing range
    "sweep": 0.15,        # liquidity raid
    "ifvg": 0.15,         # inverted FVG retest
    "order_block": 0.07,  # fresh order block retest
    "ote": 0.07,          # optimal trade entry (0.62-0.79 fib)
    "displacement": 0.06,
    "mss": 0.06,          # TJR market structure shift
    "killzone": 0.03,
    "daily_bias": 0.03,   # TJR PO3 daily bias
}


class PBModel:
    """Stateful, bar-by-bar evaluator for a single instrument."""

    def __init__(self, symbol: str, confluence_threshold: float = 0.75,
                 swing_k: int = 2, displacement_mult: float = 1.5,
                 require_killzone: bool = False,
                 news: Optional[NewsCalendar] = None,
                 max_history: int = 800,
                 htf_minutes: int = 15,
                 require_htf_alignment: bool = True):
        self.symbol = symbol
        self.threshold = confluence_threshold
        self.swing_k = swing_k
        self.displacement_mult = displacement_mult
        self.max_history = max_history
        self.require_killzone = require_killzone
        self.news = news or NewsCalendar()
        self.htf_minutes = htf_minutes
        self.require_htf_alignment = require_htf_alignment
        self.bars: list[Bar] = []
        self.struct = StructureState()
        self.po3 = DailyPO3()
        self.fvgs: list = []
        self.blocks: list = []
        self.htf_trend: Optional[Direction] = None
        self.pools: list = []
        self.conditions: Optional[MarketConditions] = None
        self._recent_sweep = None
        self._sweep_age = 0

    def _displacement(self) -> float:
        """How strongly the last bar moved vs recent average range (0..1 quality)."""
        if len(self.bars) < 12:
            return 0.0
        avg = sum(b.range for b in self.bars[-11:-1]) / 10.0
        if avg == 0:
            return 0.0
        ratio = self.bars[-1].range / avg
        return max(0.0, min(1.0, (ratio - 1.0) / (self.displacement_mult - 1.0)))

    def on_bar(self, bar: Bar) -> Optional[Setup]:
        self.bars.append(bar)
        self.po3.update(bar)
        # Bound history to keep per-bar cost ~constant (structure only needs recent bars).
        # Safe: swings/FVGs are recomputed each bar, so trimming can't corrupt state.
        if len(self.bars) > self.max_history:
            self.bars = self.bars[-self.max_history:]
        i = len(self.bars) - 1
        if i < 3 * self.swing_k + 5:
            return None

        # ---- Hard condition gates (PB: read the condition before the setup) ----
        self.conditions = assess_conditions(self.bars)
        if not self.conditions.tradeable:
            return None
        if self.news.in_blackout(bar.ts):
            return None
        if self.require_killzone and current_killzone(bar.ts) is None:
            return None

        # ---- Top-down: higher-timeframe bias (core SMC) ----
        self.htf_trend = htf_bias(self.bars, self.htf_minutes, self.swing_k)

        # Refresh structure, FVGs, order blocks, liquidity pools.
        swings = find_swings(self.bars, self.swing_k)
        self.struct.update(swings, bar, i)
        self.fvgs = detect_fvgs(self.bars)
        for f in self.fvgs:
            update_fvg_states([f], bar)
        self.blocks = order_blocks_from_fvgs(self.bars, self.fvgs)
        update_block_states(self.blocks, bar)
        self.pools = build_pools(swings)

        sweep = detect_sweep(self.pools, bar)
        if sweep:
            self._recent_sweep = sweep
            self._sweep_age = 0
        elif self._recent_sweep:
            self._sweep_age += 1
            if self._sweep_age > 10:       # sweep edge decays
                self._recent_sweep = None

        return self._evaluate(bar, i)

    def _evaluate(self, bar: Bar, i: int) -> Optional[Setup]:
        trend = self.struct.trend
        if trend is None:
            return None

        # Top-down gate: don't fight a decided higher-timeframe bias.
        if self.require_htf_alignment and self.htf_trend is not None \
                and self.htf_trend != trend:
            return None

        lo, eq, hi = premium_discount(self.bars)
        ifvgs = active_ifvgs(self.fvgs)
        if not ifvgs:
            return None

        # Score every aligned iFVG being retested; keep only the BEST candidate so we
        # always hand the user the single highest-probability A+ setup, never the first.
        best: Optional[Setup] = None
        for f in ifvgs:
            aligned = f.direction == trend
            retesting = f.contains(bar.close) or f.contains(bar.low) or f.contains(bar.high)
            if not (aligned and retesting):
                continue

            score = 0.0
            reasons: list[str] = []

            score += WEIGHTS["structure"]
            reasons.append(f"HTF structure {trend.value} (last event aligns)")

            in_discount = bar.close < eq
            if (trend is Direction.BULL and in_discount) or (trend is Direction.BEAR and not in_discount):
                score += WEIGHTS["pd"]
                reasons.append("price in " + ("discount" if in_discount else "premium") + " — aligned")

            if self._recent_sweep is not None:
                score += WEIGHTS["sweep"]
                reasons.append(f"liquidity sweep: {self._recent_sweep.kind} @ {self._recent_sweep.price:.2f}")

            score += WEIGHTS["ifvg"]
            reasons.append(f"iFVG retest [{f.bottom:.2f}, {f.top:.2f}]")

            # HTF bias alignment (top-down confluence).
            if self.htf_trend is not None and self.htf_trend == trend:
                score += WEIGHTS["htf_bias"]
                reasons.append(f"HTF({self.htf_minutes}m) bias {trend.value} aligned")

            # Order block: entry coincides with a fresh, aligned demand/supply block.
            if retesting_block(self.blocks, trend, bar):
                score += WEIGHTS["order_block"]
                reasons.append("fresh order block retest")

            # OTE: entry sits in the 0.62-0.79 retracement of the leg.
            side_for_ote = Side.LONG if trend is Direction.BULL else Side.SHORT
            entry_price = f.top if trend is Direction.BULL else f.bottom
            if ote_check(self.bars, entry_price, side_for_ote, self.swing_k):
                score += WEIGHTS["ote"]
                reasons.append("OTE zone (0.62-0.79 fib)")

            dq = self._displacement()
            score += WEIGHTS["displacement"] * dq
            reasons.append(f"displacement quality {dq:.0%}")

            # TJR: Market Structure Shift on the entry timeframe, aligned to trend.
            mss = detect_mss(self.bars, self.swing_k)
            if mss is not None and mss == trend:
                score += WEIGHTS["mss"]
                reasons.append(f"TJR MSS confirms {trend.value}")

            # TJR: inside a high-probability killzone/session.
            kz = current_killzone(bar.ts)
            if kz is not None:
                score += WEIGHTS["killzone"]
                reasons.append(f"killzone: {kz}")

            # TJR: PO3 daily bias (from the manipulation/judas sweep) agrees.
            if self.po3.bias_aligns(trend):
                score += WEIGHTS["daily_bias"]
                reasons.append(f"PO3 daily bias {self.po3.bias.value} aligned")

            # Add the live condition read to the rationale.
            if self.conditions:
                reasons.append("conditions: " + "; ".join(self.conditions.reasons[:1]))

            # Hard gate: never below the 75% A+ threshold.
            if score < self.threshold:
                continue

            candidate = self._build_setup(bar, f, trend, score, reasons)
            if best is None or candidate.confluence > best.confluence:
                best = candidate
        return best

    def _build_setup(self, bar: Bar, f, trend: Direction, score: float,
                     reasons: list[str]) -> Setup:
        if trend is Direction.BULL:
            side = Side.LONG
            entry = f.top                       # retest of inverted gap as support
            stop = min(f.bottom, bar.low) - 0.25
            tgt_pool = next_liquidity(self.pools, entry, "up")
            t1 = entry + 2 * (entry - stop)
            targets = [tgt_pool.price] if tgt_pool else [t1]
            if not targets or targets[0] <= entry:
                targets = [t1]
        else:
            side = Side.SHORT
            entry = f.bottom
            stop = max(f.top, bar.high) + 0.25
            tgt_pool = next_liquidity(self.pools, entry, "down")
            t1 = entry - 2 * (stop - entry)
            targets = [tgt_pool.price] if tgt_pool else [t1]
            if not targets or targets[0] >= entry:
                targets = [t1]

        return Setup(
            symbol=self.symbol, side=side, entry=round(entry, 2),
            stop=round(stop, 2), targets=[round(t, 2) for t in targets],
            ts=bar.ts, confluence=round(score, 3), reasons=reasons,
            session=_session_of(bar.ts),
        )


def _session_of(ts) -> str:
    """Rough NY-time session bucket (assumes bar ts already in exchange tz)."""
    h = ts.hour
    if 9 <= h < 11:
        return "NY Open"
    if 11 <= h < 13:
        return "NY Lunch"
    if 13 <= h < 16:
        return "NY PM"
    if 3 <= h < 9:
        return "London"
    return "Asia/Overnight"
