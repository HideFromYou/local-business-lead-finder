import json

import httpx
import pytest
from fastapi.testclient import TestClient

from finder import db
from finder.api import app
from finder.sources import google_places as gp


def place(i, **kw):
    base = {"id": f"pid{i}", "displayName": {"text": f"Φαρμακείο {i}"}, "formattedAddress": "Οδός 1",
            "location": {"latitude": 40.6, "longitude": 22.9}, "nationalPhoneNumber": "231 000 0000",
            "rating": 4.5, "userRatingCount": 10}
    return {**base, **kw}


def client_with(handler, limit=900, conn=None):
    conn = conn or db.connect(":memory:")
    return gp.GooglePlacesClient("KEY", conn, limit=limit, transport=httpx.MockTransport(handler)), conn


def test_lead_status():
    assert gp.lead_status(None) == "none"
    assert gp.lead_status("") == "none"
    assert gp.lead_status("https://m.facebook.com/shop") == "social_only"
    assert gp.lead_status("shop.gr") == "has_site"


def test_grid_cells_cover_bbox_exactly():
    cells = gp.grid_cells((40.0, 41.0, 22.0, 23.0), 2)
    assert len(cells) == 4
    assert min(c[0] for c in cells) == 40.0 and max(c[1] for c in cells) == 41.0
    assert min(c[2] for c in cells) == 22.0 and max(c[3] for c in cells) == 23.0


def test_bbox_from_point_is_centered():
    s, n, w, e = gp.bbox_from_point(40.0, 22.0, 1000)
    assert s < 40.0 < n and w < 22.0 < e
    assert round((n - s) * 111_320 / 2) == 1000


def test_request_has_key_fieldmask_and_no_review_fields():
    seen = {}
    def handler(req):
        seen["key"] = req.headers["x-goog-api-key"]
        seen["mask"] = req.headers["x-goog-fieldmask"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"places": [place(1)]})
    client, _ = client_with(handler)
    client.search("φαρμακεία", (40.0, 41.0, 22.0, 23.0))
    assert seen["key"] == "KEY"
    assert "places.nationalPhoneNumber" in seen["mask"] and "places.websiteUri" in seen["mask"]
    assert "reviews" not in seen["mask"]
    assert seen["body"]["textQuery"] == "φαρμακεία" and seen["body"]["pageSize"] == 20
    assert "rectangle" in seen["body"]["locationRestriction"]


def test_pagination_follows_next_page_token_and_counts_calls():
    def handler(req):
        body = json.loads(req.content)
        if "pageToken" not in body:
            return httpx.Response(200, json={"places": [place(1), place(2)], "nextPageToken": "T"})
        assert body["pageToken"] == "T"
        return httpx.Response(200, json={"places": [place(3)]})
    client, conn = client_with(handler)
    places, partial = client.search("x", (0, 1, 0, 1))
    assert [p.place_id for p in places] == ["pid1", "pid2", "pid3"] and not partial
    assert client.calls_made == 2 and db.get_usage(conn, gp.month_key()) == 2


def test_grid_dedupes_same_place_across_cells():
    client, _ = client_with(lambda req: httpx.Response(200, json={"places": [place(1)]}))
    places, _ = client.search("x", (0, 1, 0, 1), grid=2)
    assert len(places) == 1 and client.calls_made == 4


def test_hard_limit_stops_and_returns_partial_without_calling_google():
    calls = []
    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"places": [place(len(calls))]})
    client, _ = client_with(handler, limit=2)
    places, partial = client.search("x", (0, 1, 0, 1), grid=3)
    assert partial and len(calls) == 2 and len(places) == 2


def test_limit_already_reached_makes_no_request():
    client, conn = client_with(lambda req: pytest.fail("must not call Google"), limit=5)
    db.add_usage(conn, gp.month_key(), 5)
    places, partial = client.search("x", (0, 1, 0, 1))
    assert places == [] and partial


def test_api_error_message_does_not_leak_key():
    client, _ = client_with(lambda req: httpx.Response(403, json={"error": {"message": "API key not valid"}}))
    with pytest.raises(gp.GoogleApiError) as e:
        client.search("x", (0, 1, 0, 1))
    assert "403" in str(e.value) and "KEY" not in str(e.value)


# ---- API endpoints ----
AREA = {"name": "Πεύκα", "display_name": "x", "osm_type": "node", "osm_id": 1,
        "lat": 40.65, "lon": 22.99, "place_type": "suburb"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "g.db"))
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "KEY")
    return TestClient(app)


def fake_google(monkeypatch, places):
    real = gp.GooglePlacesClient
    def factory(key, conn, **kw):
        return real(key, conn, transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"places": places})), **kw)
    monkeypatch.setattr(gp, "GooglePlacesClient", factory)


def test_search_requires_key(api, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY")
    assert api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA}).status_code == 400


def test_search_returns_status_and_usage(api, monkeypatch):
    fake_google(monkeypatch, [place(1), place(2, websiteUri="https://facebook.com/x"),
                              place(3, websiteUri="https://real.gr")])
    r = api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA}).json()
    assert {x["place_id"]: x["site_status"] for x in r["results"]} == {
        "pid1": "none", "pid2": "social_only", "pid3": "has_site"}
    assert r["calls_used_now"] == 1 and r["calls_this_month"] == 1
    assert api.get("/api/google/status").json() == {"configured": True, "calls_this_month": 1, "limit": 900}


def test_own_fields_saved_by_place_id_and_do_not_call_hidden(api, monkeypatch):
    fake_google(monkeypatch, [place(1), place(2)])
    assert api.patch("/api/google/leads/pid1", json={"notes": "καλώ", "manual_phone": "6900", "no_site_verified": True}).status_code == 200
    assert api.patch("/api/google/leads/pid2", json={"contact_status": "do_not_call"}).status_code == 200
    r = api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA}).json()["results"]
    assert [x["place_id"] for x in r] == ["pid1"]
    assert (r[0]["notes"], r[0]["manual_phone"], r[0]["no_site_verified"]) == ("καλώ", "6900", 1)


def test_no_google_content_is_stored_in_the_database(api, monkeypatch):
    fake_google(monkeypatch, [place(1, websiteUri="https://secret-site.gr")])
    api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA})
    api.patch("/api/google/leads/pid1", json={"notes": "x"})
    conn = db.connect()
    dump = "\n".join(conn.iterdump())
    for google_text in ("Φαρμακείο 1", "231 000 0000", "secret-site.gr", "Οδός 1"):
        assert google_text not in dump
    assert conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 0


def test_place_id_validation_and_error_mapping(api, monkeypatch):
    assert api.patch("/api/google/leads/bad id!", json={"notes": "x"}).status_code in (404, 422)
    real = gp.GooglePlacesClient
    monkeypatch.setattr(gp, "GooglePlacesClient", lambda key, conn, **kw: real(
        key, conn, transport=httpx.MockTransport(lambda req: httpx.Response(403, json={"error": {"message": "denied"}})), **kw))
    r = api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA})
    assert r.status_code == 502 and "denied" in r.json()["detail"] and "KEY" not in r.text


def test_manual_email_saved_validated_and_returned(api, monkeypatch):
    fake_google(monkeypatch, [place(1)])
    assert api.patch("/api/google/leads/pid1", json={"manual_email": "info@shop.gr"}).status_code == 200
    assert api.patch("/api/google/leads/pid1", json={"manual_email": "not an email"}).status_code == 422
    r = api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA}).json()["results"]
    assert r[0]["manual_email"] == "info@shop.gr"
    api.patch("/api/google/leads/pid1", json={"manual_email": ""})
    assert api.post("/api/google/search", json={"query": "φαρμακεία", "area": AREA}).json()["results"][0]["manual_email"] is None


def test_root_serves_the_google_page(api):
    assert "Web Presence Scanner" in api.get("/").text and "google.js" in api.get("/").text


def test_adaptive_splits_a_capped_cell_and_dedupes():
    state = {"n": 0}
    def handler(req):
        state["n"] += 1
        body = json.loads(req.content)
        low = body["locationRestriction"]["rectangle"]["low"]["latitude"]
        if state["n"] <= 3:  # the whole area: three full pages = 60 results = capped
            first = (state["n"] - 1) * 20
            places = [place(first + i) for i in range(20)]
            return httpx.Response(200, json={"places": places, **({"nextPageToken": "T"} if state["n"] < 3 else {})})
        return httpx.Response(200, json={"places": [place(1000 + state["n"]), place(0)]})  # place(0) is a repeat
    client, _ = client_with(handler)
    places, partial = client.search_adaptive("καταστήματα", (40.0, 41.0, 22.0, 23.0))
    assert not partial and client.calls_made == 3 + 4  # whole area, then 4 sub-cells
    assert len(places) == 60 + 4  # 4 new places, the repeated one is not counted twice


def test_adaptive_respects_the_search_call_budget():
    def handler(req):
        return httpx.Response(200, json={"places": [place(1)], "nextPageToken": "T"})
    client, _ = client_with(handler)
    client.call_budget = 2
    places, partial = client.search_adaptive("x", (0, 1, 0, 1))
    assert partial and client.calls_made == 2 and "2 κλήσεων" in client.stop_reason


def test_all_mode_endpoint_uses_adaptive_and_budget(api, monkeypatch):
    fake_google(monkeypatch, [place(1), place(2)])
    r = api.post("/api/google/search", json={"query": "καταστήματα", "area": AREA, "mode": "all", "max_calls": 15}).json()
    assert len(r["results"]) == 2 and r["calls_used_now"] == 1 and r["stop_reason"] == ""
    assert api.post("/api/google/search", json={"query": "καταστήματα", "area": AREA, "mode": "all", "max_calls": 1000}).status_code == 422


def test_parse_place_keeps_weekday_lines_and_periods():
    raw = place(1, regularOpeningHours={
        "openNow": True,
        "periods": [{"open": {"day": 1, "hour": 8, "minute": 0}, "close": {"day": 1, "hour": 21, "minute": 0}},
                    {"open": {"day": 0, "hour": 0, "minute": 0}}],
        "weekdayDescriptions": ["Δευτέρα: 8:00 π.μ.–9:00 μ.μ."],
    })
    parsed = gp.parse_place(raw)
    assert parsed.opening_hours == ["Δευτέρα: 8:00 π.μ.–9:00 μ.μ."]
    assert parsed.opening_periods[0] == {"open": {"day": 1, "hour": 8, "minute": 0}, "close": {"day": 1, "hour": 21, "minute": 0}}
    assert parsed.opening_periods[1]["close"] is None
    assert gp.parse_place(place(2)).opening_periods is None
