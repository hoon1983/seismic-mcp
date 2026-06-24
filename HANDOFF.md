# Handoff — seismic-mcp

State as of end-of-session. Read this first; everything you need to pick up is here.

## What this is

A Model Context Protocol server unifying real-time earthquake data from 20 seismic agencies. Same physical earthquake gets reported by multiple agencies under different event IDs with slightly different magnitudes and epicenters; this server queries them in parallel, clusters reports of the same event, and surfaces the disagreement so an LLM agent can see what one feed alone would hide.

## Current status: shippable, dogfooded

- **20 agencies wired and live-tested.** 17 via a generic FDSN-event adapter; 3 via hand-written custom adapters (JMA / AFAD / IMO).
- **7 MCP tools** exposed via FastMCP over stdio: `find_events`, `get_event`, `compare_sources`, `find_discrepancies`, `list_recent_by_agency`, `get_agency_info`, `list_agencies`.
- **57 unit tests, all passing** (~0.3 s). Covers parsers (with edge cases for NRCAN's 8-col format, SCEDC's `Longtitude` typo, JMA's `cod` field, AFAD's redirect, IMO's magnitude preference), matching, prime-selection, authorities lookup, reconciliation, and the TTL cache.
- **TTL cache (60 s)** with in-flight de-duplication. Default `find_events` queries every supported agency in parallel; with the cache, repeated queries are sub-100 ms.
- **Verified working in Claude Desktop.** The dogfood test prompt *"find me the latest earthquake with a discrepency"* returned a real cross-agency disagreement (Türkiye event with EMSC reporting M2.0 ml @ 7.0 km vs AFAD reporting M1.5 ML @ 5.1 km), and the agent stitched in `get_agency_info` on its own to label AFAD as "Turkey's national authority." Multi-tool integration works.
- **HTTP frontend** ([web.py](web.py) + [static/index.html](static/index.html)) on port 8765 for manual QA — query form, Leaflet map, side-by-side compare drawer, agency-info popovers, discrepancies-only toggle. **Not part of the MCP deliverable** — it's just a developer dashboard that exercises the same code paths the MCP tools do.

## Run commands

```bash
# MCP server (stdio, for Claude Desktop / Code)
uv run python server.py

# HTTP dashboard (port 8765, manual inspection)
uv run python web.py

# Tests
uv run pytest

# Stdio protocol smoke-test (not part of pytest suite)
uv run python tests/manual_stdio_probe.py
```

## Architecture

See [README.md](README.md) for the full map. Quick orientation:

- [server.py](server.py) — FastMCP entry point. Seven `@mcp.tool` decorators wrap thin functions in [src/tools/](src/tools/).
- [src/adapters/](src/adapters/) — One file per non-FDSN adapter ([afad.py](src/adapters/afad.py), [jma.py](src/adapters/jma.py), [imo.py](src/adapters/imo.py)) plus the generic [fdsn.py](src/adapters/fdsn.py) that handles 17 networks. [__init__.py](src/adapters/__init__.py) is the registry — `make_adapter(code)` and `supported_agencies()` are the public API.
- [src/reconcile.py](src/reconcile.py), [src/matching.py](src/matching.py), [src/prime_selection.py](src/prime_selection.py), [src/authorities.py](src/authorities.py) — pure-logic reconciliation pipeline. Heavily unit-tested.
- [src/cache.py](src/cache.py) — TTL cache with in-flight task de-dup.
- [data/](data/) — `agency_metadata.json` (23 entries, 20 with working adapters), `region_authorities.json` (bbox → authoritative agency), `known_aliases.json` (empty, manual fallback for matching).

## Important file paths (gotchas)

- **Claude Desktop config (UWP-sandboxed install):** `C:\Users\matt\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` — NOT the standard `%APPDATA%\Claude\` path. Microsoft Store version redirects writes. Already configured with the seismic server.
- **`uv` binary:** `C:\Users\matt\.local\bin\uv.exe`. UWP-sandboxed Claude Desktop doesn't inherit shell PATH, so the config uses this absolute path.
- **Repo:** `c:\Users\matt\seismic-mcp` (Windows path, but everything works under Git Bash too via `/c/Users/matt/seismic-mcp`).

## Non-obvious design decisions

These would be easy to undo without context:

1. **FDSN parser is header-aware.** It reads the `#col1|col2|...` header line and maps columns by name. Don't switch back to fixed-column parsing — NRCAN returns only 8 columns, SCEDC has a `Longtitude` typo, and some agencies omit columns. See [src/adapters/fdsn.py](src/adapters/fdsn.py) `_parse_header` / `_HEADER_ALIASES`.
2. **`get_by_id` uses GeoJSON, not text.** USGS returns empty body for `format=text&eventid=X`. We use `format=geojson` instead. Don't "fix" this back to text — it'll silently break `get_event` and `compare_sources`.
3. **`find_events` and `get_event` both default to ALL 20 agencies.** `find_events` used to query only USGS+EMSC, `get_event` used USGS+EMSC+regional-authority+seed — both were widened. Querying everything is OK because the TTL cache absorbs repeat traffic and per-adapter timeouts cap the wait at ~10 s. If revisited, don't shrink the default back without also fixing the underlying problem (cross-agency reconciliation requires multiple agencies to be queried).
4. **AFAD adapter sets `follow_redirects=True`.** Their public URL 302s through to a different host. Same for RESIF.
5. **`is_reviewed` boolean is filtered out of numeric spread in compare_sources.** Python's `bool` is a subclass of `int`, so `True/False` would otherwise be summed as `1.0`/`0.0`.
6. **The connection pool size scales with the number of adapters** (`max_connections=max(len(agency_set)+4, 20)`) so all 20 can run in parallel without queueing.
7. **Adapter timeout is 10s** (was 15s). Caps worst-case wait when a slow agency hangs.
8. **`tests/manual_stdio_probe.py`** is intentionally not part of the pytest suite — it spawns a real subprocess and shells out, so it lives separately.

## Agencies: what's wired, what was tried and dropped, what's possible

**Working (20):**
- FDSN: USGS, EMSC, IRIS, GFZ, INGV, GeoNet, NOA, IPGP, NCEDC, SCEDC, SED, ISC, BMKG, NIEP, RESIF, KNMI, NRCAN.
- Custom: JMA, AFAD, IMO.

**Intentionally dropped (don't re-add without a working endpoint):**
- KOERI (Boğaziçi) — `eida.koeri.boun.edu.tr/fdsnws/event/` returns 404; runs SeisComP-FDSNWS for stations only.
- BGR (Germany federal) — same: 404 on the event service.
- BGS UK, ICGC Catalonia, LMU München — 204 (empty catalog, endpoint healthy but no events).
- GA Australia — SPA portal that returns the same HTML for every URL; no scriptable API found.
- CSN Chile (sismologia.cl) — 403 Access Denied on all public JSON paths tried.
- SSN Mexico — 404/Access Denied on the candidate endpoints.
- NORSAR Norway, IPGP eida — timed out.

**Known limit:** BMKG (Indonesia) is in the registry but its host was unreachable from this network. Adapter handles failure gracefully; from a non-blocked network it should work.

## Open work (prioritized)

This is what the user and I were considering for the next session. I had recommended #1 followed by #2.

1. **Publish to PyPI.** Currently the Claude Desktop config has a hardcoded path. After publishing, the config becomes:
   ```json
   { "mcpServers": { "seismic": { "command": "uvx", "args": ["seismic-mcp"] } } }
   ```
   Steps:
   - Update [pyproject.toml](pyproject.toml): fill in `[project.urls]` (Homepage/Repository), confirm `authors` email, possibly bump version from `0.1.0` to `0.1.1` or `0.2.0`.
   - Confirm `seismic-mcp` is available on pypi.org.
   - `uv build` → wheel + sdist in `dist/`.
   - Get a PyPI token from the user → `uv publish --token …`.
   - Verify `uvx seismic-mcp` runs from a clean shell and registers all 7 tools.
   - Update Claude Desktop config and [README.md](README.md) to use `uvx seismic-mcp`.

2. **Just use it for a week.** The bugs that matter are the ones found by actually using it for real questions. Resist further building until something concrete surfaces.

3. **MCP resources.** Expose agencies as resources (`seismic://agency/USGS`, etc.) in addition to tools. Marginal value over `get_agency_info` but more idiomatically MCP — agents can browse them as a knowledge base.

4. **Harder agency adapters.** GA Australia, CSN Chile, SSN Mexico would each take ~1-2 hours of browser reverse-engineering and produce small-event coverage that USGS/EMSC already give us at M≥4.5. Low priority unless you specifically care about regional small-event coverage.

5. **Real-time / subscription.** MCP supports streaming notifications. Could push new events as they arrive. Speculative — needs a real use case.

6. **Items from the original README's "not yet built" list that are still TODO:**
   - **EMSC eventid mapping** — EMSC publishes cross-references between USGS/EMSC IDs. Would improve matching beyond the current spatiotemporal clustering. Marginal quality gain.
   - **Populate `known_aliases.json`** — currently `{}`. Manual fallback for famous events whose matching the clustering gets wrong. Cheap once you hit a bad case.
   - **Multi-authority per region** — KOERI alongside AFAD for Türkiye, for example. The current `region_authorities.json` maps a bbox to exactly one agency.

## Frontend caveat

The HTTP frontend ([web.py](web.py), [static/index.html](static/index.html)) is **not part of the MCP deliverable.** It exists for manual QA and dogfooding. If a future Claude is tempted to "polish the frontend," push back — the user's stated goal is the MCP server.

## Memory note

There are no user-memory entries from this session that need to be preserved into the next. All decisions are captured here or in the code.
