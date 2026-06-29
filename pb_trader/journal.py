"""Trade & signal journal (JSONL). Detach P&L; losses are tuition/data."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

JOURNAL_DIR = Path("journal")


def _default(o: Any):
    if isinstance(o, datetime):
        return o.isoformat()
    if is_dataclass(o):
        return asdict(o)
    if hasattr(o, "value"):  # Enum
        return o.value
    return str(o)


def log_event(kind: str, payload: Any, path: str | None = None) -> None:
    JOURNAL_DIR.mkdir(exist_ok=True)
    fname = path or f"{datetime.now().strftime('%Y%m%d') if False else 'session'}.jsonl"
    rec = {"kind": kind, "payload": payload}
    with open(JOURNAL_DIR / fname, "a") as fh:
        fh.write(json.dumps(rec, default=_default) + "\n")
