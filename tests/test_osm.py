import pytest

from finder.sources.base import Area
from finder.sources.osm import _fold, build_query, parse_element


def point_area():
    return Area("Πεύκα", "Πεύκα, Θεσσαλονίκη", "node", 1, 40.6, 22.9, "suburb")


def boundary_area():
    return Area("Καλαμαριά", "Καλαμαριά", "relation", 123, 40.58, 22.95, "administrative")


def test_fold_ignores_accents_and_case():
    assert _fold("Πεύκα") == _fold("ΠΕΥΚΑ") == "πευκα"


def test_query_for_boundary_uses_area_id():
    q = build_query(boundary_area(), "cafe")
    assert "area(3600000123)" in q
    assert '"amenity"="cafe"' in q


def test_query_for_point_uses_radius():
    q = build_query(point_area(), "pharmacy", radius=800)
    assert "around:800,40.6,22.9" in q


def test_raw_tag_category_and_unknown_category():
    assert '"shop"="jewelry"' in build_query(point_area(), "shop=jewelry")
    with pytest.raises(ValueError):
        build_query(point_area(), "nonsense")


def test_parse_element_node():
    el = {
        "type": "node",
        "id": 5,
        "lat": 40.1,
        "lon": 22.2,
        "tags": {"name": "Καφέ", "addr:street": "Οδός", "addr:housenumber": "3", "contact:phone": "2310"},
    }
    b = parse_element(el, "Πεύκα", "cafe")
    assert b.source_id == "node/5"
    assert b.address == "Οδός 3"
    assert b.phone == "2310"
    assert b.website_url is None
    assert (b.lat, b.lon) == (40.1, 22.2)


def test_parse_element_way_uses_center_and_skips_unnamed():
    el = {"type": "way", "id": 9, "center": {"lat": 1.0, "lon": 2.0}, "tags": {"name": "X", "website": "http://x.gr"}}
    b = parse_element(el, "A", "cafe")
    assert (b.lat, b.lon) == (1.0, 2.0)
    assert b.website_url == "http://x.gr"
    assert parse_element({"type": "node", "id": 1, "tags": {}}, "A", "cafe") is None


def test_user_agent_ignores_placeholder_contact(monkeypatch):
    from finder.sources.osm import user_agent
    monkeypatch.setenv("OVERPASS_CONTACT", "you@example.com")
    assert "example.com" not in user_agent()
    monkeypatch.setenv("OVERPASS_CONTACT", "me@mydomain.gr")
    assert "me@mydomain.gr" in user_agent()
    monkeypatch.delenv("OVERPASS_CONTACT")
    assert user_agent().endswith("personal tool)")


def test_resolve_areas_drops_streets_and_bus_stops(monkeypatch):
    from finder.sources import osm
    rows = [
        {"osm_type": "node", "osm_id": 1, "category": "highway", "type": "bus_stop", "display_name": "ΠΕΥΚΑ, Θεσσαλονίκης", "lat": "1", "lon": "2", "boundingbox": ["1", "1", "2", "2"]},
        {"osm_type": "node", "osm_id": 2, "category": "place", "type": "suburb", "display_name": "Πεύκα, Θεσσαλονίκη", "lat": "1", "lon": "2", "boundingbox": ["1", "1", "2", "2"]},
        {"osm_type": "node", "osm_id": 3, "category": "place", "type": "hamlet", "display_name": "Πεύκα, Έβρου", "lat": "1", "lon": "2", "boundingbox": ["1", "1", "2", "2"]},
    ]
    monkeypatch.setattr(osm, "_cached_request", lambda *a, **k: rows)
    areas = osm.resolve_areas("πευκα", "Θεσσαλονίκη")
    assert [a.osm_id for a in areas] == [2]
    assert [a.osm_id for a in osm.resolve_areas("πευκα")] == [2, 3]
    only_street = [rows[0]]
    monkeypatch.setattr(osm, "_cached_request", lambda *a, **k: only_street)
    assert [a.osm_id for a in osm.resolve_areas("x")] == [1]  # never an empty dead end
