"""HTTP-level tests for FdsnAdapter using respx to mock httpx responses.

These verify the *interaction* with FDSN servers: that we send the right URL
params, handle 204 / 4xx correctly, and follow redirects.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from src.adapters.fdsn import FdsnAdapter


STD_BODY = (
    "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|"
    "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName\n"
    "us6000sze1|2026-05-22T01:06:52.614|16.5411|-46.5899|10.0|us|us||"
    "us6000sze1|mww|5.1|us|northern Mid-Atlantic Ridge\n"
)


@respx.mock
async def test_fdsn_query_sends_expected_params_and_parses():
    route = respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, text=STD_BODY)
    )
    adapter = FdsnAdapter("USGS")
    async with httpx.AsyncClient() as client:
        reports = await adapter.query(
            client,
            start_time=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 22, 2, 0, tzinfo=timezone.utc),
            min_magnitude=4.5,
            min_latitude=-90.0,
            limit=50,
        )
    assert len(reports) == 1
    assert reports[0].source_event_id == "us6000sze1"

    # Verify our request shape.
    req = route.calls.last.request
    params = dict(req.url.params)
    assert params["format"] == "text"
    assert params["starttime"] == "2026-05-22T00:00:00"
    assert params["endtime"] == "2026-05-22T02:00:00"
    assert params["minmagnitude"] == "4.5"
    assert params["minlatitude"] == "-90.0"
    assert params["limit"] == "50"


@respx.mock
async def test_fdsn_query_204_returns_empty():
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(204)
    )
    adapter = FdsnAdapter("USGS")
    async with httpx.AsyncClient() as client:
        reports = await adapter.query(
            client,
            start_time=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 22, 2, 0, tzinfo=timezone.utc),
        )
    assert reports == []


@respx.mock
async def test_fdsn_query_5xx_returns_empty():
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(503)
    )
    adapter = FdsnAdapter("USGS")
    async with httpx.AsyncClient() as client:
        reports = await adapter.query(
            client,
            start_time=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 22, 2, 0, tzinfo=timezone.utc),
        )
    assert reports == []


@respx.mock
async def test_fdsn_query_follows_redirect():
    """RESIF redirects ws.resif.fr → api.franceseisme.fr — make sure we follow."""
    respx.get("https://api.franceseisme.fr/fdsnws/event/1/query").mock(
        return_value=httpx.Response(
            302,
            headers={"Location": "https://new.example.com/fdsnws/event/1/query"},
        )
    )
    respx.get("https://new.example.com/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, text=STD_BODY)
    )
    adapter = FdsnAdapter("RESIF")
    async with httpx.AsyncClient() as client:
        reports = await adapter.query(
            client,
            start_time=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 5, 22, 2, 0, tzinfo=timezone.utc),
        )
    assert len(reports) == 1


@respx.mock
async def test_fdsn_get_by_id_uses_geojson():
    geo = {
        "type": "Feature",
        "id": "us6000sze1",
        "geometry": {"type": "Point", "coordinates": [-46.5899, 16.5411, 10]},
        "properties": {
            "mag": 5.1,
            "place": "northern Mid-Atlantic Ridge",
            "time": 1779412012614,
            "magType": "mww",
            "status": "reviewed",
        },
    }
    route = respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, content=json.dumps(geo).encode()),
    )
    adapter = FdsnAdapter("USGS")
    async with httpx.AsyncClient() as client:
        r = await adapter.get_by_id(client, "us6000sze1")
    assert r is not None
    assert r.magnitude == 5.1
    # Verify the request used format=geojson, not format=text.
    params = dict(route.calls.last.request.url.params)
    assert params["format"] == "geojson"
    assert params["eventid"] == "us6000sze1"


@respx.mock
async def test_fdsn_get_by_id_empty_body_returns_none():
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, content=b""),
    )
    adapter = FdsnAdapter("USGS")
    async with httpx.AsyncClient() as client:
        r = await adapter.get_by_id(client, "us6000sze1")
    assert r is None


@respx.mock
async def test_fdsn_get_by_id_feature_collection_with_one_event():
    """Some FDSN servers return a FeatureCollection even for a single-event query."""
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "id": "abc",
            "geometry": {"type": "Point", "coordinates": [10, 20, 5]},
            "properties": {"mag": 3.0, "time": 1779412012614, "magType": "ml", "place": "X"},
        }],
    }
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, content=json.dumps(fc).encode())
    )
    adapter = FdsnAdapter("USGS")
    async with httpx.AsyncClient() as client:
        r = await adapter.get_by_id(client, "abc")
    assert r is not None
    assert r.source_event_id == "abc"
    assert r.magnitude == 3.0
