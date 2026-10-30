from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from hb.open_houses.route import (
    HaversineEstimator,
    Stop,
    drive_legs,
    plan_route,
    suggested_order,
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


def test_departs_just_in_time_and_times_each_stop():
    plan = plan_route(HOME, "Home", [_stop(1, 37.40, -122.10)], estimator=FlatEstimator())

    assert plan.depart_at == T0 - timedelta(minutes=10)
    [only] = plan.stops
    assert only.arrive_at == T0
    assert only.leave_at == T0 + timedelta(minutes=20)
    assert only.wait_min == 0


def test_window_order_beats_distance():
    # the far stop closes early, the near one is open all afternoon:
    # visiting the far one first is the only way to see both
    early_far = _stop(1, 37.50, -122.30, start_h=0, hours=0.75)
    late_near = _stop(2, 37.40, -122.10, start_h=0, hours=4)
    plan = plan_route(HOME, "Home", [late_near, early_far], estimator=HaversineEstimator())

    assert [p.stop.id for p in plan.stops] == ["s1", "s2"]
    assert plan.skipped == []


def test_infeasible_stop_is_skipped_with_reason():
    a = _stop(1, 37.40, -122.10, start_h=0, hours=1)
    b = _stop(2, 37.41, -122.11, start_h=0, hours=0.25)  # 15-min window < 20-min dwell
    plan = plan_route(HOME, "Home", [a, b], estimator=FlatEstimator())

    assert [p.stop.id for p in plan.stops] == ["s1"]
    assert [(s.id, reason) for s, reason in plan.skipped] == \
        [("s2", "open only 15 min")]


def test_late_arrival_reasons():
    a = _stop(1, 37.40, -122.10, start_h=0, hours=0.5)
    plan = plan_route(HOME, "Home", [a], start_at=T0 + timedelta(minutes=15),
                      estimator=FlatEstimator())
    assert plan.skipped[0][1] == "can't get 20 min before it closes"
    plan = plan_route(HOME, "Home", [a], start_at=T0 + timedelta(hours=1),
                      estimator=FlatEstimator())
    assert plan.skipped[0][1] == "closed before you'd arrive"


def test_prefers_less_driving_when_all_fit():
    near = _stop(1, 37.40, -122.10)
    mid = _stop(2, 37.42, -122.12)
    far = _stop(3, 37.45, -122.15)
    plan = plan_route(HOME, "Home", [far, near, mid], estimator=HaversineEstimator())

    assert [p.stop.id for p in plan.stops] == ["s1", "s2", "s3"]


def test_greedy_path_beyond_exhaustive_limit():
    stops = [_stop(i, 37.40 + i * 0.01, -122.10, hours=6) for i in range(10)]
    plan = plan_route(HOME, "Home", stops, estimator=HaversineEstimator())

    assert len(plan.stops) == 10
    assert [p.stop.id for p in plan.stops] == [f"s{i}" for i in range(10)]


def test_maps_url_lists_origin_waypoints_destination():
    a = _stop(1, 37.40, -122.10, label="1 A St, Mountain View, CA 94040")
    b = _stop(2, 37.41, -122.11, start_h=1, label="2 B St, Los Altos, CA 94022")
    plan = plan_route(HOME, "100 Test Origin Rd", [a, b], estimator=FlatEstimator())

    q = parse_qs(urlparse(plan.maps_url).query)
    assert q["origin"] == ["100 Test Origin Rd"]
    assert q["waypoints"] == ["1 A St, Mountain View, CA 94040"]
    assert q["destination"] == ["2 B St, Los Altos, CA 94022"]
    assert q["travelmode"] == ["driving"]


def test_empty_plan():
    plan = plan_route(HOME, "Home", [])
    assert plan.stops == [] and plan.maps_url is None and plan.depart_at is None


def test_drive_legs_follow_the_given_order():
    a, b = _stop(1, 37.40, -122.10), _stop(2, 37.41, -122.11)
    nowhere = Stop(id="x", label="9 Lost Ln", lat=None, lon=None,
                   start_at=T0, end_at=T0 + timedelta(hours=1))
    legs = drive_legs(HOME, [b, nowhere, a, a], estimator=FlatEstimator())

    assert [leg.stop.id for leg in legs] == ["s2", "x", "s1", "s1"]
    assert [leg.drive_min for leg in legs] == [10.0, None, 10.0, 0.0]  # from b, skipping x


def test_suggested_order_keeps_every_stop():
    a = _stop(1, 37.40, -122.10, start_h=0, hours=1)
    short = _stop(2, 37.41, -122.11, start_h=0, hours=0.25)  # can't fit a 20-min visit
    nowhere = Stop(id="x", label="9 Lost Ln", lat=None, lon=None,
                   start_at=T0 - timedelta(hours=1), end_at=T0)
    order = suggested_order(HOME, [short, nowhere, a], estimator=FlatEstimator())

    assert [s.id for s in order] == ["s1", "x", "s2"]  # planned, then the rest soonest first
