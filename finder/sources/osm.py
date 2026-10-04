"""OpenStreetMap source: Nominatim (name -> area) + Overpass (area -> businesses)."""

import hashlib
import json
import os
import time
import unicodedata
from pathlib import Path

import httpx

from .base import Area, Business, Source

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_DIR = Path(__file__).resolve().parents[2] / "cache"
MIN_SECONDS_BETWEEN_REQUESTS = 1.5

# friendly category name -> OSM tag
CATEGORIES: dict[str, tuple[str, str]] = {
    "cafe": ("amenity", "cafe"),
    "restaurant": ("amenity", "restaurant"),
    "fast_food": ("amenity", "fast_food"),
    "bar": ("amenity", "bar"),
    "pharmacy": ("amenity", "pharmacy"),
    "bakery": ("shop", "bakery"),
    "butcher": ("shop", "butcher"),
    "supermarket": ("shop", "supermarket"),
    "clothes": ("shop", "clothes"),
    "hairdresser": ("shop", "hairdresser"),
    "beauty": ("shop", "beauty"),
    "florist": ("shop", "florist"),
    "bookstore": ("shop", "books"),
    "electronics": ("shop", "electronics"),
    "car_repair": ("shop", "car_repair"),
    "dentist": ("amenity", "dentist"),
}

_last_request = 0.0


def user_agent() -> str:
    ua = "local-business-lead-finder/0.1 (personal tool"
    contact = (os.getenv("OVERPASS_CONTACT") or "").strip()
    # The template value from .env.example is not a real contact: OSM servers block it.
    if not contact or "example.com" in contact.lower():
        return f"{ua})"
    return f"{ua}; {contact})"


def _fold(text: str) -> str:
    """Lowercase and strip Greek/Latin accents so 'Πεύκα' matches 'πευκα'."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).replace("ς", "σ")


def _cached_request(method: str, url: str, **kwargs) -> object:
    """HTTP call with an on-disk cache and a pause between real requests."""
    global _last_request
    key = hashlib.sha1(
        json.dumps([method, url, kwargs.get("params"), kwargs.get("data")], sort_keys=True).encode()
    ).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    response = httpx.request(
        method, url, headers={"User-Agent": user_agent()}, timeout=90, **kwargs
    )
    _last_request = time.monotonic()
    if response.status_code in (403, 429):
        raise httpx.HTTPError(
            f"Το OpenStreetMap απέρριψε το αίτημα (HTTP {response.status_code}). "
            "Περίμενε λίγο, και βάλε το πραγματικό email σου στο OVERPASS_CONTACT στο .env."
        )
    response.raise_for_status()
    payload = response.json()
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False))
    return payload


def resolve_areas(name: str, hint: str | None = None) -> list[Area]:
    """Look the name up in Nominatim. `hint` keeps only candidates whose full address contains it."""
    results = _cached_request(
        "GET",
        NOMINATIM_URL,
        params={
            "q": name,
            "format": "jsonv2",
            "limit": 15,
            "accept-language": "el",
            "countrycodes": "gr",
        },
    )
    areas = [
        Area(
            name=name,
            display_name=r["display_name"],
            osm_type=r["osm_type"],
            osm_id=int(r["osm_id"]),
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            place_type=r["type"],
            bbox=tuple(float(x) for x in r["boundingbox"]) if r.get("boundingbox") else None,
        )
        for r in results
    ]
    if hint:
        needle = _fold(hint)
        areas = [a for a in areas if needle in _fold(a.display_name)]
    return areas


def build_query(area: Area, category: str, radius: int = 1500) -> str:
    key, value = CATEGORIES[category] if category in CATEGORIES else _raw_tag(category)
    selector = f'nwr["{key}"="{value}"]'
    if area.has_boundary:
        area_id = (3600000000 if area.osm_type == "relation" else 2400000000) + area.osm_id
        body = f"area({area_id})->.a;\n{selector}(area.a);"
    else:
        body = f"{selector}(around:{radius},{area.lat},{area.lon});"
    return f"[out:json][timeout:60];\n{body}\nout center tags;"


def _raw_tag(category: str) -> tuple[str, str]:
    """Allow `--category shop=jewelry` for tags not in CATEGORIES."""
    if "=" not in category:
        raise ValueError(
            f"Unknown category '{category}'. Known: {', '.join(sorted(CATEGORIES))} (or use key=value)"
        )
    key, value = category.split("=", 1)
    return key, value


def parse_element(element: dict, area_name: str, category: str) -> Business | None:
    tags = element.get("tags", {})
    name = tags.get("name") or tags.get("name:el") or tags.get("name:en")
    if not name:
        return None  # unnamed places can't be called
    center = element.get("center", {})
    street = " ".join(p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p)
    address = ", ".join(
        p for p in (street, tags.get("addr:postcode"), tags.get("addr:city")) if p
    )
    return Business(
        source="osm",
        source_id=f"{element['type']}/{element['id']}",
        name=name,
        category=category,
        area=area_name,
        address=address or None,
        phone=tags.get("phone") or tags.get("contact:phone"),
        website_url=tags.get("website") or tags.get("contact:website") or tags.get("url"),
        opening_hours=tags.get("opening_hours"),
        lat=element.get("lat", center.get("lat")),
        lon=element.get("lon", center.get("lon")),
    )


class OsmSource(Source):
    name = "osm"

    def __init__(self, radius: int = 1500):
        self.radius = radius
        self.overpass_url = os.getenv("OVERPASS_URL", DEFAULT_OVERPASS_URL)

    def search(self, area: Area, category: str) -> list[Business]:
        query = build_query(area, category, self.radius)
        data = _cached_request("POST", self.overpass_url, data={"data": query})
        businesses = (parse_element(e, area.name, category) for e in data["elements"])
        return [b for b in businesses if b is not None]
