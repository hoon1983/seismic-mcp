"""Tests for the regional-authority bbox lookup."""

from __future__ import annotations

from src.authorities import authority_for


def test_authority_for_japan_returns_jma():
    # Tokyo
    assert authority_for(35.68, 139.69) == "JMA"


def test_authority_for_italy_returns_ingv():
    # Rome
    assert authority_for(41.90, 12.50) == "INGV"


def test_authority_for_turkey_returns_afad():
    # Ankara
    assert authority_for(39.93, 32.86) == "AFAD"


def test_authority_for_iceland_returns_imo():
    # Reykjavík
    assert authority_for(64.13, -21.94) == "IMO"


def test_authority_for_canada_returns_nrcan():
    # Whitehorse, YT
    assert authority_for(60.72, -135.05) == "NRCAN"


def test_smallest_bbox_wins_for_overlap():
    """California overlaps both NCEDC (~35-42°N) and SCEDC (~32-37°N).
    The 35-37° band is in both bboxes; the smaller bbox should win."""
    # Lat=36, Lon=-120 → falls in NCEDC bbox (-125..-119, 35..42)
    # and also in SCEDC bbox? Actually -120 is outside SCEDC's -122..-114, so
    # this is only in NCEDC. Pick a point inside both.
    # NCEDC: -125..-119, 35..42  ;  SCEDC: -122..-114, 32..37
    # Overlap: -122..-119 lon, 35..37 lat.
    # Areas: NCEDC = 6*7 = 42 ; SCEDC = 8*5 = 40 → SCEDC is smaller, wins.
    assert authority_for(36.0, -120.5) == "SCEDC"


def test_authority_for_open_ocean_returns_none():
    # Middle of Pacific
    assert authority_for(0.0, -160.0) is None
