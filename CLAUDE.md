# Project: Local Business Site Finder

## Purpose
A personal tool that scans geographic areas I specify and finds local businesses (shops, cafes, pharmacies, etc.) that have **no website** or a **dead website**. I then phone them and offer to build a site. The tool is for my own use (single user, runs locally).

## About me / how to work with me
- I'm Nikos, based in Thessaloniki. I'm a junior pentester in training, comfortable with Linux/terminal basics, but still learning software engineering.
- Work in **small steps**. After each step: explain briefly what you did and why, tell me how to run it, and wait for my OK before starting the next phase.
- Ask before installing system-wide packages, deleting files, or running anything that makes many network requests.
- UI text in the dashboard must be in **Greek**. Code, comments, and commit messages in English.
- Keep it simple. No over-engineering, no frameworks I don't need.

## Workflow the tool implements
1. **Collect**: for a given area + business category, fetch businesses (name, phone, address, opening hours, website, coordinates) from a data source.
2. **Filter 1**: if the website field is empty/null -> save as `site_status = none`.
3. **Filter 2**: if there is a website, send an HTTP request to check it. If it does not respond properly -> `site_status = dead`. If it is only a social page (facebook.com, instagram.com, linktr.ee, etc.) -> `social_only`. Otherwise `alive` (and not a lead).
4. **Dashboard**: a small web UI listing leads per area/category with their status, phone number, and my own call notes.

## Stack (proposed, change only if you have a good reason)
- Python 3.11+, venv, `requirements.txt`
- `httpx` for HTTP, `FastAPI` + `uvicorn` for the backend, `SQLite` (via `sqlite3` or SQLAlchemy) for storage
- Frontend: plain HTML + a little vanilla JS (or htmx). No heavy build tooling.
- Config in `.env` (loaded with `python-dotenv`). `.env` MUST be in `.gitignore`. Never print or commit secrets.

## Suggested structure
```
finder/
  sources/          # one module per data source, same interface
    base.py         # abstract: search(area, category) -> list[Business]
    osm.py          # OpenStreetMap Overpass (first source, no API key)
    google_places.py# optional later (Places API New)
  checker.py        # website liveness check
  db.py             # schema + queries
  cli.py            # scan / check / list commands
  api.py            # FastAPI app for the dashboard
web/                # static dashboard
tests/
CLAUDE.md
.env.example
```

## Data model (SQLite)
`businesses`: id, source, source_id (unique per source), name, category, area, address, phone, website_url, opening_hours, lat, lon, site_status (`unchecked|none|dead|social_only|alive`), http_status, check_error, site_checked_at, contact_status (`new|called|interested|not_interested|do_not_call`), notes, created_at, updated_at.
`scans`: id, area, category, source, started_at, result_count.

## Phases (do ONE at a time, stop for review after each)
- **Phase 0**: project skeleton, venv, requirements, `.gitignore`, `.env.example`, git init.
- **Phase 1**: OSM/Overpass source + CLI `scan --area "Καλαμαριά" --category cafe`. Print results in the terminal. Resolve the area by name (e.g. admin boundary) and handle Greek names; show me how you resolved ambiguity.
- **Phase 2**: SQLite storage, dedupe by (source, source_id), `site_status = none` for empty websites.
- **Phase 3**: website checker (see rules below) + CLI `check`.
- **Phase 4**: FastAPI + dashboard with filters (area, category, status, contact_status), editable notes/contact status, click-to-call `tel:` links, export to CSV.
- **Phase 5 (optional)**: Google Places API (New) as a second source behind the same interface.

## Rules for the website checker
- Timeout ~10s, follow redirects, set a normal User-Agent, retry once on failure.
- Limit concurrency (e.g. 5-10 at once).
- `alive`: final response 2xx/3xx. `dead`: DNS failure, connection error, TLS error, timeout, 4xx/5xx. Record `http_status` and the error text.
- Normalize URLs (add `https://` if missing).
- Detect social-only links by hostname.
- Optional later: detect parked/expired-domain pages.

## Data source rules
- **Overpass (OSM)**: be polite: send a descriptive User-Agent, space out requests, cache raw responses locally while developing, do not hammer the public server. Data is ODbL: keep attribution "© OpenStreetMap contributors" in the dashboard footer. Missing `website` in OSM does not guarantee no site, so the dashboard should show a "search on Google" helper link per business to verify before calling.
- **Google Places (if added)**: use Places API (New) with a field mask asking only needed fields. Respect Google's terms: do not build a permanent copy of Google content; store the `place_id` and my own fields (status, notes) and re-fetch the rest when needed. Cap spending with a Google Cloud budget alert and a daily quota. Never scrape Google Maps HTML.

## Safety / legal notes
- No secrets in code or git. Provide `.env.example` only.
- Keep a `do_not_call` flag and respect it. These are B2B cold calls in Greece: if anyone asks not to be contacted, mark them and never show them as a lead again.
- This tool only reads public business listings and public websites. No port scanning, no vulnerability probing of the sites it checks.

## Definition of done for each phase
Runs from a clean venv, has at least a basic test where reasonable, and I know the exact command to run it.
