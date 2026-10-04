import pytest
from fastapi.testclient import TestClient

from finder import db
from finder.api import app, csv_safe
from finder.sources.base import Business


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    conn = db.connect()
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [
        Business("osm", "node/1", "Χωρίς Site", "cafe", "Πεύκα", phone="2310"),
        Business("osm", "node/2", "Με Site", "cafe", "Πεύκα", website_url="http://a.gr"),
        Business("osm", "node/3", "=HYPERLINK(1)", "bakery", "Καλαμαριά"),
    ])
    conn.execute("UPDATE businesses SET site_status='alive' WHERE source_id='node/2'")
    conn.commit()
    conn.close()
    return TestClient(app)


def names(resp):
    return sorted(b["name"] for b in resp.json())


def test_filters_lists_areas_and_categories(client):
    assert client.get("/api/filters").json() == {"areas": ["Καλαμαριά", "Πεύκα"], "categories": ["bakery", "cafe"]}


def test_filter_by_area_and_leads_only(client):
    assert names(client.get("/api/businesses", params={"area": "Πεύκα", "leads_only": True})) == ["Χωρίς Site"]
    assert len(client.get("/api/businesses").json()) == 3


def test_search_text(client):
    assert names(client.get("/api/businesses", params={"q": "2310"})) == ["Χωρίς Site"]


def test_invalid_status_rejected(client):
    assert client.get("/api/businesses", params={"site_status": "bogus"}).status_code == 422


def test_patch_notes_and_status(client):
    bid = client.get("/api/businesses", params={"q": "2310"}).json()[0]["id"]
    assert client.patch(f"/api/businesses/{bid}", json={"notes": "καλώ Δευτέρα", "contact_status": "called"}).status_code == 200
    row = client.get("/api/businesses", params={"contact_status": "called"}).json()[0]
    assert row["notes"] == "καλώ Δευτέρα"


def test_patch_rejects_bad_status_and_missing_id(client):
    assert client.patch("/api/businesses/1", json={"contact_status": "x"}).status_code == 422
    assert client.patch("/api/businesses/999", json={"notes": "a"}).status_code == 404


def test_do_not_call_hidden_unless_filtered(client):
    bid = client.get("/api/businesses", params={"q": "2310"}).json()[0]["id"]
    client.patch(f"/api/businesses/{bid}", json={"contact_status": "do_not_call"})
    assert "Χωρίς Site" not in names(client.get("/api/businesses"))
    assert "Χωρίς Site" not in names(client.get("/api/businesses", params={"leads_only": True}))
    assert names(client.get("/api/businesses", params={"contact_status": "do_not_call"})) == ["Χωρίς Site"]


def test_csv_export_escapes_formulas(client):
    r = client.get("/api/export.csv", params={"area": "Καλαμαριά"})
    assert r.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK(1)" in r.text


def test_csv_safe():
    assert csv_safe("=1+1") == "'=1+1" and csv_safe(None) == "" and csv_safe("ok") == "ok"


def test_manual_phone_and_verified(client):
    b = client.get("/api/businesses", params={"area": "Καλαμαριά"}).json()[0]
    assert client.get("/api/businesses", params={"has_phone": True, "area": "Καλαμαριά"}).json() == []
    client.patch(f"/api/businesses/{b['id']}", json={"manual_phone": " 2310 111111 ", "no_site_verified": True})
    row = client.get("/api/businesses", params={"has_phone": True, "verified": True}).json()[0]
    assert (row["manual_phone"], row["no_site_verified"]) == ("2310 111111", 1)
    client.patch(f"/api/businesses/{b['id']}", json={"manual_phone": "  "})  # blank clears it
    assert client.get("/api/businesses", params={"area": "Καλαμαριά", "has_phone": True}).json() == []


def test_sort_by_name_descending_and_unknown_sort_ignored(client):
    asc = [b["name"] for b in client.get("/api/businesses", params={"sort": "name"}).json()]
    desc = [b["name"] for b in client.get("/api/businesses", params={"sort": "name", "desc": True}).json()]
    assert desc == asc[::-1]
    assert client.get("/api/businesses", params={"sort": "name; DROP TABLE businesses"}).status_code == 200
    assert len(client.get("/api/businesses").json()) == 3


AREA = {"name": "Πεύκα", "display_name": "x", "osm_type": "node", "osm_id": 1, "lat": 40.6, "lon": 22.9, "place_type": "suburb"}


def test_resolve_returns_candidates(client, monkeypatch):
    from finder import api
    from finder.sources.base import Area
    monkeypatch.setattr(api, "resolve_areas", lambda name, hint=None: [Area(name, "Πεύκα, Θεσσαλονίκη", "node", 1, 1.0, 2.0, "suburb")])
    data = client.get("/api/resolve", params={"name": "Πεύκα", "hint": "Θεσσαλονίκη"}).json()
    assert data[0]["display_name"] == "Πεύκα, Θεσσαλονίκη" and data[0]["has_boundary"] is False
    assert client.get("/api/resolve", params={"name": "a"}).status_code == 422


def test_scan_saves_businesses(client, monkeypatch):
    from finder import api
    class FakeSource:
        def __init__(self, radius): pass
        def search(self, area, category):
            return [Business("osm", "node/50", "Νέο Καφέ", category, area.name)]
    monkeypatch.setattr(api, "OsmSource", FakeSource)
    r = client.post("/api/scan", json={"area": AREA, "category": "cafe", "radius": 1000})
    assert r.json() == {"category": "cafe", "found": 1, "new": 1, "updated": 0, "unchanged": 0}
    assert "Νέο Καφέ" in names(client.get("/api/businesses"))


def test_scan_validates_input_and_reports_overpass_errors(client, monkeypatch):
    import httpx
    from finder import api
    assert client.post("/api/scan", json={"area": AREA, "category": "shop=evil"}).status_code == 422
    assert client.post("/api/scan", json={"area": AREA, "category": "cafe", "radius": 999999}).status_code == 422
    class Boom:
        def __init__(self, radius): pass
        def search(self, area, category): raise httpx.ConnectError("down")
    monkeypatch.setattr(api, "OsmSource", Boom)
    assert client.post("/api/scan", json={"area": AREA, "category": "cafe"}).status_code == 502


def test_check_endpoint_updates_status(client, monkeypatch):
    from finder import api
    from finder.checker import CheckResult
    async def fake_check_many(urls, concurrency=5):
        return {k: CheckResult("dead", None, "ConnectError") for k in urls}
    monkeypatch.setattr(api, "check_many", fake_check_many)
    assert client.get("/api/check/pending").json() == {"pending": 0}  # fixture site is already 'alive'
    conn = db.connect()
    conn.execute("UPDATE businesses SET site_status='unchecked' WHERE website_url IS NOT NULL"); conn.commit(); conn.close()
    assert client.get("/api/check/pending").json() == {"pending": 1}
    assert client.post("/api/check").json() == {"checked": 1, "dead": 1}
    assert client.get("/api/businesses", params={"site_status": "dead"}).json()[0]["check_error"] == "ConnectError"
