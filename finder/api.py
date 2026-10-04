import csv
import io
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db

load_dotenv()
WEB_DIR = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(title="local-business-lead-finder")

SiteStatus = Literal["unchecked", "none", "dead", "social_only", "alive"]
ContactStatus = Literal["new", "called", "interested", "not_interested", "do_not_call"]

CSV_COLUMNS = ["name", "category", "area", "phone", "address", "opening_hours", "website_url",
               "site_status", "http_status", "check_error", "contact_status", "notes", "lat", "lon"]


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


class Filters:
    def __init__(self, area: str | None = None, category: str | None = None,
                 site_status: SiteStatus | None = None, contact_status: ContactStatus | None = None,
                 q: str | None = None, leads_only: bool = False):
        self.kwargs = dict(area=area or None, category=category or None, site_status=site_status,
                           contact_status=contact_status, search=q or None, leads_only=leads_only)


class ContactUpdate(BaseModel):
    notes: str | None = None
    contact_status: ContactStatus | None = None


@app.get("/api/filters")
def filters(conn=Depends(get_conn)):
    return {"areas": db.distinct_values(conn, "area"), "categories": db.distinct_values(conn, "category")}


@app.get("/api/businesses")
def businesses(f: Filters = Depends(), conn=Depends(get_conn)):
    return [dict(r) for r in db.list_businesses(conn, **f.kwargs)]


@app.patch("/api/businesses/{business_id}")
def update_business(business_id: int, body: ContactUpdate, conn=Depends(get_conn)):
    with conn:
        found = db.update_contact(conn, business_id, body.notes, body.contact_status)
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


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
