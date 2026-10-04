# local-business-lead-finder

A personal tool that scans a geographic area and finds local businesses (cafes, shops, pharmacies, ...) that have **no website** or a **dead website**. Those businesses are potential customers for a web developer, so the tool turns public map data into a call list.

> Status: work in progress (Phase 2 of 5 done). See [Roadmap](#roadmap).

## How it works

1. **Collect** – for an area and a business category, fetch businesses (name, phone, address, opening hours, website, coordinates) from OpenStreetMap via the Overpass API.
2. **Filter 1** – no website listed → `site_status = none`.
3. **Filter 2** – a website is listed → send an HTTP request to check it:
   - does not respond properly (DNS/TLS/connection error, timeout, 4xx/5xx) → `dead`
   - only a social page (facebook.com, instagram.com, linktr.ee, ...) → `social_only`
   - otherwise → `alive` (not a lead)
4. **Dashboard** – a small web UI listing leads per area and category, with phone numbers (click-to-call), call notes, contact status and CSV export. The UI text is in Greek.

## Tech stack

- Python 3.11+, `httpx` (async HTTP), FastAPI + uvicorn, SQLite
- Plain HTML and a little vanilla JS for the dashboard, no build tooling
- Config via `.env` (see `.env.example`)

## Design notes

- **Polite data access:** descriptive User-Agent, spaced-out requests and local caching of raw Overpass responses, so the public server is not hammered.
- **Safe checker:** limited concurrency, timeouts and one retry. It only does a normal HTTP request to public websites, with no port scanning or vulnerability probing.
- **Pluggable sources:** every data source implements the same interface, so Google Places can be added later next to OSM.
- **Opt-out respected:** a `do_not_call` flag keeps anyone who asks not to be contacted out of the lead list for good.
- **Missing is not proof:** a business without a website in OSM may still have one, so the dashboard links to a Google search to verify before calling.

## Roadmap

- [x] Phase 0: project skeleton
- [x] Phase 1: OSM/Overpass source and CLI `scan`
- [x] Phase 2: SQLite storage and deduplication
- [ ] Phase 3: website checker and CLI `check`
- [ ] Phase 4: FastAPI dashboard with filters, notes and CSV export
- [ ] Phase 5 (optional): Google Places API as a second source

## Setup

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest
```

## Data attribution

Business data © OpenStreetMap contributors, available under the [ODbL](https://opendatacommons.org/licenses/odbl/).

## Usage

```
python -m finder.cli scan --area "Πεύκα" --category cafe --hint Θεσσαλονίκη
```

Results are saved to SQLite (deduplicated by source and source id; your notes and contact status survive re-scans). Other commands:

```
python -m finder.cli scan --area "Πεύκα" --category cafe --hint Θεσσαλονίκη --no-save
python -m finder.cli list --status none
```

If a name matches several places, the candidates are listed and you narrow down with `--hint` or `--pick N`.
