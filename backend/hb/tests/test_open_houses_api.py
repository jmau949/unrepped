from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import hb.open_houses.geocode as geocode
from hb.config import settings
from hb.db.models import AppSetting, Listing, OpenHouse, Property

NOW = datetime.now(timezone.utc).replace(microsecond=0)
HOME = {"address": "100 Test Origin Rd, Mountain View, CA 94040",
        "lat": 37.40, "lon": -122.10}


def _iso(dt):
    return dt.isoformat(timespec="seconds")


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.listings as listings_module
    import hb.api.open_houses as oh_module
    import hb.api.tours as tours_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (listings_module, oh_module, tours_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))
    monkeypatch.setattr(settings, "home_address", "")

    from hb.main import app

    return TestClient(app)


@pytest.fixture
def seeded(session):
    """Three active homes with open houses 1h / 25h / 49h out, at ~0.7 / ~5 / ~12 mi."""
    ids = {}
    for name, lat, lon, price, hours_out in [
        ("near", 37.39, -122.10, 2_800_000, 1),
        ("mid", 37.42, -122.18, 2_100_000, 25),
        ("far", 37.55, -122.25, 2_500_000, 49),
    ]:
        prop = Property(address_norm=f"1 {name.upper()} ST", zip="94040", city="Mountain View",
                        state="CA", lat=lat, lon=lon)
        session.add(prop)
        session.flush()
        lst = Listing(property_id=prop.id, source="realtor", source_listing_id=name,
                      status="active", list_price=price)
        session.add(lst)
        session.flush()
        start = NOW + timedelta(hours=hours_out)
        oh = OpenHouse(listing_id=lst.id, source="realtor", start_at=_iso(start),
                       end_at=_iso(start + timedelta(hours=3)), methods=["in_person"])
        session.add(oh)
        session.flush()
        ids[name] = (lst.id, oh.id)
    session.add(AppSetting(key="home_location", value=HOME))
    session.commit()
    return ids


def _window(hours):
    return {"from": _iso(NOW), "to": _iso(NOW + timedelta(hours=hours))}


def test_list_sorts_by_time_with_distance_and_summary(client, seeded):
    body = client.get("/api/open-houses", params=_window(72)).json()

    assert body["origin"] == HOME
    assert [i["listing_id"] for i in body["items"]] == \
        [seeded["near"][0], seeded["mid"][0], seeded["far"][0]]
    near = body["items"][0]
    assert 0 < near["distance_mi"] < 1.5
    assert near["listing"]["list_price"] == 2_800_000
    assert near["listing"]["next_open_house"]["start_at"] == near["start_at"]


def test_list_filters_window_distance_and_sorts(client, seeded):
    in_day = client.get("/api/open-houses", params=_window(24)).json()["items"]
    assert [i["listing_id"] for i in in_day] == [seeded["near"][0]]

    close = client.get("/api/open-houses", params={**_window(72), "max_miles": 6}).json()["items"]
    assert {i["listing_id"] for i in close} == {seeded["near"][0], seeded["mid"][0]}

    by_price = client.get("/api/open-houses", params={**_window(72), "sort": "price"}).json()
    assert [i["listing"]["list_price"] for i in by_price["items"]] == \
        [2_100_000, 2_500_000, 2_800_000]


def test_list_filters_by_price_range(client, seeded):
    def prices(**params):
        items = client.get("/api/open-houses", params={**_window(72), **params}).json()["items"]
        return sorted(i["listing"]["list_price"] for i in items)

    assert prices(min_price=2_400_000) == [2_500_000, 2_800_000]
    assert prices(max_price=2_600_000) == [2_100_000, 2_500_000]
    assert prices(min_price=2_200_000, max_price=2_600_000) == [2_500_000]


def test_pending_listing_hides_its_open_houses(client, seeded, session):
    session.get(Listing, seeded["near"][0]).status = "pending"
    session.commit()
    items = client.get("/api/open-houses", params=_window(72)).json()["items"]
    assert seeded["near"][0] not in {i["listing_id"] for i in items}


def test_put_origin_geocodes_and_persists(client, session, monkeypatch):
    monkeypatch.setattr(geocode, "fetch_census", lambda address: {"result": {"addressMatches": [
        {"coordinates": {"x": -122.10, "y": 37.40}, "matchedAddress": "X"}]}})

    r = client.put("/api/open-houses/origin", json={"address": " 100 Test Origin Rd "})
    assert r.status_code == 200
    assert r.json()["origin"] == {"address": "100 Test Origin Rd",
                                  "lat": 37.40, "lon": -122.10}
    assert client.get("/api/open-houses/origin").json()["origin"]["lat"] == 37.40


def test_put_origin_unresolvable_is_422(client, monkeypatch):
    monkeypatch.setattr(geocode, "fetch_census",
                        lambda address: {"result": {"addressMatches": []}})
    r = client.put("/api/open-houses/origin", json={"address": "nowhere"})
    assert r.status_code == 422


def test_origin_seeds_from_home_address(client, monkeypatch):
    calls = []

    def fake(address):
        calls.append(address)
        return {"result": {"addressMatches": [{"coordinates": {"x": -122.0, "y": 37.0}}]}}

    monkeypatch.setattr(geocode, "fetch_census", fake)
    monkeypatch.setattr(settings, "home_address", "1 Seed St, Town, CA")

    assert client.get("/api/open-houses/origin").json()["origin"]["address"] == "1 Seed St, Town, CA"
    client.get("/api/open-houses/origin")
    assert calls == ["1 Seed St, Town, CA"]  # geocoded once, then read from settings


def test_route_drives_the_given_order_and_links_maps(client, seeded):
    ids = [seeded["mid"][1], seeded["near"][1]]
    body = client.post("/api/open-houses/route", json={"open_house_ids": ids}).json()

    assert [s["open_house_id"] for s in body["stops"]] == ids  # the buyer's order, kept
    assert body["stops"][1]["address"] == "1 Near St, Mountain View, CA 94040"
    assert all(s["drive_min"] > 0 for s in body["stops"])
    assert "arrive_at" not in body["stops"][0] and "skipped" not in body
    assert body["total_drive_min"] == pytest.approx(sum(s["drive_min"] for s in body["stops"]), abs=0.2)
    assert body["maps_url"].startswith("https://www.google.com/maps/dir/?api=1")
    assert body["maps_stops"] == 2


def test_route_nearest_from_chains_stops_and_keeps_every_one(client, seeded, session):
    """`nearest_from` orders the stops nearest-next from that point (05 §4c) —
    here from up north, so the day runs far → mid → near — a home with no map
    location goes last, and the drive legs still start from home."""
    near, mid, far = (seeded[k][1] for k in ("near", "mid", "far"))
    prop = Property(address_norm="9 LOST LN", zip="94040", city="Mountain View", state="CA")
    session.add(prop)
    session.flush()
    lst = Listing(property_id=prop.id, source="realtor", source_listing_id="lost",
                  status="active", list_price=1_000_000)
    session.add(lst)
    session.flush()
    start = NOW + timedelta(hours=2)
    nowhere = OpenHouse(listing_id=lst.id, source="realtor", start_at=_iso(start),
                        end_at=_iso(start + timedelta(hours=2)), methods=["in_person"])
    session.add(nowhere)
    session.commit()

    body = client.post("/api/open-houses/route", json={
        "open_house_ids": [near, nowhere.id, mid, far],
        "nearest_from": {"lat": 37.60, "lon": -122.30}}).json()
    assert [s["open_house_id"] for s in body["stops"]] == [far, mid, near, nowhere.id]
    assert body["stops"][0]["drive_miles"] > 10  # the leg into "far" is from home, not from up north
    assert body["stops"][3]["drive_min"] is None
    assert body["maps_stops"] == 4

    bad = client.post("/api/open-houses/route", json={
        "open_house_ids": [near], "nearest_from": {"lat": 91, "lon": 0}})
    assert bad.status_code == 422


def test_route_validation(client, seeded, session):
    assert client.post("/api/open-houses/route", json={"open_house_ids": []}).status_code == 422
    assert client.post("/api/open-houses/route",
                       json={"open_house_ids": ["nope"]}).status_code == 404
    many = [seeded["near"][1]] * 12  # no stop cap: a repeated id is just one stop
    assert len(client.post("/api/open-houses/route",
                           json={"open_house_ids": many}).json()["stops"]) == 1
    session.delete(session.get(AppSetting, "home_location"))
    session.commit()
    r = client.post("/api/open-houses/route", json={"open_house_ids": [seeded["near"][1]]})
    assert r.status_code == 422


def test_listings_summary_carries_next_open_house(client, seeded):
    items = client.get("/api/listings").json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[seeded["far"][0]]["next_open_house"]["end_at"] > _iso(NOW)


def test_detail_carries_every_upcoming_slot(client, seeded, session):
    """The detail page lists each slot still to come with the source's note and
    the scheduled/cancelled flags, in the market zone (docs/08 §3 1d); slots
    already over are left out, and a home that is no longer active lists none."""
    lid, oh_id = seeded["near"]
    session.get(OpenHouse, oh_id).description = "This is a Twilight Tour!"
    later = NOW + timedelta(hours=30)
    session.add(OpenHouse(listing_id=lid, source="realtor", start_at=_iso(later),
                          end_at=_iso(later + timedelta(hours=2)), methods=["virtual"],
                          href="https://example.com/tour", scheduled_at=_iso(NOW),
                          cancelled_at=_iso(NOW)))
    gone = NOW - timedelta(days=2)
    session.add(OpenHouse(listing_id=lid, source="realtor", start_at=_iso(gone),
                          end_at=_iso(gone + timedelta(hours=3)), methods=["in_person"]))
    session.commit()

    body = client.get(f"/api/listings/{lid}").json()
    assert body["timezone"] == settings.timezone
    slots = body["open_houses"]
    assert [s["id"] for s in slots][0] == oh_id and len(slots) == 2  # soonest first, past slot gone
    assert slots[0]["description"] == "This is a Twilight Tour!"
    assert (slots[0]["scheduled"], slots[0]["cancelled"]) == (False, False)
    assert slots[1]["href"] == "https://example.com/tour" and slots[1]["methods"] == ["virtual"]
    assert (slots[1]["scheduled"], slots[1]["cancelled"]) == (True, True)  # kept, flagged

    client.put(f"/api/open-houses/{oh_id}/schedule")  # the page's toggle round-trips
    assert client.get(f"/api/listings/{lid}").json()["open_houses"][0]["scheduled"] is True

    session.get(Listing, lid).status = "pending"
    session.commit()
    assert client.get(f"/api/listings/{lid}").json()["open_houses"] == []


def test_schedule_round_trip(client, seeded):
    mid, far = seeded["mid"][1], seeded["far"][1]
    assert client.get("/api/open-houses/schedule").json()["items"] == []

    assert client.put(f"/api/open-houses/{far}/schedule").json() == {"id": far, "scheduled": True}
    client.put(f"/api/open-houses/{mid}/schedule")
    client.put(f"/api/open-houses/{mid}/schedule")  # idempotent

    body = client.get("/api/open-houses/schedule").json()
    assert [i["id"] for i in body["items"]] == [far, mid]  # the order they were added
    assert body["items"][0]["distance_mi"] is not None
    listed = {i["id"]: i for i in client.get("/api/open-houses", params=_window(72)).json()["items"]}
    assert listed[mid]["scheduled"] and not listed[seeded["near"][1]]["scheduled"]

    client.delete(f"/api/open-houses/{mid}/schedule")
    assert [i["id"] for i in client.get("/api/open-houses/schedule").json()["items"]] == [far]
    assert client.put("/api/open-houses/nope/schedule").status_code == 404


def test_cancelled_scheduled_slot_stays_on_schedule_only(client, seeded, session):
    lid, oh_id = seeded["near"]
    oh = session.get(OpenHouse, oh_id)
    oh.scheduled_at = oh.cancelled_at = _iso(NOW)
    session.commit()

    sched = client.get("/api/open-houses/schedule").json()["items"]
    assert [(i["id"], i["cancelled"]) for i in sched] == [(oh_id, True)]
    listed = client.get("/api/open-houses", params=_window(72)).json()["items"]
    assert oh_id not in {i["id"] for i in listed}
    by_id = {i["id"]: i for i in client.get("/api/listings").json()["items"]}
    assert by_id[lid]["next_open_house"] is None

    client.delete(f"/api/open-houses/{oh_id}/schedule")  # removing a cancelled slot drops it
    session.expire_all()
    assert session.get(OpenHouse, oh_id) is None


def test_reorder_schedule_swaps_only_the_given_slots(client, seeded):
    near, mid, far = seeded["near"][1], seeded["mid"][1], seeded["far"][1]
    for oh_id in (near, mid, far):
        client.put(f"/api/open-houses/{oh_id}/schedule")

    def order():
        return [i["id"] for i in client.get("/api/open-houses/schedule").json()["items"]]

    assert client.put("/api/open-houses/schedule/order",
                      json={"open_house_ids": [far, near]}).status_code == 200
    assert order() == [far, mid, near]  # mid keeps its place

    client.delete(f"/api/open-houses/{mid}/schedule")
    client.put(f"/api/open-houses/{mid}/schedule")  # re-added -> last
    assert order() == [far, near, mid]

    assert client.put("/api/open-houses/schedule/order",
                      json={"open_house_ids": [near, near]}).status_code == 422
    client.delete(f"/api/open-houses/{mid}/schedule")
    assert client.put("/api/open-houses/schedule/order",
                      json={"open_house_ids": [mid, near]}).status_code == 404


def _past_slot(session, seeded, name, hours_ago):
    """Move a seeded home's slot into the past: it started `hours_ago` and ran 1 h."""
    oh = session.get(OpenHouse, seeded[name][1])
    start = NOW - timedelta(hours=hours_ago)
    oh.start_at, oh.end_at = _iso(start), _iso(start + timedelta(hours=1))
    session.commit()
    return oh.id


def test_ended_scheduled_slots_are_the_past_schedule(client, seeded, session):
    older = _past_slot(session, seeded, "mid", 50)
    newer = _past_slot(session, seeded, "far", 26)
    for oh_id in (older, newer, seeded["near"][1]):
        client.put(f"/api/open-houses/{oh_id}/schedule")

    upcoming = client.get("/api/open-houses/schedule").json()
    assert [i["id"] for i in upcoming["items"]] == [seeded["near"][1]]
    past = client.get("/api/open-houses/schedule", params={"when": "past"}).json()
    assert [i["id"] for i in past["items"]] == [newer, older]  # most recent first
    assert past["visited"] == 0 and not any(i["visited"] for i in past["items"])
    assert client.get("/api/open-houses/schedule",
                      params={"when": "later"}).status_code == 422


def test_mark_visited_round_trip(client, seeded, session):
    went = _past_slot(session, seeded, "mid", 26)
    skipped = _past_slot(session, seeded, "far", 50)
    client.put(f"/api/open-houses/{skipped}/schedule")

    # visiting a slot that was never scheduled puts it on the schedule too
    assert client.put(f"/api/open-houses/{went}/visit").json() == {
        "id": went, "scheduled": True, "visited": True}
    client.put(f"/api/open-houses/{went}/visit")  # idempotent
    past = client.get("/api/open-houses/schedule", params={"when": "past"}).json()
    assert {i["id"]: i["visited"] for i in past["items"]} == {went: True, skipped: False}
    assert past["visited"] == 1

    assert client.delete(f"/api/open-houses/{went}/visit").json() == {"id": went, "visited": False}
    past = client.get("/api/open-houses/schedule", params={"when": "past"}).json()
    assert past["visited"] == 0 and len(past["items"]) == 2  # still scheduled

    client.put(f"/api/open-houses/{went}/visit")
    client.delete(f"/api/open-houses/{went}/schedule")  # unscheduling forgets the visit
    session.expire_all()
    assert session.get(OpenHouse, went).visited_at is None


def test_visit_needs_a_started_slot(client, seeded):
    future = seeded["far"][1]
    client.put(f"/api/open-houses/{future}/schedule")
    assert client.put(f"/api/open-houses/{future}/visit").status_code == 422
    assert client.put("/api/open-houses/nope/visit").status_code == 404
    assert client.delete("/api/open-houses/nope/visit").status_code == 404


def test_logging_a_tour_visits_that_days_scheduled_slot(client, seeded, session):
    lid, _ = seeded["mid"]
    went = _past_slot(session, seeded, "mid", 2)
    client.put(f"/api/open-houses/{went}/schedule")
    other_day = _past_slot(session, seeded, "far", 50)
    client.put(f"/api/open-houses/{other_day}/schedule")

    day = datetime.fromisoformat(session.get(OpenHouse, went).start_at).astimezone(
        ZoneInfo(settings.timezone)).date().isoformat()
    assert client.post("/api/tours", json={"listing_id": lid, "toured_on": day}).status_code == 200
    far_lid = seeded["far"][0]
    client.post("/api/tours", json={"listing_id": far_lid, "toured_on": day})  # wrong day
    past = client.get("/api/open-houses/schedule", params={"when": "past"}).json()
    assert {i["id"]: i["visited"] for i in past["items"]} == {went: True, other_day: False}
