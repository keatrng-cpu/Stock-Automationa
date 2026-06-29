"""ICT Macros — the ~20-minute windows where algorithms reliably run price.

ICT teaches that price delivery concentrates in specific intraday windows (NY time).
Trading inside a macro adds timing confluence; outside, moves are more random.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

# (start_min, end_min) as minutes-from-midnight, NY time, with a label.
_MACROS = [
    (2 * 60 + 33, 3 * 60, "London 02:33"),
    (8 * 60 + 50, 9 * 60 + 10, "NY 08:50"),
    (9 * 60 + 50, 10 * 60 + 10, "Silver Bullet 09:50"),
    (10 * 60 + 50, 11 * 60 + 10, "NY 10:50"),
    (11 * 60 + 50, 12 * 60 + 10, "Lunch 11:50"),
    (13 * 60 + 10, 13 * 60 + 40, "PM 13:10"),
    (15 * 60 + 15, 15 * 60 + 45, "PM 15:15"),
]


def current_macro(ts: datetime) -> Optional[str]:
    m = ts.hour * 60 + ts.minute
    for start, end, name in _MACROS:
        if start <= m < end:
            return name
    return None


def in_macro(ts: datetime) -> bool:
    return current_macro(ts) is not None
