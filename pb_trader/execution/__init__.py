"""Execution / broker adapters."""
from .base import Broker
from .paper import PaperBroker

__all__ = ["Broker", "PaperBroker", "get_broker"]


def get_broker(mode: str, **kwargs) -> Broker:
    """Factory. 'paper' -> simulator; 'live' -> Tradovate (guarded by config)."""
    mode = (mode or "paper").lower()
    if mode == "paper":
        return PaperBroker(**kwargs)
    if mode in ("live", "tradovate"):
        from .tradovate import TradovateBroker
        return TradovateBroker(**kwargs)
    raise ValueError(f"unknown execution mode: {mode}")
