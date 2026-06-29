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
    htf_minutes: int | None = None     # override the auto-selected HTF pair
    htf2_minutes: int | None = None
    emphasis: dict = field(default_factory=dict)   # component -> multiplier (>1 favors it)
    note: str = ""

    def weights(self) -> dict:
        w = dict(_RAW_WEIGHTS)
        for k, mult in self.emphasis.items():
            if k in w:
                w[k] = w[k] * mult
        return w

    def model_kwargs(self) -> dict:
        mk = {
            "confluence_threshold": self.threshold,
            "entry_mode": self.entry_mode,
            "tp_min_r": self.tp_min_r,
            "tp_max_r": self.tp_max_r,
            "require_killzone": self.require_killzone,
            "min_displacement": self.min_displacement,
            "weights": self.weights(),
        }
        if self.htf_minutes:
            mk["htf_minutes"] = self.htf_minutes
        if self.htf2_minutes:
            mk["htf2_minutes"] = self.htf2_minutes
        return mk


# --- Profiles (interpretation; confirm/correct the specifics) ---
PROFILES = {
    # PB Blake Mechanical Model — DOCUMENTED (pbtrading.io / PB Blake YouTube): sweep
    # significant liquidity (PDH/PDL, AM/session highs, EQH/EQL) → inversion (iFVG) on the
    # highest-TF leg → target unfilled FVGs; same % risk, BE after 1:1, run to external.
    # R:R ~1:1–1:1.5, claimed 70–80% win. This matches our mechanical model directly.
    "blake": TraderProfile(
        "PB Blake", threshold=0.80, entry_mode="ce", tp_min_r=1.0, tp_max_r=3.0,
        min_displacement=0.3, htf_minutes=5, htf2_minutes=15,   # FVG from 3-15m, entry 1-5m
        require_killzone=True,                                  # NY AM/PM macros, avoid lunch
        emphasis={"mechanical_model": 1.6, "sweep_significant": 1.6, "ifvg": 1.3,
                  "displacement": 1.4, "htf_fvg_nest": 1.4, "sponsored": 1.2},
        note="DOCUMENTED mech model (pbtrading.io / PB Blake YT): swing-low/high/lower-low + "
             "sweep PDH/PDL/AM/EQH/EQL → inversion (iFVG) on highest TF (3-15m) with UNFILLED "
             "FVG; entry 1-5m; sessions 9:30-11:00 & 13:00-15:00 (avoid lunch); stop past the "
             "inversion/OB; BE after 1:1, runner to external liquidity. ~70-80% claimed."),
    # PB Patrick / PJ (co-founder). No distinct public playbook found beyond the shared
    # mech model — INTERPRETATION: same core, top-down/HTF + session lean. Confirm specifics.
    "ronan": TraderProfile(
        "PB Patrick/PJ", threshold=0.80, entry_mode="ce", tp_min_r=1.0, tp_max_r=2.0,
        emphasis={"mechanical_model": 1.4, "htf_bias": 1.4, "htf2_bias": 1.3,
                  "htf_fvg_nest": 1.3, "weekly_pd": 1.3, "daily_bias": 1.3},
        note="INTERPRETATION (co-founder; shares the mech model). Top-down lean — confirm."),
    # PB Patty — NO distinct public info found. INTERPRETATION only: precision OTE/CISD
    # scalp lean with tighter targets. Needs your input (likely paid-mentorship content).
    "patty": TraderProfile(
        "PB Patty", threshold=0.78, entry_mode="ce", tp_min_r=1.0, tp_max_r=1.5,
        emphasis={"mechanical_model": 1.3, "ote": 1.5, "cisd": 1.4, "breaker": 1.3,
                  "rejection": 1.3, "macro": 1.3},
        note="INTERPRETATION ONLY — no public playbook found. Precision/OTE scalp lean. Confirm."),
    "default": TraderProfile(
        "Balanced", threshold=0.78, note="The full balanced 26-component stack."),
}


def get_profile(name: str) -> TraderProfile:
    key = (name or "default").lower()
    if key not in PROFILES:
        raise ValueError(f"unknown profile '{name}'. Options: {', '.join(PROFILES)}")
    return PROFILES[key]
