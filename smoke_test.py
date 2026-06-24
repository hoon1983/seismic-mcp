"""Quick end-to-end smoke test: hits real USGS+EMSC, prints reconciled output."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.adapters.fdsn import FdsnAdapter
from src.tools.find_events import find_events


async def probe_one(agency: str, start, end, min_mag):
    async with httpx.AsyncClient(http2=True) as c:
        a = FdsnAdapter(agency)
        reports = await a.query(c, start_time=start, end_time=end, min_magnitude=min_mag, limit=20)
        print(f"[{agency}] returned {len(reports)} reports")
        for r in reports[:3]:
            print(
                f"  {r.time_utc.isoformat()} M{r.magnitude}{r.magnitude_type or ''} "
                f"@({r.latitude:.2f},{r.longitude:.2f}) id={r.source_event_id} region={r.region_name}"
            )


async def main():
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    print(f"--- Probing individual adapters: {start.isoformat()} -> {end.isoformat()} ---")
    for ag in ("USGS", "EMSC"):
        await probe_one(ag, start, end, 4.5)

    print("\n--- find_events (last 24h, M>=4.5) ---")
    events = await find_events(start_time=start, end_time=end, min_magnitude=4.5, limit=15)
    print(f"Got {len(events)} reconciled events.\n")
    for e in events[:10]:
        p = e.prime_report
        print(
            f"- {p.time_utc.isoformat()} | M{p.magnitude}{p.magnitude_type or ''} "
            f"@({p.latitude:.2f},{p.longitude:.2f}) depth={p.depth_km}km "
            f"prime={p.agency} agencies={sorted(e.magnitudes_by_agency.keys())} "
            f"mag_spread={e.magnitude_spread} loc_spread_km={e.location_spread_km and round(e.location_spread_km,1)} "
            f"local_auth={e.local_authority_agency} disagree={e.reports_disagree}"
        )
        print(f"  region: {p.region_name}")


if __name__ == "__main__":
    asyncio.run(main())
