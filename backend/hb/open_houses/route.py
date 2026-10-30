"""Open-house day routes (docs/05 §4c). The buyer sets the visiting order;
`drive_legs` times the drive into each stop in that order, and
`suggested_order` offers an order that fits the most time windows, then
drives the least — every stop is kept, the ones that can't fit go last.

Pure: no DB, no network. Drive time comes from a `TravelEstimator`; the shipped
one is straight-line miles x a detour factor at an average speed, which is
honest enough for a 5-15 mile peninsula hop. A routing-API estimator can be
dropped in without touching the search.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import permutations
from typing import Protocol
from urllib.parse import urlencode

from hb.geo import haversine_miles

EXHAUSTIVE_MAX = 8  # 8! = 40,320 orders — instant; beyond that, greedy
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
    lat: float | None  # None = no map location: no drive leg, never planned
    lon: float | None
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class Leg:
    stop: Stop
    drive_min: float | None  # from the previous located point; None = no location
    drive_miles: float | None


@dataclass
class PlannedStop:
    stop: Stop
    arrive_at: datetime
    leave_at: datetime
    drive_min: float
    drive_miles: float
    wait_min: float


@dataclass
class RoutePlan:
    depart_at: datetime | None
    stops: list[PlannedStop] = field(default_factory=list)
    skipped: list[tuple[Stop, str]] = field(default_factory=list)
    total_drive_min: float = 0.0
    maps_url: str | None = None


def _whole_minutes(dwell: timedelta) -> int:
    return int(dwell.total_seconds() // 60)


def _simulate(order, origin, start_at, dwell, est) -> RoutePlan:
    """Walk `order`, skipping any stop that can't get `dwell` inside its window."""
    plan = RoutePlan(depart_at=None)
    pos, t = origin, start_at
    for stop in order:
        here = (stop.lat, stop.lon)
        drive = est.minutes(pos, here)
        arrive = t + timedelta(minutes=drive)
        visit_from = max(arrive, stop.start_at)
        if visit_from + dwell > stop.end_at:
            if stop.end_at - stop.start_at < dwell:
                reason = f"open only {_whole_minutes(stop.end_at - stop.start_at)} min"
            elif arrive < stop.end_at:
                reason = f"can't get {_whole_minutes(dwell)} min before it closes"
            else:
                reason = "closed before you'd arrive"
            plan.skipped.append((stop, reason))
            continue
        if not plan.stops:
            # leave home just in time rather than waiting on the curb
            plan.depart_at = visit_from - timedelta(minutes=drive)
        plan.stops.append(PlannedStop(
            stop=stop, arrive_at=visit_from, leave_at=visit_from + dwell,
            drive_min=round(drive, 1), drive_miles=round(est.miles(pos, here), 1),
            wait_min=round((visit_from - arrive).total_seconds() / 60, 1) if plan.stops else 0.0,
        ))
        plan.total_drive_min += drive
        pos, t = here, visit_from + dwell
    plan.total_drive_min = round(plan.total_drive_min, 1)
    return plan


def _score(plan: RoutePlan):
    """Most stops, then least driving, then home earliest."""
    finish = plan.stops[-1].leave_at.timestamp() if plan.stops else 0
    return (-len(plan.stops), plan.total_drive_min, finish)


def _greedy(stops, origin, start_at, dwell, est) -> list[Stop]:
    """Repeatedly take the stop that can be finished soonest from here."""
    remaining, order = list(stops), []
    pos, t = origin, start_at
    while remaining:
        def done_at(s):
            arrive = t + timedelta(minutes=est.minutes(pos, (s.lat, s.lon)))
            return max(arrive, s.start_at) + dwell
        feasible = [s for s in remaining if done_at(s) <= s.end_at]
        if not feasible:
            order.extend(remaining)  # simulate() reports them as skipped
            break
        nxt = min(feasible, key=done_at)
        t, pos = done_at(nxt), (nxt.lat, nxt.lon)
        order.append(nxt)
        remaining.remove(nxt)
    return order


def maps_url(origin_label: str, stops: list[Stop]) -> str | None:
    if not stops:
        return None
    stops = stops[:MAPS_MAX_STOPS]
    params = {"api": "1", "origin": origin_label, "destination": stops[-1].label,
              "travelmode": "driving"}
    if len(stops) > 1:
        params["waypoints"] = "|".join(s.label for s in stops[:-1])
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def plan_route(origin: tuple[float, float], origin_label: str, stops: list[Stop],
               start_at: datetime | None = None, dwell_min: int = 20,
               estimator: TravelEstimator | None = None) -> RoutePlan:
    """Best visiting order for `stops`, starting from `origin` no earlier than
    `start_at` (default: whenever the first window opens)."""
    est = estimator or HaversineEstimator()
    dwell = timedelta(minutes=dwell_min)
    if not stops:
        return RoutePlan(depart_at=None)
    if start_at is None:
        start_at = min(s.start_at for s in stops) - timedelta(hours=2)

    if len(stops) <= EXHAUSTIVE_MAX:
        best = min((_simulate(order, origin, start_at, dwell, est)
                    for order in permutations(stops)), key=_score)
    else:
        best = _simulate(_greedy(stops, origin, start_at, dwell, est),
                         origin, start_at, dwell, est)
    best.maps_url = maps_url(origin_label, [p.stop for p in best.stops])
    return best


def drive_legs(origin: tuple[float, float], stops: list[Stop],
               estimator: TravelEstimator | None = None) -> list[Leg]:
    """The drive into each stop, visiting `stops` in the order given. A stop
    with no location gets no leg, and the next leg starts from the last
    located point."""
    est = estimator or HaversineEstimator()
    legs, pos = [], origin
    for stop in stops:
        if stop.lat is None or stop.lon is None:
            legs.append(Leg(stop, None, None))
            continue
        here = (stop.lat, stop.lon)
        legs.append(Leg(stop, round(est.minutes(pos, here), 1), round(est.miles(pos, here), 1)))
        pos = here
    return legs


def suggested_order(origin: tuple[float, float], stops: list[Stop],
                    start_at: datetime | None = None, dwell_min: int = 20,
                    estimator: TravelEstimator | None = None) -> list[Stop]:
    """`plan_route`'s best order for the located stops, then every stop it
    could not fit (and any without a location), soonest window first — a
    suggestion the buyer can rearrange, so nothing is dropped."""
    located = [s for s in stops if s.lat is not None and s.lon is not None]
    plan = plan_route(origin, "", located, start_at=start_at, dwell_min=dwell_min,
                      estimator=estimator)
    first = [p.stop for p in plan.stops]
    rest = sorted((s for s in stops if s not in first), key=lambda s: (s.start_at, s.id))
    return first + rest
