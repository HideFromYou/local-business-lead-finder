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
    manual_phone TEXT,
    no_site_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);

-- Google Places: we keep ONLY the place_id and our own fields, never Google's content.
CREATE TABLE IF NOT EXISTS google_leads (
    place_id TEXT PRIMARY KEY,
    notes TEXT,
    contact_status TEXT NOT NULL DEFAULT 'new'
        CHECK (contact_status IN ('new','called','interested','not_interested','do_not_call')),
    manual_phone TEXT,
    no_site_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Billable Google API calls per month (UTC), used for the hard monthly limit.
CREATE TABLE IF NOT EXISTS api_usage (
    month TEXT PRIMARY KEY,
    calls INTEGER NOT NULL DEFAULT 0
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
    # check_same_thread=False: FastAPI may run a request's dependency and endpoint on
    # different worker threads. Each request has its own connection, used one step at a time.
    conn = sqlite3.connect(path or os.getenv("DB_PATH", "site_finder.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


NEW_COLUMNS = {
    "manual_phone": "TEXT",
    "no_site_verified": "INTEGER NOT NULL DEFAULT 0",
}


def migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(businesses)")}
    for column, definition in NEW_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE businesses ADD COLUMN {column} {definition}")
    conn.commit()


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


LEAD_STATUSES = ("none", "dead", "social_only")
SORT_COLUMNS = {
    "name": "name COLLATE NOCASE",
    "area": "area COLLATE NOCASE",
    "category": "category",
    "site_status": "site_status",
    "contact_status": "contact_status",
    "phone": "COALESCE(NULLIF(manual_phone, ''), NULLIF(phone, ''))",
    "verified": "no_site_verified",
}
HAS_PHONE_SQL = "COALESCE(NULLIF(manual_phone, ''), NULLIF(phone, '')) IS NOT NULL"


def list_businesses(conn: sqlite3.Connection, area: str | None = None, category: str | None = None,
                    site_status: str | None = None, contact_status: str | None = None,
                    search: str | None = None, leads_only: bool = False,
                    has_phone: bool = False, verified: bool = False,
                    sort: str | None = None, descending: bool = False,
                    include_do_not_call: bool = False) -> list[sqlite3.Row]:
    """do_not_call rows are hidden unless asked for explicitly."""
    where, params = [], []
    if area:
        where.append("area = ?"); params.append(area)
    if category:
        where.append("category = ?"); params.append(category)
    if site_status:
        where.append("site_status = ?"); params.append(site_status)
    if contact_status:
        where.append("contact_status = ?"); params.append(contact_status)
    if leads_only:
        where.append(f"site_status IN ({', '.join('?' for _ in LEAD_STATUSES)})"); params.extend(LEAD_STATUSES)
    if has_phone:
        where.append(HAS_PHONE_SQL)
    if verified:
        where.append("no_site_verified = 1")
    if search:
        where.append("(name LIKE ? OR address LIKE ? OR phone LIKE ? OR manual_phone LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if not include_do_not_call and contact_status != "do_not_call":
        where.append("contact_status != 'do_not_call'")
    sql = "SELECT * FROM businesses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = "area, category, name"
    if sort in SORT_COLUMNS:  # whitelist: never put user input into SQL
        order = f"{SORT_COLUMNS[sort]} {'DESC' if descending else 'ASC'}, name COLLATE NOCASE"
    return conn.execute(f"{sql} ORDER BY {order}", params).fetchall()


def distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    assert column in ("area", "category")
    rows = conn.execute(f"SELECT DISTINCT {column} FROM businesses WHERE {column} IS NOT NULL ORDER BY {column}")
    return [r[0] for r in rows]


def update_contact(conn: sqlite3.Connection, business_id: int, notes: str | None = None,
                   contact_status: str | None = None, manual_phone: str | None = None,
                   no_site_verified: bool | None = None) -> bool:
    """Update only the fields that are given. Returns False if the business doesn't exist."""
    updates = {}
    if notes is not None:
        updates["notes"] = notes
    if contact_status is not None:
        updates["contact_status"] = contact_status
    if manual_phone is not None:
        updates["manual_phone"] = manual_phone.strip() or None
    if no_site_verified is not None:
        updates["no_site_verified"] = int(no_site_verified)
    if updates:
        updates["updated_at"] = now()
        assignments = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE businesses SET {assignments} WHERE id = ?", (*updates.values(), business_id))
    return conn.execute("SELECT 1 FROM businesses WHERE id = ?", (business_id,)).fetchone() is not None


def businesses_to_check(conn: sqlite3.Connection, area: str | None = None, category: str | None = None,
                        recheck: bool = False) -> list[sqlite3.Row]:
    where = ["website_url IS NOT NULL", "contact_status != 'do_not_call'"]
    params: list[str] = []
    if not recheck:
        where.append("site_status = 'unchecked'")
    if area:
        where.append("area = ?"); params.append(area)
    if category:
        where.append("category = ?"); params.append(category)
    return conn.execute(
        f"SELECT * FROM businesses WHERE {' AND '.join(where)} ORDER BY id", params
    ).fetchall()


def save_check(conn: sqlite3.Connection, business_id: int, site_status: str,
               http_status: int | None, error: str | None) -> None:
    conn.execute(
        """UPDATE businesses SET site_status = ?, http_status = ?, check_error = ?,
           site_checked_at = ?, updated_at = ? WHERE id = ?""",
        (site_status, http_status, error, now(), now(), business_id),
    )


def get_usage(conn: sqlite3.Connection, month: str) -> int:
    row = conn.execute("SELECT calls FROM api_usage WHERE month = ?", (month,)).fetchone()
    return row["calls"] if row else 0


def add_usage(conn: sqlite3.Connection, month: str, calls: int = 1) -> None:
    conn.execute(
        "INSERT INTO api_usage (month, calls) VALUES (?, ?) "
        "ON CONFLICT(month) DO UPDATE SET calls = calls + excluded.calls",
        (month, calls),
    )
    conn.commit()


def get_google_leads(conn: sqlite3.Connection, place_ids: list[str]) -> dict[str, sqlite3.Row]:
    if not place_ids:
        return {}
    marks = ", ".join("?" for _ in place_ids)
    rows = conn.execute(f"SELECT * FROM google_leads WHERE place_id IN ({marks})", place_ids).fetchall()
    return {r["place_id"]: r for r in rows}


def update_google_lead(conn: sqlite3.Connection, place_id: str, notes: str | None = None,
                       contact_status: str | None = None, manual_phone: str | None = None,
                       no_site_verified: bool | None = None) -> None:
    """Create the row on first edit, then update only the given fields."""
    stamp = now()
    conn.execute(
        "INSERT OR IGNORE INTO google_leads (place_id, created_at, updated_at) VALUES (?, ?, ?)",
        (place_id, stamp, stamp),
    )
    updates = {}
    if notes is not None:
        updates["notes"] = notes
    if contact_status is not None:
        updates["contact_status"] = contact_status
    if manual_phone is not None:
        updates["manual_phone"] = manual_phone.strip() or None
    if no_site_verified is not None:
        updates["no_site_verified"] = int(no_site_verified)
    if updates:
        updates["updated_at"] = stamp
        assignments = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE google_leads SET {assignments} WHERE place_id = ?", (*updates.values(), place_id))
