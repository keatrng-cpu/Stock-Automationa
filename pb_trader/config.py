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
# Aggressive-but-survivable growth plan: 2% default, 5% fat-finger ceiling.
MAX_RISK_PCT_CEILING = 0.05  # 5%
# Above this, the engine prints a loud risk warning every run.
RISK_WARN_THRESHOLD = 0.02   # 2%


@dataclass
class Settings:
    mode: str = os.environ.get("PB_MODE", "paper")
    account_equity: float = _f("PB_ACCOUNT_EQUITY", 1_000.0)        # growth plan starts at $1k
    risk_pct: float = min(_f("PB_RISK_PCT", 0.02), MAX_RISK_PCT_CEILING)  # 2% per trade (compounding)
    max_setups_per_session: int = _i("PB_MAX_SETUPS_PER_SESSION", 2)      # 2 trades/day max
    use_micros: bool = os.environ.get("PB_USE_MICROS", "true").lower() != "false"
    # Reward:risk band for targets (1:1 .. 1:3).
    min_rr: float = _f("PB_MIN_RR", 1.0)
    tp_max_r: float = _f("PB_TP_MAX_R", 3.0)
    # A+ gate: never take a setup below 75% confluence.
    confluence_threshold: float = max(_f("PB_CONFLUENCE_THRESHOLD", 0.75), 0.75)
    # Realistic cost model: per-side slippage in ticks (commission is per-contract in CONTRACTS).
    slippage_ticks: float = _f("PB_SLIPPAGE_TICKS", 1.0)
    # Trade management: bank a partial + move to breakeven at scale_at_r, runner to target.
    trade_mgmt: bool = os.environ.get("PB_TRADE_MGMT", "true").lower() != "false"
    scale_at_r: float = _f("PB_SCALE_AT_R", 1.0)
    scale_frac: float = _f("PB_SCALE_FRAC", 0.5)

    @property
    def risk_is_aggressive(self) -> bool:
        return self.risk_pct > RISK_WARN_THRESHOLD

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
