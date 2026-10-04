import csv
import io
import os
import re
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import httpx

from . import db
from .checker import check_many
from .sources.base import Area
from .sources import google_places as gp
from .sources.osm import CATEGORIES, OsmSource, resolve_areas

load_dotenv()
WEB_DIR = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(title="local-business-lead-finder")

SiteStatus = Literal["unchecked", "none", "dead", "social_only", "alive"]
ContactStatus = Literal["new", "called", "interested", "not_interested", "do_not_call"]

CSV_COLUMNS = ["name", "category", "area", "phone", "address", "opening_hours", "website_url",
               "manual_phone", "site_status", "no_site_verified", "http_status", "check_error", "contact_status",
               "notes", "lat", "lon"]


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


class Filters:
    def __init__(self, area: str | None = None, category: str | None = None,
                 site_status: SiteStatus | None = None, contact_status: ContactStatus | None = None,
                 q: str | None = None, leads_only: bool = False, has_phone: bool = False,
                 verified: bool = False, sort: str | None = None, desc: bool = False):
        self.kwargs = dict(area=area or None, category=category or None, site_status=site_status,
                           contact_status=contact_status, search=q or None, leads_only=leads_only,
                           has_phone=has_phone, verified=verified, sort=sort, descending=desc)


class ContactUpdate(BaseModel):
    notes: str | None = None
    contact_status: ContactStatus | None = None
    manual_phone: str | None = Field(default=None, max_length=40)
    no_site_verified: bool | None = None


class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(default="", max_length=500)
    osm_type: Literal["node", "way", "relation"]
    osm_id: int
    lat: float
    lon: float
    place_type: str = Field(default="", max_length=50)
    bbox: tuple[float, float, float, float] | None = None


class ScanIn(BaseModel):
    area: AreaIn
    category: str
    radius: int = Field(default=1500, ge=100, le=5000)


@app.get("/api/categories")
def categories():
    return list(CATEGORIES)


@app.get("/api/resolve")
def resolve(name: str = Query(min_length=2, max_length=100), hint: str | None = Query(default=None, max_length=100)):
    """Candidate places for a name. The user picks one (same ambiguity step as the CLI)."""
    try:
        areas = resolve_areas(name, hint or None)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Η αναζήτηση ονόματος απέτυχε: {e}")
    return [{**a.__dict__, "has_boundary": a.has_boundary} for a in areas]


@app.post("/api/scan")
def scan(body: ScanIn, conn=Depends(get_conn)):
    """Scan ONE category (the UI loops over categories to show progress)."""
    if body.category not in CATEGORIES:
        raise HTTPException(422, "Άγνωστη κατηγορία")
    area = Area(**body.area.model_dump())
    try:
        found = OsmSource(radius=body.radius).search(area, body.category)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ο Overpass server δεν απάντησε σωστά: {e}")
    counts = db.save_scan(conn, area.name, body.category, "osm", found)
    return {"category": body.category, "found": len(found), **counts}


@app.get("/api/check/pending")
def pending_checks(conn=Depends(get_conn)):
    return {"pending": len(db.businesses_to_check(conn))}


@app.post("/api/check")
async def run_checks():
    # Own connection: this endpoint runs on the event-loop thread, and a sqlite3
    # connection can only be used in the thread that created it.
    conn = db.connect()
    try:
        rows = db.businesses_to_check(conn)
        results = await check_many({r["id"]: r["website_url"] for r in rows}, concurrency=5)
        summary: dict[str, int] = {}
        with conn:
            for r in rows:
                res = results[r["id"]]
                db.save_check(conn, r["id"], res.site_status, res.http_status, res.error)
                summary[res.site_status] = summary.get(res.site_status, 0) + 1
        return {"checked": len(rows), **summary}
    finally:
        conn.close()


class GoogleSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=100)
    area: AreaIn
    radius: int = Field(default=1500, ge=100, le=5000)
    grid: Literal[1, 2, 3] = 1


class GoogleLeadUpdate(ContactUpdate):
    pass


PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


@app.get("/api/google/status")
def google_status(conn=Depends(get_conn)):
    return {
        "configured": bool(os.getenv("GOOGLE_PLACES_API_KEY")),
        "calls_this_month": db.get_usage(conn, gp.month_key()),
        "limit": gp.monthly_limit(),
    }


@app.post("/api/google/search")
def google_search(body: GoogleSearchIn, conn=Depends(get_conn)):
    """Live Google search. Results are NOT stored: only place_id + our own fields live in the DB."""
    key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        raise HTTPException(400, "Λείπει το GOOGLE_PLACES_API_KEY από το .env")
    area = Area(**body.area.model_dump())
    # For a point place (a suburb is only a point in OSM) we use a square of `radius` around it.
    bbox = area.bbox if area.has_boundary and area.bbox else gp.bbox_from_point(area.lat, area.lon, body.radius)
    client = gp.GooglePlacesClient(key, conn)
    try:
        places, partial = client.search(body.query, bbox, body.grid)
    except gp.GoogleApiError as e:
        raise HTTPException(502, str(e))
    if partial and not places:
        raise HTTPException(429, f"Έφτασες το μηνιαίο όριο των {client.limit} κλήσεων.")

    own = db.get_google_leads(conn, [p.place_id for p in places])
    results = []
    for p in places:
        mine = own.get(p.place_id)
        if mine and mine["contact_status"] == "do_not_call":
            continue  # never show a do-not-call business as a lead again
        results.append({
            **p.__dict__,
            "site_status": gp.lead_status(p.website_url),
            "notes": mine["notes"] if mine else None,
            "contact_status": mine["contact_status"] if mine else "new",
            "manual_phone": mine["manual_phone"] if mine else None,
            "no_site_verified": mine["no_site_verified"] if mine else 0,
        })
    return {
        "results": results, "partial": partial, "calls_used_now": client.calls_made,
        "calls_this_month": client.calls_this_month(), "limit": client.limit,
    }


@app.patch("/api/google/leads/{place_id}")
def update_google_lead(place_id: str, body: ContactUpdate, conn=Depends(get_conn)):
    if not PLACE_ID_RE.match(place_id):
        raise HTTPException(422, "Μη έγκυρο place_id")
    with conn:
        db.update_google_lead(conn, place_id, body.notes, body.contact_status,
                              body.manual_phone, body.no_site_verified)
    return {"ok": True}


@app.get("/api/filters")
def filters(conn=Depends(get_conn)):
    return {"areas": db.distinct_values(conn, "area"), "categories": db.distinct_values(conn, "category")}


@app.get("/api/businesses")
def businesses(f: Filters = Depends(), conn=Depends(get_conn)):
    return [dict(r) for r in db.list_businesses(conn, **f.kwargs)]


@app.patch("/api/businesses/{business_id}")
def update_business(business_id: int, body: ContactUpdate, conn=Depends(get_conn)):
    with conn:
        found = db.update_contact(
            conn, business_id, body.notes, body.contact_status, body.manual_phone, body.no_site_verified
        )
    if not found:
        raise HTTPException(404, "Business not found")
    return {"ok": True}


def csv_safe(value) -> str:
    """Stop spreadsheet apps from running a cell as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@app.get("/api/export.csv")
def export_csv(f: Filters = Depends(), conn=Depends(get_conn)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for r in db.list_businesses(conn, **f.kwargs):
        writer.writerow([csv_safe(r[c]) for c in CSV_COLUMNS])
    # BOM so Excel reads the Greek text as UTF-8
    return Response(
        "﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/google")
def google_page():
    return FileResponse(WEB_DIR / "google.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
