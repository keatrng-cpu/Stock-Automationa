"""Market data sources."""
from .base import DataSource
from .synthetic import SyntheticSource

__all__ = ["DataSource", "SyntheticSource", "get_source"]


def get_source(name: str, **kwargs) -> DataSource:
    """Factory: resolve a data source by name, importing heavy deps lazily."""
    name = (name or "synthetic").lower()
    if name == "synthetic":
        return SyntheticSource(**kwargs)
    if name == "neutral":
        from .neutral import NeutralSource
        return NeutralSource(**kwargs)
    if name == "adversarial":
        from .adversarial import AdversarialSource
        return AdversarialSource(**kwargs)
    if name == "csv":
        from .csv_source import CSVSource
        return CSVSource(**kwargs)
    if name == "databento":
        from .databento_source import DatabentoSource
        return DatabentoSource(**kwargs)
    if name == "tradovate":
        from .tradovate_source import TradovateSource
        return TradovateSource(**kwargs)
    raise ValueError(f"unknown data source: {name}")
