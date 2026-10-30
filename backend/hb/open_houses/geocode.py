"""Address -> coordinates for the open-house distance origin.

The shipped geocoder is the US Census Bureau's: free, no key, US addresses
only. Another market swaps in its own `Geocoder` via `GEOCODER`.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


@dataclass(frozen=True)
class GeoPoint:
    address: str
    lat: float
    lon: float


class Geocoder(Protocol):
    def geocode(self, address: str) -> GeoPoint | None:
        """None when the address can't be resolved."""
        ...


def fetch_census(address: str) -> dict:
    """Seam for tests: the raw Census JSON for one address."""
    resp = httpx.get(CENSUS_URL, params={"address": address, "benchmark": "Public_AR_Current",
                                         "format": "json"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


class CensusGeocoder:
    def geocode(self, address: str) -> GeoPoint | None:
        matches = ((fetch_census(address).get("result") or {}).get("addressMatches")) or []
        if not matches:
            return None
        best = matches[0]
        coords = best.get("coordinates") or {}
        if coords.get("x") is None or coords.get("y") is None:
            return None
        return GeoPoint(address=address, lat=float(coords["y"]), lon=float(coords["x"]))


GEOCODER: Geocoder = CensusGeocoder()
