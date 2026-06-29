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
    default_timeframe: str = "1m"      # the base chart this style belongs on
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
        default_timeframe="1m",                                 # intraday mech model
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
    # PB Patty SWING / "PDI model" — PARTIALLY DOCUMENTED (PB Trading TikTok/YT): a swing
    # variant on higher timeframes — reject HTF key levels (1h/4h/daily value gaps + order
    # blocks), premium/discount, where LIQUIDITY rejection + PERIOD rejection align; LTF
    # structure shift (MSS) for entry; avoid against trend / SMT. NQ focus, larger targets.
    "patty": TraderProfile(
        "PB Patty (Swing/PDI)", threshold=0.78, entry_mode="ce",
        tp_min_r=1.5, tp_max_r=4.0, htf_minutes=60, htf2_minutes=240,
        default_timeframe="15m",                               # swing belongs on 15m
        emphasis={"htf_bias": 1.5, "htf2_bias": 1.5, "htf_fvg_nest": 1.6, "pd": 1.5,
                  "order_block": 1.4, "mss": 1.5, "weekly_pd": 1.4, "rejection": 1.4,
                  "sweep_significant": 1.3},
        note="Swing 'PDI' model (partial-doc): HTF PD arrays (1h/4h/daily FVG+OB) rejection "
             "+ liquidity sweep + LTF MSS entry; premium/discount; avoid vs trend/SMT; NQ, "
             "larger swing targets. Refine remaining specifics from the mentorship."),
    # PB Patty FAST / SCALP — Patty sometimes executes very fast on the 30s (and smaller)
    # chart. Public sources DON'T document a PB-specific sub-minute playbook, so this is the
    # defensible ICT-scalp interpretation: tight, macro/killzone-gated entries on a liquidity
    # sweep + LTF structure shift (MSS), small targets, fast in/out. Clearly labeled, not a
    # verified transcript — correct the specifics from the mentorship and I'll tune it.
    "patty_scalp": TraderProfile(
        "PB Patty (Fast/Scalp)", threshold=0.78, entry_mode="ce",
        tp_min_r=1.0, tp_max_r=2.0, htf_minutes=5, htf2_minutes=15,
        default_timeframe="30s",                               # sub-minute fast execution
        require_killzone=True, min_displacement=0.3,           # macro/killzone only, sharp moves
        emphasis={"mechanical_model": 1.5, "mss": 1.6, "sweep_significant": 1.5,
                  "macro": 1.6, "killzone": 1.4, "displacement": 1.4, "ifvg": 1.3},
        note="INTERPRETATION (no public 30s PB playbook found): fast sub-minute scalp — sweep "
             "+ LTF MSS inside a macro/killzone window, tight 1-2R targets, sharp displacement. "
             "Belongs on 30s/lower. Confirm the real fast-execution rules from the mentorship."),
    "default": TraderProfile(
        "Balanced", threshold=0.78, note="The full balanced 26-component stack."),
}


def get_profile(name: str) -> TraderProfile:
    key = (name or "default").lower()
    if key not in PROFILES:
        raise ValueError(f"unknown profile '{name}'. Options: {', '.join(PROFILES)}")
    return PROFILES[key]
