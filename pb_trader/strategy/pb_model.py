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

from ..models import CONTRACTS, Bar, Direction, Setup, Side
from .conditions import MarketConditions, NewsCalendar, assess_conditions
from .fib import in_ote
from .fvg import active_ifvgs, new_fvg, update_fvg_states
from .htf import _bucket, htf_bias, htf_fvgs, in_htf_fvg
from .macros import current_macro
from .liquidity import build_pools, detect_sweep, next_liquidity
from .liquidity_draw import draw_on_liquidity
from .order_blocks import (flip_broken_blocks, order_block_at_formation,
                           retesting_block, retesting_breaker, retesting_propulsion,
                           update_block_states)
from .pd_arrays import consequent_encroachment, detect_bpr, in_bpr
from .sessions import SessionTracker
from .structure import (StructureState, detect_cisd, detect_rejection_block,
                        find_swings, premium_discount)
from .tjr import DailyPO3, current_killzone, detect_mss
from .voids import nearest_unfilled_void, new_vacuum, new_void, update_void_states

# SMC-grade confluence stack (sums to 1.0). Top-down: the primary HTF bias is weighted
# heavily and also gates entries; entry-zone quality stacks iFVG + order block +
# breaker + OTE; a second HTF and liquidity void add higher-order confluence.
# Relative confluence weights — auto-normalized to sum to 1.0 (so concepts can be added
# without hand-tuning). PB Mechanical Model core + the price action it acts on are heaviest.
_RAW_WEIGHTS = {
    "mechanical_model": 8,    # the PB sequence fired IN ORDER (sweep→displ-inv→retest)
    "structure": 8,           # LTF BOS/CHOCH aligned
    "htf_bias": 8,            # primary higher-timeframe bias aligned (top-down)
    "sweep": 8,               # liquidity raid
    "ifvg": 8,                # inverted FVG retest
    "htf2_bias": 4,           # second (slower) HTF agrees
    "htf_fvg_nest": 4,        # LTF entry nests inside an HTF FVG (PD-array confluence)
    "sweep_significant": 4,   # the raid took SIGNIFICANT liquidity (PDH/PDL/session)
    "weekly_pd": 4,           # weekly premium/discount + PWH/PWL/PMH/PML draws aligned
    "order_block": 4,         # fresh order block retest
    "ote": 4,                 # optimal trade entry (fib retracement)
    "cisd": 4,                # change in state of delivery confirmation
    "displacement": 4,        # aggressive displacement (PB)
    "mss": 4,                 # TJR market structure shift
    "opening_bias": 4,        # price vs true day open aligns
    "pd": 3,                  # premium/discount of the dealing range
    "sponsored": 3,           # the FVG is sponsored (institutional volume) — PB
    "breaker": 3,             # breaker block retest
    "bpr": 3,                 # entry sits in a balanced price range
    "rejection": 3,           # rejection block (long-wick rejection) aligned
    "propulsion": 3,          # stacked order blocks propelling the move (ICT)
    "daily_bias": 3,          # TJR PO3 daily bias
    "void": 2,                # unfilled liquidity void in trade direction
    "vacuum": 2,              # vacuum block (price gap) to be rebalanced
    "killzone": 2,
    "macro": 2,               # inside an ICT macro window
}
_W_TOTAL = sum(_RAW_WEIGHTS.values())
WEIGHTS = {k: v / _W_TOTAL for k, v in _RAW_WEIGHTS.items()}


class PBModel:
    """Stateful, bar-by-bar evaluator for a single instrument."""

    def __init__(self, symbol: str, confluence_threshold: float = 0.75,
                 swing_k: int = 2, displacement_mult: float = 1.5,
                 require_killzone: bool = False,
                 news: Optional[NewsCalendar] = None,
                 max_history: int = 800,
                 struct_window: int = 200,
                 htf_minutes: int = 15,
                 htf2_minutes: int = 60,
                 require_htf_alignment: bool = True,
                 ote_low: float = 0.62,
                 ote_high: float = 0.79,
                 tp_min_r: float = 1.0,
                 tp_max_r: float = 3.0,
                 min_stop_ticks: int = 8,
                 require_sweep: bool = True,
                 min_displacement: float = 0.0,
                 entry_mode: str = "ce",      # "ce" = consequent encroachment, "edge"
                 signal_window: int = 3,      # fire within N bars of the iFVG inverting
                 weights: Optional[dict] = None):   # per-profile confluence emphasis
        self.symbol = symbol
        self.threshold = confluence_threshold
        self.swing_k = swing_k
        self.displacement_mult = displacement_mult
        self.max_history = max_history
        self.struct_window = struct_window
        self.require_killzone = require_killzone
        self.news = news or NewsCalendar()
        self.htf_minutes = htf_minutes
        self.htf2_minutes = htf2_minutes
        self.require_htf_alignment = require_htf_alignment
        self.ote_low = ote_low
        self.ote_high = ote_high
        self.tp_min_r = tp_min_r
        self.tp_max_r = tp_max_r
        self.min_stop_ticks = min_stop_ticks
        self.require_sweep = require_sweep
        self.min_displacement = min_displacement
        self.entry_mode = entry_mode
        self.signal_window = signal_window
        # Confluence weights (optionally a profile's emphasis), normalized to sum 1.0.
        w = weights or WEIGHTS
        wt = sum(w.values()) or 1.0
        self.weights = {k: v / wt for k, v in w.items()}
        self._signaled: set = set()    # iFVGs already signalled (avoid duplicate limits)
        self.tick = CONTRACTS.get(symbol, {}).get("tick", 0.25)
        self.sessions = SessionTracker()
        self._sweep_significant: Optional[str] = None
        self._bprs: list = []
        self.bars: list[Bar] = []
        self.struct = StructureState()
        self.po3 = DailyPO3()
        self.fvgs: list = []
        self.blocks: list = []
        self.breakers: list = []
        self.voids: list = []
        self.vacuums: list = []
        self.htf_trend: Optional[Direction] = None
        self.htf2_trend: Optional[Direction] = None
        self._htf_fvgs: list = []
        self._htf_bucket = None
        self._htf2_bucket = None
        self._range_high = None
        self._range_low = None
        self.pools: list = []
        self.conditions: Optional[MarketConditions] = None
        self._recent_sweep = None
        self._sweep_age = 0
        self._sweep_index = -1

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
        self.sessions.update(bar)
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

        # ---- Top-down: higher-timeframe bias (core SMC), two timeframes ----
        # HTF bias only changes when an HTF candle closes, so recompute once per HTF
        # bucket instead of every bar (the resample is the most expensive step).
        b1 = _bucket(bar.ts, self.htf_minutes)
        if b1 != self._htf_bucket:
            self._htf_bucket = b1
            self.htf_trend = htf_bias(self.bars, self.htf_minutes, self.swing_k)
            self._htf_fvgs = htf_fvgs(self.bars, self.htf_minutes)
        b2 = _bucket(bar.ts, self.htf2_minutes)
        if b2 != self._htf2_bucket:
            self._htf2_bucket = b2
            self.htf2_trend = htf_bias(self.bars, self.htf2_minutes, self.swing_k)

        # ---- Incremental SMC objects: detect what FORMS on this bar, then update
        # persisted state once. O(1) amortized per bar (was O(n) recompute = O(n^2)). ----
        nf = new_fvg(self.bars)
        if nf is not None:
            self.fvgs.append(nf)
            ob = order_block_at_formation(self.bars, nf.direction)
            if ob is not None:
                self.blocks.append(ob)
        nv = new_void(self.bars)
        if nv is not None:
            self.voids.append(nv)
        vac = new_vacuum(self.bars)         # vacuum block (true price gap)
        if vac is not None:
            self.vacuums.append(vac)

        update_fvg_states(self.fvgs, bar, i)
        update_block_states(self.blocks, bar)
        flip_broken_blocks(self.blocks, self.breakers, bar)
        update_void_states(self.voids, bar)

        # Bound the object lists (older mitigated/filled levels stop mattering).
        self.fvgs = self.fvgs[-60:]
        self.blocks = self.blocks[-40:]
        self.breakers = self.breakers[-40:]
        self.voids = self.voids[-40:]
        self.vacuums = self.vacuums[-20:]
        for v in self.vacuums:
            update_void_states([v], bar)
        # Forget signalled iFVGs older than the recent window (bounded memory).
        if len(self._signaled) > 200:
            self._signaled = {k for k in self._signaled if k[2] >= i - 300}

        # Structure + liquidity pools from swings over a recent window (LTF structure
        # only needs recent swings; the long-term picture comes from the HTF bias).
        window = self.bars[-self.struct_window:]
        swings = find_swings(window, self.swing_k)
        self.struct.update(swings, bar, len(window) - 1)
        self.pools = build_pools(swings)

        # Cache the dealing range (most recent swing low/high) for OTE — avoids a
        # second find_swings pass inside ote_check.
        self._range_high = next((s.price for s in reversed(swings) if s.kind == "high"), None)
        self._range_low = next((s.price for s in reversed(swings) if s.kind == "low"), None)

        self._bprs = detect_bpr(self.fvgs)

        sweep = detect_sweep(self.pools, bar)
        if sweep:
            self._recent_sweep = sweep
            self._sweep_age = 0
            self._sweep_index = i      # for PB mechanical-model sequencing
            # Grade the sweep: did it take SIGNIFICANT liquidity (PDH/PDL/session/open)?
            tol = 6 * self.tick
            self._sweep_significant = self.sessions.is_significant(sweep.price, tol)
        elif self._recent_sweep:
            self._sweep_age += 1
            if self._sweep_age > 10:       # sweep edge decays
                self._recent_sweep = None
                self._sweep_significant = None

        return self._evaluate(bar, i)

    def _evaluate(self, bar: Bar, i: int) -> Optional[Setup]:
        trend = self.struct.trend
        if trend is None:
            return None

        # Top-down gate: don't fight a decided higher-timeframe bias.
        if self.require_htf_alignment and self.htf_trend is not None \
                and self.htf_trend != trend:
            return None

        # Core-SMC gate: an A+ requires liquidity to have been taken (the stop-hunt).
        # No sweep → no trade. This is the heart of the model, so it's mandatory.
        if self.require_sweep and self._recent_sweep is None:
            return None
        # Optional displacement-energy gate: skip limp moves.
        if self.min_displacement > 0 and self._displacement() < self.min_displacement:
            return None

        ifvgs = active_ifvgs(self.fvgs)
        if not ifvgs:
            return None

        # Collect FRESHLY-inverted aligned candidates (cheap) before any heavy scoring.
        # We fire on inversion and place a limit at the CE for the anticipated retest.
        candidates = []
        for f in ifvgs:
            if f.direction != trend:
                continue
            fresh = f.inverted_at >= 0 and 0 <= (i - f.inverted_at) <= self.signal_window
            key = (round(f.bottom, 2), round(f.top, 2), f.inverted_at)
            if fresh and key not in self._signaled:
                candidates.append((f, key))
        if not candidates:
            return None

        # ---- f-INDEPENDENT components: compute ONCE per bar (was recomputed per
        # candidate — the heavy detections dominated the profile). ----
        lo, eq, hi = premium_discount(self.bars)
        dq = self._displacement()
        base = self.weights["structure"]
        base_reasons = [f"HTF structure {trend.value} (last event aligns)"]

        in_discount = bar.close < eq
        if (trend is Direction.BULL and in_discount) or (trend is Direction.BEAR and not in_discount):
            base += self.weights["pd"]
            base_reasons.append("price in " + ("discount" if in_discount else "premium") + " — aligned")
        if self._recent_sweep is not None:
            base += self.weights["sweep"]
            base_reasons.append(f"liquidity sweep: {self._recent_sweep.kind} @ {self._recent_sweep.price:.2f}")
            if self._sweep_significant:
                base += self.weights["sweep_significant"]
                base_reasons.append(f"significant liquidity taken: {self._sweep_significant}")
        if detect_cisd(self.bars, trend):
            base += self.weights["cisd"]
            base_reasons.append("CISD confirmation (delivery flipped)")
        if detect_rejection_block(self.bars, trend):
            base += self.weights["rejection"]
            base_reasons.append("rejection block (wick rejection)")
        if self.htf_trend is not None and self.htf_trend == trend:
            base += self.weights["htf_bias"]
            base_reasons.append(f"HTF({self.htf_minutes}m) bias {trend.value} aligned")
        if self.htf2_trend is not None and self.htf2_trend == trend:
            base += self.weights["htf2_bias"]
            base_reasons.append(f"HTF({self.htf2_minutes}m) bias {trend.value} aligned")
        if retesting_block(self.blocks, trend, bar):
            base += self.weights["order_block"]
            base_reasons.append("fresh order block retest")
        if retesting_breaker(self.breakers, trend, bar):
            base += self.weights["breaker"]
            base_reasons.append("breaker block retest")
        if retesting_propulsion(self.blocks, trend, bar, tol=8 * self.tick):
            base += self.weights["propulsion"]
            base_reasons.append("propulsion block (stacked OBs)")
        base += self.weights["displacement"] * dq
        base_reasons.append(f"displacement quality {dq:.0%}")
        mss = detect_mss(self.bars, self.swing_k)
        if mss is not None and mss == trend:
            base += self.weights["mss"]
            base_reasons.append(f"TJR MSS confirms {trend.value}")
        kz = current_killzone(bar.ts)
        if kz is not None:
            base += self.weights["killzone"]
            base_reasons.append(f"killzone: {kz}")
        mac = current_macro(bar.ts)
        if mac is not None:
            base += self.weights["macro"]
            base_reasons.append(f"ICT macro: {mac}")
        if self.po3.bias_aligns(trend):
            base += self.weights["daily_bias"]
            base_reasons.append(f"PO3 daily bias {self.po3.bias.value} aligned")
        ob = self.sessions.opening_bias(bar.close)
        if ob is not None and ob == trend:
            base += self.weights["opening_bias"]
            base_reasons.append(f"opening-price bias {ob.value} (vs day open)")
        wpd = self.sessions.weekly_pd_bias(bar.close)
        if wpd is not None and wpd == trend:
            base += self.weights["weekly_pd"]
            base_reasons.append(f"weekly {'discount' if trend is Direction.BULL else 'premium'} (PD array)")
        if self.conditions:
            base_reasons.append("conditions: " + "; ".join(self.conditions.reasons[:1]))

        mech_ready = (self._recent_sweep is not None and self._sweep_index >= 0 and dq > 0.2)
        side_for_ote = Side.LONG if trend is Direction.BULL else Side.SHORT

        # ---- f-DEPENDENT components: cheap, per candidate ----
        best: Optional[Setup] = None
        for f, key in candidates:
            score = base + self.weights["ifvg"]
            reasons = base_reasons + [f"iFVG retest [{f.bottom:.2f}, {f.top:.2f}]"]
            if mech_ready and f.inverted_at >= self._sweep_index:
                score += self.weights["mechanical_model"]
                reasons.append("PB mechanical model: sweep → displacement-inversion → retest")
            if f.sponsored:
                score += self.weights["sponsored"]
                reasons.append("sponsored FVG (institutional volume)")
            ce = consequent_encroachment(f)
            if in_bpr(ce, self._bprs):
                score += self.weights["bpr"]
                reasons.append("entry in balanced price range (BPR)")
            if in_htf_fvg(ce, self._htf_fvgs, trend):
                score += self.weights["htf_fvg_nest"]
                reasons.append(f"nested in HTF({self.htf_minutes}m) FVG")
            entry_price = f.top if trend is Direction.BULL else f.bottom
            if self._range_low is not None and self._range_high is not None \
                    and in_ote(entry_price, self._range_low, self._range_high,
                               side_for_ote, self.ote_low, self.ote_high):
                score += self.weights["ote"]
                reasons.append(f"OTE zone ({self.ote_low:.2f}-{self.ote_high:.2f} fib)")
            if nearest_unfilled_void(self.voids, entry_price, trend) is not None:
                score += self.weights["void"]
                reasons.append("unfilled liquidity void ahead")
            if nearest_unfilled_void(self.vacuums, entry_price, trend) is not None:
                score += self.weights["vacuum"]
                reasons.append("vacuum block (price gap) ahead")

            if score < self.threshold:
                continue
            self._signaled.add(key)        # one limit per inverted iFVG
            candidate = self._build_setup(bar, f, trend, score, reasons)
            if best is None or candidate.confluence > best.confluence:
                best = candidate
        return best

    def _build_setup(self, bar: Bar, f, trend: Direction, score: float,
                     reasons: list[str]) -> Setup:
        min_stop = self.min_stop_ticks * self.tick
        # ICT consequent encroachment: fill at the gap's 50% (better price) vs the edge.
        ce = consequent_encroachment(f)
        if trend is Direction.BULL:
            side = Side.LONG
            entry = ce if self.entry_mode == "ce" else f.top
            stop = min(f.bottom, bar.low) - 0.25
            stop = min(stop, entry - min_stop)  # enforce a minimum stop distance
            risk = entry - stop
            # Target the draw on liquidity (external pool) first, then any liquidity.
            dol = draw_on_liquidity(self.pools, entry, Direction.BULL)
            tgt_pool = dol or next_liquidity(self.pools, entry, "up")
            raw = tgt_pool.price if (tgt_pool and tgt_pool.price > entry) \
                else entry + 2 * risk
            reward_r = (raw - entry) / risk if risk > 0 else self.tp_min_r
            reward_r = max(self.tp_min_r, min(self.tp_max_r, reward_r))  # clamp to 1:1..1:max
            targets = [entry + reward_r * risk]
        else:
            side = Side.SHORT
            entry = ce if self.entry_mode == "ce" else f.bottom
            stop = max(f.top, bar.high) + 0.25
            stop = max(stop, entry + min_stop)  # enforce a minimum stop distance
            risk = stop - entry
            dol = draw_on_liquidity(self.pools, entry, Direction.BEAR)
            tgt_pool = dol or next_liquidity(self.pools, entry, "down")
            raw = tgt_pool.price if (tgt_pool and tgt_pool.price < entry) \
                else entry - 2 * risk
            reward_r = (entry - raw) / risk if risk > 0 else self.tp_min_r
            reward_r = max(self.tp_min_r, min(self.tp_max_r, reward_r))
            targets = [entry - reward_r * risk]

        return Setup(
            symbol=self.symbol, side=side, entry=round(entry, 2),
            stop=round(stop, 2), targets=[round(t, 2) for t in targets],
            ts=bar.ts, confluence=round(score, 3), reasons=reasons,
            session=_session_of(bar.ts), features=self._features(reasons, bar),
        )

    # Concept keywords -> stable feature tags the brain/memory learn from.
    _CONCEPT_MAP = (
        ("mechanical model", "mechanical"), ("sponsored FVG", "sponsored"),
        ("significant liquidity", "sig_sweep"), ("nested in HTF", "htf_fvg"),
        ("CISD", "cisd"), ("rejection block", "rejection"),
        ("balanced price range", "bpr"), ("order block", "ob"),
        ("breaker block", "breaker"), ("OTE zone", "ote"),
        ("ICT macro", "macro"), ("killzone", "killzone"),
        ("opening-price bias", "opening_bias"), ("PO3 daily bias", "po3"),
        ("propulsion block", "propulsion"), ("vacuum block", "vacuum"),
        ("weekly", "weekly_pd"), ("MSS confirms", "mss"),
        ("in discount", "pd"), ("in premium", "pd"), ("m) bias", "htf_bias"),
    )

    def _features(self, reasons: list[str], bar: Bar) -> dict:
        text = " | ".join(reasons)
        concepts = [tag for kw, tag in self._CONCEPT_MAP if kw in text]
        # PB Blake canonical grade: the documented mech model = sweep of SIGNIFICANT
        # liquidity → inversion (iFVG) → UNFILLED higher-TF FVG, in sequence. When all
        # are present the brain tags it "blake" so memory learns Blake-grade setups apart.
        if "mechanical" in concepts and "sig_sweep" in concepts and "htf_fvg" in concepts:
            concepts.append("blake")
        # PB Patty SWING / PDI grade: HTF value-gap (PD-array) rejection + LTF structure
        # shift (MSS) + premium/discount — the swing signature. Tagged so the brain learns
        # Patty-grade swing setups apart from Blake-grade intraday ones.
        if "htf_fvg" in concepts and "mss" in concepts and "pd" in concepts:
            concepts.append("patty")

        # The PB A+ Setup CHECKLIST (Mech Model 2.0): the documented 6 questions. Count how
        # many are satisfied; a full-checklist setup is the canonical PB A+ ("pb_aplus").
        cset = set(concepts)
        checklist = sum([
            bool(cset & {"htf_fvg", "htf_bias", "weekly_pd"}),   # 1) reject HTF PD array
            "sig_sweep" in cset,                                  # 2) swept prominent HTF liquidity
            bool(cset & {"killzone", "macro"}),                  # 3) time aligned
            bool(cset & {"sig_sweep", "vacuum", "bpr"}),         # 4) EQH/EQL / daily H-L / gaps
            "pd" in cset,                                         # 5) above/below equilibrium
        ])  # (6) SMT alignment is enforced at the instrument-selection layer
        if checklist >= 4:
            concepts.append("pb_aplus")

        regime = self.conditions.regime if self.conditions else "na"
        return {
            "concepts": concepts,
            "regime": regime,
            "session": _session_of(bar.ts),
            "macro": current_macro(bar.ts) is not None,
            "checklist": checklist,
        }


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
