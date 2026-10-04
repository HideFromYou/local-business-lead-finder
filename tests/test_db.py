import pytest

from finder import db
from finder.sources.base import Business


@pytest.fixture
def conn():
    return db.connect(":memory:")


def biz(**kw):
    base = dict(source="osm", source_id="node/1", name="Cafe", category="cafe", area="Πεύκα")
    return Business(**{**base, **kw})


def get(conn):
    return conn.execute("SELECT * FROM businesses").fetchall()


def test_no_website_is_status_none(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(), biz(source_id="node/2", website_url="http://a.gr")])
    status = {r["source_id"]: r["site_status"] for r in get(conn)}
    assert status == {"node/1": "none", "node/2": "unchecked"}


def test_blank_website_counts_as_none(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(website_url="  ")])
    assert get(conn)[0]["site_status"] == "none"
    assert get(conn)[0]["website_url"] is None


def test_dedupe_by_source_and_source_id(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz()])
    counts = db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz()])
    assert counts == {"new": 0, "updated": 0, "unchanged": 1}
    assert len(get(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2


def test_same_id_from_other_source_is_separate(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(), biz(source="google")])
    assert len(get(conn)) == 2


def test_rescan_keeps_my_notes_and_contact_status(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz()])
    conn.execute("UPDATE businesses SET notes='call after 5', contact_status='called'")
    counts = db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(phone="2310")])
    row = get(conn)[0]
    assert counts["updated"] == 1
    assert (row["phone"], row["notes"], row["contact_status"]) == ("2310", "call after 5", "called")


def test_new_website_resets_status_but_same_url_keeps_check(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(website_url="http://a.gr")])
    conn.execute("UPDATE businesses SET site_status='dead', http_status=500")
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(website_url="http://a.gr", phone="1")])
    assert get(conn)[0]["site_status"] == "dead"
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(website_url="http://b.gr", phone="1")])
    row = get(conn)[0]
    assert (row["site_status"], row["http_status"]) == ("unchecked", None)
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(phone="1")])  # website removed
    assert get(conn)[0]["site_status"] == "none"


def test_do_not_call_hidden_from_list(conn):
    db.save_scan(conn, "Πεύκα", "cafe", "osm", [biz(), biz(source_id="node/2", name="B")])
    conn.execute("UPDATE businesses SET contact_status='do_not_call' WHERE source_id='node/1'")
    assert [r["name"] for r in db.list_businesses(conn)] == ["B"]
    assert len(db.list_businesses(conn, include_do_not_call=True)) == 2
    assert db.list_businesses(conn, site_status="none")[0]["name"] == "B"


def test_migration_adds_new_columns_to_old_database(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE businesses (id INTEGER PRIMARY KEY, source TEXT, source_id TEXT)")
    old.commit(); old.close()
    cols = {r["name"] for r in db.connect(path).execute("PRAGMA table_info(businesses)")}
    assert {"manual_phone", "no_site_verified"} <= cols
