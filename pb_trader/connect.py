"""Connection verifier for Databento (data) and Tradovate (execution).

Run AFTER putting your keys in .env. Each check authenticates and does the smallest
possible real call, then prints PASS/FAIL. No secrets are printed.

    python -m pb_trader.connect databento
    python -m pb_trader.connect tradovate
    python -m pb_trader.connect all
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from .config import settings


def _ok(msg: str) -> None:
    print(f"  \033[92mPASS\033[0m  {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[91mFAIL\033[0m  {msg}")


def check_databento(symbol: str = "ES") -> bool:
    print("\nDatabento (market data)")
    if not settings.databento_api_key:
        _fail("DATABENTO_API_KEY is empty — add it to .env")
        return False
    try:
        import databento  # noqa: F401
    except ImportError:
        _fail("databento package not installed — run: pip install 'pb-trader[databento]'")
        return False
    try:
        from .data.databento_source import DatabentoSource
        src = DatabentoSource()
        _ok(f"authenticated to dataset {settings.databento_dataset}")
        # Smallest meaningful pull: ~1 day of hourly bars, ending recently.
        end = datetime.utcnow().date()
        start = end - timedelta(days=4)
        bars = src.history(symbol, start=str(start), end=str(end), timeframe="1h")
        if not bars:
            _fail("auth OK but no bars returned — check symbol/date range/entitlement")
            return False
        _ok(f"pulled {len(bars)} {symbol} 1h bars; latest close "
            f"{bars[-1].close:.2f} @ {bars[-1].ts}")
        return True
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return False


def check_tradovate() -> bool:
    print("\nTradovate (execution)")
    if not settings.tradovate_configured:
        _fail("TRADOVATE_* creds incomplete — fill username/password/cid/secret in .env")
        return False
    try:
        import requests  # noqa: F401
    except ImportError:
        _fail("requests not installed — run: pip install 'pb-trader[tradovate]'")
        return False
    try:
        from .execution.tradovate import TradovateClient
        client = TradovateClient()
        print(f"  ...  environment: {settings.tradovate_env} ({client.base})")
        client.ensure_auth()
        _ok("access token acquired")
        if client.account_id:
            _ok(f"account loaded (id {client.account_id})")
        else:
            _fail("authed but no trading account found on this login")
            return False
        if settings.tradovate_env == "live":
            print("  \033[93mNOTE\033[0m  TRADOVATE_ENV=live — real-money endpoint. "
                  "Use 'demo' until paper-validated.")
        return True
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return False


def main() -> None:
    p = argparse.ArgumentParser(description="Verify data/broker connections")
    p.add_argument("target", choices=["databento", "tradovate", "all"], default="all",
                   nargs="?")
    p.add_argument("--symbol", default="ES")
    args = p.parse_args()

    results = []
    if args.target in ("databento", "all"):
        results.append(check_databento(args.symbol))
    if args.target in ("tradovate", "all"):
        results.append(check_tradovate())

    print()
    if all(results):
        print("All checks PASSED. You're wired up.")
        sys.exit(0)
    print("Some checks failed — see messages above.")
    sys.exit(1)


if __name__ == "__main__":
    main()
