"""Local-authority lookup: which agency is regionally authoritative for a coordinate.

v1 uses bounding boxes (data/region_authorities.json). On overlap, the smaller
bbox wins — so INGV beats EMSC for Sicily even though EMSC's nominal coverage
is broader. v2 could swap in real polygons via Shapely.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "region_authorities.json"


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _bbox_area(bbox: list[float]) -> float:
    minlon, minlat, maxlon, maxlat = bbox
    return (maxlon - minlon) * (maxlat - minlat)


def _bbox_contains(bbox: list[float], lat: float, lon: float) -> bool:
    minlon, minlat, maxlon, maxlat = bbox
    return minlat <= lat <= maxlat and minlon <= lon <= maxlon


def authority_for(lat: float, lon: float) -> Optional[str]:
    """Return the agency code for the smallest bbox containing the point, or None."""
    matches = [entry for entry in _load() if _bbox_contains(entry["bbox"], lat, lon)]
    if not matches:
        return None
    matches.sort(key=lambda e: _bbox_area(e["bbox"]))
    return matches[0]["agency"]
