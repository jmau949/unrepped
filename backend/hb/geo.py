"""Geo helpers: haversine distance + bounding-box prefilter (docs/06 §2.1).

Used by entity resolution (100 m match guard) and the CMA comp radius
search (SQL bbox prefilter on indexed lat/lon, exact haversine in Python).
"""

import math

EARTH_RADIUS_MILES = 3958.8
METERS_PER_MILE = 1609.344


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_miles(lat1, lon1, lat2, lon2) * METERS_PER_MILE


def bbox(lat: float, lon: float, radius_miles: float) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) box containing the radius circle —
    SQL prefilter for the indexed (lat, lon) columns."""
    dlat = radius_miles / 69.0
    dlon = radius_miles / (69.0 * max(0.01, math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon
