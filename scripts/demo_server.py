"""Run the dashboard with FICTIONAL data, no API keys and no network calls to Google/OSM.

    python scripts/demo_server.py            # then open http://127.0.0.1:8770/?q=φαρμακεία&area=Πεύκα&auto=1

Everything lives in a temporary database. Business names and phone numbers are made up.
(The map tiles are still loaded from OpenStreetMap by your browser.)
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "demo.db")
os.environ["GOOGLE_PLACES_API_KEY"] = "demo-not-a-real-key"

import uvicorn  # noqa: E402

from finder import api, db  # noqa: E402
from finder.sources import google_places as gp  # noqa: E402
from finder.sources.base import Area, Business  # noqa: E402

CENTER = (40.6566, 22.9895)
# name, dlat, dlon, phone, website, rating, rating_count, address
FAKE = [
    ("Φαρμακείο Παράδειγμα Α", 0.0012, -0.0021, "2310 000 101", None, 4.6, 48, "Οδός Δοκιμής 12"),
    ("Φαρμακείο Παράδειγμα Β", -0.0018, 0.0016, "2310 000 102", "https://facebook.com/example-b", 4.2, 17, "Οδός Δοκιμής 40"),
    ("Φαρμακείο Παράδειγμα Γ", 0.0031, 0.0009, None, None, 3.9, 6, "Λεωφ. Παραδείγματος 8"),
    ("Φαρμακείο Παράδειγμα Δ", -0.0007, -0.0034, "2310 000 104", "https://example-pharmacy-d.gr", 4.8, 112, "Λεωφ. Παραδείγματος 55"),
    ("Φαρμακείο Παράδειγμα Ε", 0.0022, 0.0035, "2310 000 105", None, 4.4, 31, "Οδός Δοκιμής 77"),
    ("Φαρμακείο Παράδειγμα ΣΤ", -0.0030, -0.0005, "2310 000 106", "https://instagram.com/example_f", 4.9, 64, "Οδός Δοκιμής 3"),
    ("Φαρμακείο Παράδειγμα Ζ", 0.0004, 0.0052, "2310 000 107", "https://example-pharmacy-g.gr", 4.1, 22, "Λεωφ. Παραδείγματος 101"),
    ("Φαρμακείο Παράδειγμα Η", -0.0041, 0.0028, "2310 000 108", None, 4.5, 39, "Οδός Δοκιμής 91"),
]


def _hours(open_h, close_h, days=(1, 2, 3, 4, 5, 6)):
    """Fictional weekday opening hours, in the same shape Google returns."""
    names = {0: "Κυριακή", 1: "Δευτέρα", 2: "Τρίτη", 3: "Τετάρτη", 4: "Πέμπτη", 5: "Παρασκευή", 6: "Σάββατο"}
    lines = [f"{names[d]}: {open_h}:00–{close_h}:00" if d in days else f"{names[d]}: Κλειστό" for d in (1, 2, 3, 4, 5, 6, 0)]
    periods = [{"open": {"day": d, "hour": open_h, "minute": 0}, "close": {"day": d, "hour": close_h, "minute": 0}} for d in days]
    return lines, periods


HOURS = [_hours(8, 21), _hours(9, 15, (1, 2, 3, 4, 5)), _hours(8, 23, (0, 1, 2, 3, 4, 5, 6)), _hours(10, 14),
         _hours(8, 21), _hours(9, 22, (0, 1, 2, 3, 4, 5, 6)), _hours(8, 15), _hours(17, 21)]


class FakeClient:
    """Stands in for GooglePlacesClient: same interface, fictional data, no network."""

    limit = 900

    def __init__(self, key, conn, **kw):
        self.conn, self.calls_made = conn, 0
        self.call_budget, self.stop_reason = None, ""

    def calls_this_month(self):
        return db.get_usage(self.conn, gp.month_key())

    def search(self, query, bbox, grid=1):
        self.calls_made = 2
        db.add_usage(self.conn, gp.month_key(), 2)
        places = [
            gp.GooglePlace(f"demo-{i}", name, addr, phone, site, HOURS[i][0], CENTER[0] + dlat, CENTER[1] + dlon,
                           rating, count, "OPERATIONAL", HOURS[i][1])
            for i, (name, dlat, dlon, phone, site, rating, count, addr) in enumerate(FAKE)
        ]
        return places, False

    def search_adaptive(self, query, bbox, max_depth=2):
        return self.search(query, bbox)


def fake_resolve(name, hint=None):
    return [Area(name, f"{name}, Θεσσαλονίκη (demo)", "node", 1, CENTER[0], CENTER[1], "suburb")]


gp.GooglePlacesClient = FakeClient
api.resolve_areas = fake_resolve

if __name__ == "__main__":
    print("DEMO MODE: fictional data. Open http://127.0.0.1:8770/?q=φαρμακεία&area=Πεύκα&auto=1")
    uvicorn.run(api.app, host="127.0.0.1", port=8770)
