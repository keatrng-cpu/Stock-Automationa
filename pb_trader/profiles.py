"""PB trader profiles — Blake, Ronan, Patty (+ default).

Each profile is a distinct setup/execution style: a base confluence threshold, entry
mode, R:R band, optional session/killzone requirement, and a confluence *emphasis* (a
multiplier on specific components so the model leans on what that trader leans on).

⚠️ HONESTY NOTE: these emphases are my best PB/ICT *interpretation* of how Blake, Ronan
and Patty differ — NOT verified transcripts of their exact playbooks (I can't fetch
those here, and the engine must never fabricate setups). Tell me each trader's real
approach and I'll tune these precisely. They are starting points, clearly labeled.

A profile yields model_kwargs (threshold, entry_mode, tp_*, require_*, weight emphasis)
that backtest/weekly/live apply via --profile.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .strategy.pb_model import _RAW_WEIGHTS


@dataclass
class TraderProfile:
    name: str
    threshold: float
    entry_mode: str = "ce"
    tp_min_r: float = 1.0
    tp_max_r: float = 3.0
    require_killzone: bool = False
    min_displacement: float = 0.0
    emphasis: dict = field(default_factory=dict)   # component -> multiplier (>1 favors it)
    note: str = ""

    def weights(self) -> dict:
        w = dict(_RAW_WEIGHTS)
        for k, mult in self.emphasis.items():
            if k in w:
                w[k] = w[k] * mult
        return w

    def model_kwargs(self) -> dict:
        return {
            "confluence_threshold": self.threshold,
            "entry_mode": self.entry_mode,
            "tp_min_r": self.tp_min_r,
            "tp_max_r": self.tp_max_r,
            "require_killzone": self.require_killzone,
            "min_displacement": self.min_displacement,
            "weights": self.weights(),
        }


# --- Profiles (interpretation; confirm/correct the specifics) ---
PROFILES = {
    # Strict Mechanical Model 2.0: the sequence + significant liquidity, mechanical-only.
    "blake": TraderProfile(
        "PB Blake", threshold=0.80, entry_mode="ce", tp_max_r=3.0,
        min_displacement=0.3,
        emphasis={"mechanical_model": 1.6, "sweep_significant": 1.5, "displacement": 1.4,
                  "ifvg": 1.2, "sponsored": 1.3},
        note="Mechanical Model 2.0 — strict sweep→displacement-inversion→retest, sponsored gaps."),
    # Top-down / SMT + HTF bias + killzone discipline; patient, session-driven.
    "ronan": TraderProfile(
        "PB Ronan / PJ", threshold=0.80, entry_mode="ce", tp_max_r=3.0,
        require_killzone=True,
        emphasis={"htf_bias": 1.5, "htf2_bias": 1.4, "htf_fvg_nest": 1.4,
                  "weekly_pd": 1.4, "killzone": 1.6, "daily_bias": 1.4},
        note="Top-down: HTF bias + weekly PD + killzone-only execution (SMT-aware)."),
    # Precision entries: OTE / CISD / breaker, tighter targets, scalp-leaning.
    "patty": TraderProfile(
        "PB Patty", threshold=0.78, entry_mode="ce", tp_min_r=1.0, tp_max_r=2.0,
        emphasis={"ote": 1.6, "cisd": 1.5, "breaker": 1.4, "rejection": 1.4,
                  "bpr": 1.3, "macro": 1.3},
        note="Precision/OTE entries with CISD + breaker confirmation; tighter 1:1–1:2 targets."),
    "default": TraderProfile(
        "Balanced", threshold=0.78, note="The full balanced 26-component stack."),
}


def get_profile(name: str) -> TraderProfile:
    key = (name or "default").lower()
    if key not in PROFILES:
        raise ValueError(f"unknown profile '{name}'. Options: {', '.join(PROFILES)}")
    return PROFILES[key]
