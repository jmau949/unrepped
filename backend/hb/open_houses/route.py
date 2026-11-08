"""Open-house day routes (docs/05 §4c). The buyer sets the visiting order;
`drive_legs` times the drive into each stop in that order, and
`nearest_order` offers a nearest-next chain from wherever the buyer is —
every stop is kept, the ones without a location go last.

Pure: no DB, no network. Drive time comes from a `TravelEstimator`; the shipped
one is straight-line miles x a detour factor at an average speed, which is
honest enough for a 5-15 mile peninsula hop. A routing-API estimator can be
dropped in without touching the ordering.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlencode

from hb.geo import haversine_miles

MAPS_MAX_STOPS = 10  # Google Maps URLs take a destination + 9 waypoints


class TravelEstimator(Protocol):
    def minutes(self, a: tuple[float, float], b: tuple[float, float]) -> float: ...

    def miles(self, a: tuple[float, float], b: tuple[float, float]) -> float: ...


@dataclass(frozen=True)
class HaversineEstimator:
    avg_mph: float = 25.0
    detour_factor: float = 1.3

    def miles(self, a, b) -> float:
        return haversine_miles(a[0], a[1], b[0], b[1]) * self.detour_factor

    def minutes(self, a, b) -> float:
        return self.miles(a, b) / self.avg_mph * 60


@dataclass(frozen=True)
class Stop:
    id: str
    label: str  # an address Google Maps can route to
    lat: float | None  # None = no map location: no drive leg, never ordered by distance
    lon: float | None
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class Leg:
    stop: Stop
    drive_min: float | None  # from the previous located point; None = no location
    drive_miles: float | None


def _located(stop: Stop) -> bool:
    return stop.lat is not None and stop.lon is not None


def maps_url(origin_label: str, stops: list[Stop]) -> str | None:
    if not stops:
        return None
    stops = stops[:MAPS_MAX_STOPS]
    params = {"api": "1", "origin": origin_label, "destination": stops[-1].label,
              "travelmode": "driving"}
    if len(stops) > 1:
        params["waypoints"] = "|".join(s.label for s in stops[:-1])
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def drive_legs(origin: tuple[float, float], stops: list[Stop],
               estimator: TravelEstimator | None = None) -> list[Leg]:
    """The drive into each stop, visiting `stops` in the order given. A stop
    with no location gets no leg, and the next leg starts from the last
    located point."""
    est = estimator or HaversineEstimator()
    legs, pos = [], origin
    for stop in stops:
        if not _located(stop):
            legs.append(Leg(stop, None, None))
            continue
        here = (stop.lat, stop.lon)
        legs.append(Leg(stop, round(est.minutes(pos, here), 1), round(est.miles(pos, here), 1)))
        pos = here
    return legs


def nearest_order(start: tuple[float, float], stops: list[Stop],
                  estimator: TravelEstimator | None = None) -> list[Stop]:
    """The located stops as a nearest-next chain from `start`: the stop
    closest to `start` first, then the closest remaining stop to the one
    before it, and so on. Each hop is measured from the previous stop, never
    from `start`, so a day heads one way instead of crossing back past the
    buyer for a stop that is merely close to where they began. Ties go to the
    sooner window. Stops without a location follow, soonest window first — a
    suggestion the buyer can rearrange, so nothing is dropped."""
    est = estimator or HaversineEstimator()
    remaining = [s for s in stops if _located(s)]
    order, pos = [], start
    while remaining:
        nxt = min(remaining, key=lambda s: (est.minutes(pos, (s.lat, s.lon)), s.start_at, s.id))
        order.append(nxt)
        remaining.remove(nxt)
        pos = (nxt.lat, nxt.lon)
    unlocated = sorted((s for s in stops if not _located(s)), key=lambda s: (s.start_at, s.id))
    return order + unlocated
