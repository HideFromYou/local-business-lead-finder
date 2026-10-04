from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Area:
    """A place resolved from a name. Either a boundary (has polygon) or just a point."""

    name: str
    display_name: str
    osm_type: str  # node / way / relation
    osm_id: int
    lat: float
    lon: float
    place_type: str = ""
    bbox: tuple[float, float, float, float] | None = None  # south, north, west, east

    @property
    def has_boundary(self) -> bool:
        return self.osm_type in ("relation", "way") and self.place_type in (
            "administrative",
            "suburb",
            "neighbourhood",
            "quarter",
            "city",
            "town",
            "village",
        )


@dataclass
class Business:
    source: str
    source_id: str
    name: str
    category: str
    area: str
    address: str | None = None
    phone: str | None = None
    website_url: str | None = None
    opening_hours: str | None = None
    lat: float | None = None
    lon: float | None = None


class Source(ABC):
    name: str

    @abstractmethod
    def search(self, area: Area, category: str) -> list[Business]:
        """Return businesses of `category` inside `area`."""
