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
