"""Google Places API (New) Text Search.

Terms: we never store Google content. Results are returned live to the UI; only the
place_id and the user's own fields go to the database (see db.google_leads).
Cost: every request is counted, and a hard monthly limit stops us before the free tier ends.
"""

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .. import db
from ..checker import is_social, normalize_url

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Phone/rating/hours are the "Enterprise" tier. No reviews or atmosphere fields (they cost more).
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.location",
    "places.websiteUri", "places.nationalPhoneNumber", "places.regularOpeningHours",
    "places.rating", "places.userRatingCount", "places.businessStatus", "nextPageToken",
])
MAX_PAGES = 3  # Google returns at most 60 results (3 pages of 20) per query
DEFAULT_MONTHLY_LIMIT = 900  # the free tier is 1,000 Enterprise calls per month


class GoogleApiError(Exception):
    pass


class QuotaExceeded(Exception):
    pass


@dataclass
class GooglePlace:
    place_id: str
    name: str
    address: str | None
    phone: str | None
    website_url: str | None
    opening_hours: str | None
    lat: float | None
    lon: float | None
    rating: float | None
    rating_count: int | None
    business_status: str | None


def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def monthly_limit() -> int:
    try:
        return int(os.getenv("GOOGLE_MONTHLY_CALL_LIMIT", DEFAULT_MONTHLY_LIMIT))
    except ValueError:
        return DEFAULT_MONTHLY_LIMIT


def bbox_from_point(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """(south, north, west, east) around a point."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return (lat - dlat, lat + dlat, lon - dlon, lon + dlon)


def grid_cells(bbox: tuple[float, float, float, float], n: int) -> list[tuple[float, float, float, float]]:
    """Split a bbox into n x n cells; each cell gets its own search (60 results max each)."""
    south, north, west, east = bbox
    dlat, dlon = (north - south) / n, (east - west) / n
    return [
        (south + i * dlat, south + (i + 1) * dlat, west + j * dlon, west + (j + 1) * dlon)
        for i in range(n) for j in range(n)
    ]


def lead_status(website_url: str | None) -> str:
    """none = no website, social_only = just a social page, has_site = a real website listed."""
    url = normalize_url(website_url)
    if not url:
        return "none"
    return "social_only" if is_social(url) else "has_site"


def parse_place(p: dict) -> GooglePlace:
    location = p.get("location", {})
    hours = p.get("regularOpeningHours", {}).get("weekdayDescriptions")
    return GooglePlace(
        place_id=p["id"],
        name=p.get("displayName", {}).get("text", ""),
        address=p.get("formattedAddress"),
        phone=p.get("nationalPhoneNumber"),
        website_url=p.get("websiteUri"),
        opening_hours="; ".join(hours) if hours else None,
        lat=location.get("latitude"),
        lon=location.get("longitude"),
        rating=p.get("rating"),
        rating_count=p.get("userRatingCount"),
        business_status=p.get("businessStatus"),
    )


class GooglePlacesClient:
    def __init__(self, api_key: str, conn, limit: int | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.conn = conn
        self.limit = monthly_limit() if limit is None else limit
        self.http = httpx.Client(timeout=30, transport=transport)
        self.calls_made = 0
        self.call_budget: int | None = None  # optional cap for ONE search (on top of the monthly limit)
        self.stop_reason = ""

    def calls_this_month(self) -> int:
        return db.get_usage(self.conn, month_key())

    def _post(self, body: dict) -> dict:
        if self.call_budget is not None and self.calls_made >= self.call_budget:
            self.stop_reason = f"Έφτασε το όριο των {self.call_budget} κλήσεων αυτής της αναζήτησης."
            raise QuotaExceeded(self.stop_reason)
        if self.calls_this_month() >= self.limit:
            self.stop_reason = f"Έφτασες το μηνιαίο όριο των {self.limit} κλήσεων."
            raise QuotaExceeded(self.stop_reason)
        db.add_usage(self.conn, month_key())  # count before sending: never under-count
        self.calls_made += 1
        response = self.http.post(
            SEARCH_URL, json=body,
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK},
        )
        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.text[:200]
            raise GoogleApiError(f"Google API HTTP {response.status_code}: {message}")
        return response.json()

    def iter_cell(self, query: str, cell: tuple[float, float, float, float], language: str = "el"):
        south, north, west, east = cell
        body = {
            "textQuery": query, "languageCode": language, "regionCode": "GR", "pageSize": 20,
            "locationRestriction": {"rectangle": {
                "low": {"latitude": south, "longitude": west},
                "high": {"latitude": north, "longitude": east},
            }},
        }
        for _ in range(MAX_PAGES):
            data = self._post(body)
            for raw in data.get("places", []):
                yield parse_place(raw)
            token = data.get("nextPageToken")
            if not token:
                return
            body = {**body, "pageToken": token}

    def search(self, query: str, bbox: tuple[float, float, float, float],
               grid: int = 1) -> tuple[list[GooglePlace], bool]:
        """Returns (places deduplicated by place_id, partial). partial=True if the monthly limit stopped us."""
        found: dict[str, GooglePlace] = {}
        try:
            for cell in grid_cells(bbox, grid):
                for place in self.iter_cell(query, cell):
                    found.setdefault(place.place_id, place)
        except QuotaExceeded:
            return list(found.values()), True
        return list(found.values()), False

    def search_adaptive(self, query: str, bbox: tuple[float, float, float, float],
                        max_depth: int = 2) -> tuple[list[GooglePlace], bool]:
        """Search the whole area; wherever Google hits its 60-result cap, split that cell in 4 and
        search the parts (up to max_depth levels). Stops cleanly at the call budget or monthly limit."""
        found: dict[str, GooglePlace] = {}

        def run(cell, depth):
            count = 0
            for place in self.iter_cell(query, cell):
                count += 1
                found.setdefault(place.place_id, place)
            if count >= MAX_PAGES * 20 and depth < max_depth:  # capped: there is probably more here
                for part in grid_cells(cell, 2):
                    run(part, depth + 1)

        try:
            run(bbox, 0)
        except QuotaExceeded:
            return list(found.values()), True
        return list(found.values()), False
