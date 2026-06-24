"""get_agency_info: static metadata about a seismic agency."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..adapters import CUSTOM_ADAPTER_FACTORIES
from ..adapters.fdsn import FDSN_AGENCIES
from ..schemas import AgencyInfo

_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "agency_metadata.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def list_agencies() -> list[str]:
    """All agency codes we know about (FDSN-wired or not)."""
    return sorted(_load().keys())


def get_agency_info(agency: str) -> Optional[AgencyInfo]:
    data = _load().get(agency)
    if data is None:
        return None
    fdsn_cfg = FDSN_AGENCIES.get(agency)
    adapter_supported = fdsn_cfg is not None or agency in CUSTOM_ADAPTER_FACTORIES
    return AgencyInfo(
        code=agency,
        full_name=data["full_name"],
        coverage=data["coverage"],
        is_authority_for=data.get("is_authority_for", []),
        magnitude_completeness=data["magnitude_completeness"],
        typical_latency_seconds=data["typical_latency_seconds"],
        notes=data["notes"],
        adapter_supported=adapter_supported,
        fdsn_base_url=fdsn_cfg.base_url if fdsn_cfg else None,
        event_page_template=fdsn_cfg.event_page if fdsn_cfg else None,
    )
