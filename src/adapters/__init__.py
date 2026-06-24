"""Adapter registry: maps an agency code to its adapter instance.

Adding a new agency:
  1. Implement an adapter exposing `agency: str`, `async query(...)`, and
     `async get_by_id(...)` (the latter may return None if unsupported).
  2. Register it below in either FDSN_AGENCIES (via fdsn.py) or
     CUSTOM_ADAPTER_FACTORIES.
"""

from __future__ import annotations

from typing import Callable

from .afad import AfadAdapter
from .base import SeismicAdapter
from .fdsn import FDSN_AGENCIES, FdsnAdapter
from .imo import ImoAdapter
from .jma import JmaAdapter

# Code -> zero-arg factory. Keep these as factories (not pre-built instances)
# so each find_events call gets a fresh adapter, matching FDSN's pattern.
CUSTOM_ADAPTER_FACTORIES: dict[str, Callable[[], SeismicAdapter]] = {
    "AFAD": AfadAdapter,
    "JMA": JmaAdapter,
    "IMO": ImoAdapter,
}


def supported_agencies() -> set[str]:
    """All agency codes for which we have a working adapter (FDSN or custom)."""
    return set(FDSN_AGENCIES.keys()) | set(CUSTOM_ADAPTER_FACTORIES.keys())


def make_adapter(code: str) -> SeismicAdapter:
    if code in FDSN_AGENCIES:
        return FdsnAdapter(code)
    if code in CUSTOM_ADAPTER_FACTORIES:
        return CUSTOM_ADAPTER_FACTORIES[code]()
    raise ValueError(f"No adapter for agency: {code}")


__all__ = [
    "FDSN_AGENCIES",
    "FdsnAdapter",
    "CUSTOM_ADAPTER_FACTORIES",
    "supported_agencies",
    "make_adapter",
]
