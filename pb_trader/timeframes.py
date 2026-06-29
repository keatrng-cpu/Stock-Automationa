"""Timeframe ladder + top-down selection — the engine runs on any of these.

Supported base timeframes (the full ladder):
  30s, 1m, 2m, 3m, 4m, 5m, 10m, 15m, 30m, 45m, 60m, 90m, 120m, 180m, 240m

For any base timeframe, `htf_for` picks two higher timeframes for top-down bias, snapped
to the ladder — so multi-timeframe analysis works whether you trade 30-second or 4-hour.
"""
from __future__ import annotations

LADDER = ["30s", "1m", "2m", "3m", "4m", "5m", "10m", "15m",
          "30m", "45m", "60m", "90m", "120m", "180m", "240m"]


def parse_tf(tf) -> int:
    """Timeframe -> seconds. Accepts '30s', '5m', or an int (minutes)."""
    if isinstance(tf, (int, float)):
        return int(tf * 60)
    tf = str(tf).strip().lower()
    if tf.endswith("s"):
        return int(tf[:-1])
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    return int(tf) * 60          # bare number = minutes


def tf_minutes(tf) -> float:
    return parse_tf(tf) / 60.0


LADDER_MIN = [tf_minutes(t) for t in LADDER]


def snap_to_ladder(minutes: float, above: float = 0.0) -> float:
    """Nearest ladder timeframe (in minutes) strictly greater than `above`."""
    cands = [m for m in LADDER_MIN if m > above]
    if not cands:
        return max(LADDER_MIN)
    return min(cands, key=lambda m: abs(m - minutes))


def htf_for(base_minutes: float) -> tuple[float, float]:
    """Two higher timeframes for top-down bias (~15x and ~60x base, snapped, capped)."""
    h1 = snap_to_ladder(base_minutes * 15, above=base_minutes)
    h2 = snap_to_ladder(base_minutes * 60, above=h1)
    return h1, h2


def htf_minutes_for(timeframe) -> tuple[int, int]:
    """HTF pair as integer minutes (>=1) for the model, given any base timeframe."""
    h1, h2 = htf_for(tf_minutes(timeframe))
    return max(1, round(h1)), max(1, round(h2))
