# seismic-mcp

A unified Model Context Protocol server for global seismic data. Queries 20 seismic agencies in parallel; matches cross-agency reports of the same event; surfaces magnitude and location discrepancies so AI agents can see what one feed alone would hide.

## Status

Working:

- **20 agencies wired up.** FDSN-event: USGS, EMSC, IRIS, INGV, GeoNet, GFZ, NOA, IPGP, NCEDC, SCEDC, ISC, SED, BMKG, NIEP, RESIF, KNMI, NRCAN. Custom (non-FDSN): JMA (Japan), AFAD (Türkiye), IMO (Iceland).
- **Cross-agency reconciliation.** Spatiotemporal clustering, prime-report selection (local authority > EMSC for Europe > USGS), discrepancy detection (magnitude/location/depth spread). Reviewed bulletins trump preliminary.
- **Seven MCP tools:** `find_events`, `get_event`, `compare_sources`, `find_discrepancies`, `list_recent_by_agency`, `get_agency_info`, `list_agencies`.
- **TTL cache** (60 s) with in-flight de-dup: repeated queries are sub-100 ms.
- **57 unit tests** covering parsers, matching, prime-selection, authorities, reconciliation, and cache.
- **HTTP frontend** for manual inspection: form + Leaflet map + side-by-side compare drawer.

Not yet built: EMSC eventid mapping (cross-references USGS/EMSC IDs for tighter matching), populated `known_aliases.json`, multi-region per-event authority (KOERI alongside AFAD for Türkiye).

## Safety

Reports earthquake data from multiple seismic agencies for research, journalism, situational awareness, and curiosity. It is NOT an early-warning system. All earthquake reports arrive AFTER shaking has already occurred where it was felt. For earthquake preparedness and emergency response, consult official local authorities (USGS ShakeAlert, JMA Earthquake Early Warning, etc.). Preliminary magnitudes and locations are routinely revised by reporting agencies; never make safety decisions based on a single reading.

## Run

### As an MCP server (Claude Desktop, VS Code, etc.)

```bash
uv sync
uv run python server.py
```

Add to `claude_desktop_config.json` — Windows path is `%APPDATA%\Claude\claude_desktop_config.json`, macOS `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "seismic": {
      "command": "uv",
      "args": ["--directory", "C:\\Users\\matt\\seismic-mcp", "run", "python", "server.py"]
    }
  }
}
```

Restart Claude Desktop. The tools appear under the seismic-mcp server in the tools menu.

### As a web frontend (manual inspection)

```bash
uv run python web.py
```

Then open <http://127.0.0.1:8765/>. Same code paths as the MCP server, just exposed over HTTP with a small UI.

### Tests

```bash
uv run pytest
```

## Architecture

```
server.py              FastMCP entry point — 7 @mcp.tool functions
web.py                 FastAPI HTTP wrapper around the same tools
src/
  schemas.py           Pydantic models: SourceReport, ReconciledEvent, ...
  adapters/
    base.py            SeismicAdapter protocol
    fdsn.py            Header-aware FDSN-event adapter (handles 17 networks)
    afad.py            Custom AFAD JSON adapter
    jma.py             Custom JMA list.json adapter
    imo.py             Custom IMO GeoJSON adapter
    __init__.py        Registry: make_adapter(code), supported_agencies()
  authorities.py       Regional-authority bbox lookup
  matching.py          Spatiotemporal clustering with mag-scaled thresholds
  prime_selection.py   Headline-report selection rules
  reconcile.py         Cluster → ReconciledEvent with spreads
  cache.py             TTL cache + in-flight de-dup
  tools/               One file per MCP tool
data/
  agency_metadata.json    Per-agency coverage, latency, notes
  region_authorities.json Region bboxes → authoritative agency
  known_aliases.json      (manual fallback for matching, currently {})
tests/                 pytest suite — 57 tests, fast (<1s)
static/index.html      Single-page UI for the HTTP frontend
```
