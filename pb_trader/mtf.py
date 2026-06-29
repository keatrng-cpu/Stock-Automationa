"""Multi-timeframe conjunction — look at ALL timeframes at once, not one in isolation.

A single base PBModel executes on the finest chart, but price is fractal: a 1m long into
a 15m downtrend is a trap. This wrapper runs the full timeframe LADDER *in conjunction* —
on every candidate setup it resamples the accumulated bars to each higher timeframe, reads
each one's structural bias, and tallies a cross-timeframe vote:

  - If the higher timeframes NET OPPOSE the setup's direction → veto (don't fight the stack).
  - Otherwise keep it, add a confluence bonus proportional to agreement, and tag it
    `mtf_confirmed` (+ `mtf:agree:K`) so the brain LEARNS that multi-TF-aligned setups
    behave differently from one-timeframe setups.

It duck-types PBModel (`on_bar(bar) -> Optional[Setup]`) so the backtester/live loop use it
interchangeably. No look-ahead: every higher-TF read is built only from bars already seen.
"""
from __future__ import annotations

from typing import Optional

from .models import Bar, Direction, Setup, Side
from .strategy.htf import htf_bias
from .strategy.pb_model import PBModel
from .timeframes import LADDER_MIN, tf_minutes

_SIDE_DIR = {Side.LONG: Direction.BULL, Side.SHORT: Direction.BEAR}


class MultiTimeframeModel:
    """Wrap a base PBModel and gate its setups by a full multi-timeframe agreement vote."""

    def __init__(self, symbol: str, threshold: float = 0.75,
                 timeframe: str = "1m", confirm_minutes: Optional[list[float]] = None,
                 max_bonus: float = 0.08, min_agreement: float = 0.0, **model_kwargs):
        self.base = PBModel(symbol, threshold, timeframe=timeframe, **model_kwargs)
        base_min = tf_minutes(timeframe)
        # The confirmation ladder: every standard timeframe strictly above the execution TF.
        self.confirm_minutes = confirm_minutes or [m for m in LADDER_MIN if m > base_min]
        self.max_bonus = max_bonus
        self.min_agreement = min_agreement      # net agreement floor to allow a trade
        self.swing_k = self.base.swing_k
        # Expose the attributes the harness/report read off a model.
        self.symbol = symbol
        self.timeframe = timeframe

    # --- duck-typed pass-throughs so callers treat us like a PBModel ---
    @property
    def bars(self) -> list[Bar]:
        return self.base.bars

    @property
    def conditions(self):
        return self.base.conditions

    def __getattr__(self, name):
        # Anything we don't define (htf_minutes, sessions, pools, project_scenarios, …)
        # falls through to the base model.
        return getattr(self.base, name)

    def _vote(self, side: Side) -> tuple[int, int, int]:
        """Tally higher-timeframe structural bias vs the setup side: (agree, oppose, total)."""
        want = _SIDE_DIR[side]
        agree = oppose = total = 0
        bars = self.base.bars
        for m in self.confirm_minutes:
            b = htf_bias(bars, int(round(m)) or 1, self.swing_k)
            if b is None:
                continue
            total += 1
            if b == want:
                agree += 1
            else:
                oppose += 1
        return agree, oppose, total

    def on_bar(self, bar: Bar) -> Optional[Setup]:
        setup = self.base.on_bar(bar)
        if setup is None:
            return None

        agree, oppose, total = self._vote(setup.side)
        if total == 0:
            return setup                          # not enough history above — pass through
        net = (agree - oppose) / total            # -1 (all oppose) .. +1 (all agree)
        if net < self.min_agreement or oppose > agree:
            return None                           # higher timeframes net-oppose → stand aside

        # Confirmed by the stack: reward agreement (capped) and record it for the brain.
        bonus = self.max_bonus * max(0.0, net)
        setup.confluence = min(0.99, setup.confluence + bonus)
        setup.reasons.append(
            f"multi-TF conjunction: {agree}/{total} higher TFs agree (net {net:+.0%}, "
            f"+{bonus:.2f} conf)")
        if isinstance(setup.features, dict):
            cs = setup.features.setdefault("concepts", [])
            cs.append("mtf_confirmed")
            cs.append(f"mtf:agree:{agree}")
            setup.features["mtf_net"] = round(net, 2)
        return setup
