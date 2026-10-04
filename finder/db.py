import os
import sqlite3
from datetime import datetime, timezone

from .sources.base import Business

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    area TEXT,
    address TEXT,
    phone TEXT,
    website_url TEXT,
    opening_hours TEXT,
    lat REAL,
    lon REAL,
    site_status TEXT NOT NULL DEFAULT 'unchecked'
        CHECK (site_status IN ('unchecked','none','dead','social_only','alive')),
    http_status INTEGER,
    check_error TEXT,
    site_checked_at TEXT,
    contact_status TEXT NOT NULL DEFAULT 'new'
        CHECK (contact_status IN ('new','called','interested','not_interested','do_not_call')),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    result_count INTEGER NOT NULL
);
"""

# Fields refreshed from the source on every re-scan. Our own fields
# (contact_status, notes, check results) are never touched by a scan.
SOURCE_FIELDS = ("name", "address", "phone", "website_url", "opening_hours", "lat", "lon")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or os.getenv("DB_PATH", "site_finder.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def initial_status(website_url: str | None) -> str:
    return "unchecked" if website_url and website_url.strip() else "none"


def upsert_business(conn: sqlite3.Connection, b: Business) -> str:
    """Insert or refresh one business. Returns 'new', 'updated' or 'unchanged'."""
    website = (b.website_url or "").strip() or None
    row = conn.execute(
        "SELECT * FROM businesses WHERE source = ? AND source_id = ?", (b.source, b.source_id)
    ).fetchone()

    if row is None:
        conn.execute(
            """INSERT INTO businesses
               (source, source_id, name, category, area, address, phone, website_url,
                opening_hours, lat, lon, site_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (b.source, b.source_id, b.name, b.category, b.area, b.address, b.phone, website,
             b.opening_hours, b.lat, b.lon, initial_status(website), now(), now()),
        )
        return "new"

    new_values = {
        "name": b.name, "address": b.address, "phone": b.phone, "website_url": website,
        "opening_hours": b.opening_hours, "lat": b.lat, "lon": b.lon,
    }
    if all(row[f] == new_values[f] for f in SOURCE_FIELDS):
        return "unchanged"

    updates = dict(new_values)
    if website != row["website_url"]:
        # The URL changed, so any earlier check result no longer applies.
        updates.update(
            site_status=initial_status(website), http_status=None,
            check_error=None, site_checked_at=None,
        )
    updates["updated_at"] = now()
    assignments = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE businesses SET {assignments} WHERE id = ?", (*updates.values(), row["id"])
    )
    return "updated"


def save_scan(conn: sqlite3.Connection, area: str, category: str, source: str,
              businesses: list[Business]) -> dict[str, int]:
    started = now()
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    with conn:  # one transaction: all or nothing
        for b in businesses:
            counts[upsert_business(conn, b)] += 1
        conn.execute(
            "INSERT INTO scans (area, category, source, started_at, result_count) VALUES (?, ?, ?, ?, ?)",
            (area, category, source, started, len(businesses)),
        )
    return counts


def list_businesses(conn: sqlite3.Connection, area: str | None = None, category: str | None = None,
                    site_status: str | None = None, include_do_not_call: bool = False) -> list[sqlite3.Row]:
    where, params = [], []
    if area:
        where.append("area = ?"); params.append(area)
    if category:
        where.append("category = ?"); params.append(category)
    if site_status:
        where.append("site_status = ?"); params.append(site_status)
    if not include_do_not_call:
        where.append("contact_status != 'do_not_call'")
    sql = "SELECT * FROM businesses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return conn.execute(sql + " ORDER BY area, category, name", params).fetchall()
