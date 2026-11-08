from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from hb.open_houses.route import (
    MAPS_MAX_STOPS,
    HaversineEstimator,
    Stop,
    drive_legs,
    maps_url,
    nearest_order,
)

HOME = (37.39, -122.10)  # Mountain View
T0 = datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)  # Sat 1 PM PDT


class FlatEstimator:
    """10 minutes between any two distinct points — makes timing exact."""

    def minutes(self, a, b):
        return 0.0 if a == b else 10.0

    def miles(self, a, b):
        return 0.0 if a == b else 3.0


def _stop(i, lat, lon, start_h=0, hours=3, label=None):
    start = T0 + timedelta(hours=start_h)
    return Stop(id=f"s{i}", label=label or f"{i} Main St, Town, CA", lat=lat, lon=lon,
                start_at=start, end_at=start + timedelta(hours=hours))


def test_nearest_order_chains_from_the_previous_stop_not_from_the_start():
    # from home: north-near 1.4 mi, south 2.1 mi, north-far 3.1 mi — sorted by
    # distance from home the day would zigzag north, south, north; the chain
    # goes north, north (1.7 mi on from the first), then south
    north_near = _stop(1, 37.41, -122.10)
    south = _stop(2, 37.36, -122.10)
    north_far = _stop(3, 37.435, -122.10)
    order = nearest_order(HOME, [south, north_far, north_near], estimator=HaversineEstimator())

    assert [s.id for s in order] == ["s1", "s3", "s2"]


def test_nearest_order_starts_from_the_given_point():
    # the same stops, from up north: the chain runs north-far, north-near, south
    stops = [_stop(1, 37.41, -122.10), _stop(2, 37.36, -122.10), _stop(3, 37.435, -122.10)]
    order = nearest_order((37.50, -122.10), stops, estimator=HaversineEstimator())

    assert [s.id for s in order] == ["s3", "s1", "s2"]


def test_nearest_order_keeps_every_stop_and_breaks_ties_by_window():
    later = _stop(1, 37.40, -122.10, start_h=1)
    sooner = _stop(2, 37.41, -122.11, start_h=0)
    nowhere = Stop(id="x", label="9 Lost Ln", lat=None, lon=None,
                   start_at=T0 - timedelta(hours=1), end_at=T0)
    nowhere_later = Stop(id="y", label="10 Lost Ln", lat=None, lon=None,
                         start_at=T0 + timedelta(hours=2), end_at=T0 + timedelta(hours=3))
    order = nearest_order(HOME, [nowhere_later, later, nowhere, sooner], estimator=FlatEstimator())

    # every hop is 10 min, so the sooner window leads; the unlocated go last, soonest first
    assert [s.id for s in order] == ["s2", "s1", "x", "y"]


def test_nearest_order_empty():
    assert nearest_order(HOME, []) == []


def test_drive_legs_follow_the_given_order():
    a, b = _stop(1, 37.40, -122.10), _stop(2, 37.41, -122.11)
    nowhere = Stop(id="x", label="9 Lost Ln", lat=None, lon=None,
                   start_at=T0, end_at=T0 + timedelta(hours=1))
    legs = drive_legs(HOME, [b, nowhere, a, a], estimator=FlatEstimator())

    assert [leg.stop.id for leg in legs] == ["s2", "x", "s1", "s1"]
    assert [leg.drive_min for leg in legs] == [10.0, None, 10.0, 0.0]  # from b, skipping x


def test_maps_url_lists_origin_waypoints_destination():
    a = _stop(1, 37.40, -122.10, label="1 A St, Mountain View, CA 94040")
    b = _stop(2, 37.41, -122.11, start_h=1, label="2 B St, Los Altos, CA 94022")

    q = parse_qs(urlparse(maps_url("100 Test Origin Rd", [a, b])).query)
    assert q["origin"] == ["100 Test Origin Rd"]
    assert q["waypoints"] == ["1 A St, Mountain View, CA 94040"]
    assert q["destination"] == ["2 B St, Los Altos, CA 94022"]
    assert q["travelmode"] == ["driving"]


def test_maps_url_covers_the_first_ten_stops_only():
    stops = [_stop(i, 37.40 + i * 0.01, -122.10) for i in range(12)]

    q = parse_qs(urlparse(maps_url("Home", stops)).query)
    assert q["destination"] == [stops[MAPS_MAX_STOPS - 1].label]
    assert len(q["waypoints"][0].split("|")) == MAPS_MAX_STOPS - 1
    assert maps_url("Home", []) is None
