"""Settings loaded from environment / .env (no hard dependency on python-dotenv)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so we don't require python-dotenv."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Hard ceiling on risk per trade — code refuses to exceed this regardless of env.
MAX_RISK_PCT_CEILING = 0.01  # 1.0%


@dataclass
class Settings:
    mode: str = os.environ.get("PB_MODE", "paper")
    account_equity: float = _f("PB_ACCOUNT_EQUITY", 10_000.0)
    risk_pct: float = min(_f("PB_RISK_PCT", 0.005), MAX_RISK_PCT_CEILING)
    max_setups_per_session: int = _i("PB_MAX_SETUPS_PER_SESSION", 1)
    # A+ gate: never take a setup below 75% confluence.
    confluence_threshold: float = max(_f("PB_CONFLUENCE_THRESHOLD", 0.75), 0.75)
    # Realistic cost model: per-side slippage in ticks (commission is per-contract in CONTRACTS).
    slippage_ticks: float = _f("PB_SLIPPAGE_TICKS", 1.0)

    # Databento
    databento_api_key: str = os.environ.get("DATABENTO_API_KEY", "")
    databento_dataset: str = os.environ.get("DATABENTO_DATASET", "GLBX.MDP3")

    # Tradovate
    tradovate_env: str = os.environ.get("TRADOVATE_ENV", "demo")
    tradovate_username: str = os.environ.get("TRADOVATE_USERNAME", "")
    tradovate_password: str = os.environ.get("TRADOVATE_PASSWORD", "")
    tradovate_app_id: str = os.environ.get("TRADOVATE_APP_ID", "")
    tradovate_app_version: str = os.environ.get("TRADOVATE_APP_VERSION", "1.0")
    tradovate_cid: str = os.environ.get("TRADOVATE_CID", "")
    tradovate_secret: str = os.environ.get("TRADOVATE_SECRET", "")
    tradovate_device_id: str = os.environ.get("TRADOVATE_DEVICE_ID", "")

    @property
    def tradovate_configured(self) -> bool:
        return bool(self.tradovate_username and self.tradovate_password
                    and self.tradovate_cid and self.tradovate_secret)

    @property
    def live_enabled(self) -> bool:
        """Live orders require explicit mode AND real creds — belt and suspenders."""
        return self.mode == "live" and self.tradovate_configured


settings = Settings()
