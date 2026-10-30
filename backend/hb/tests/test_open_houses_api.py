from datetime import datetime, timedelta, timezone

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
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (listings_module, oh_module):
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


def test_route_optimize_suggests_an_order_and_keeps_every_stop(client, seeded, session):
    near, mid = seeded["near"][1], seeded["mid"][1]
    gone = NOW - timedelta(hours=5)  # already closed: can't fit, still kept (last)
    lid = seeded["far"][0]
    closed = OpenHouse(listing_id=lid, source="realtor", start_at=_iso(gone),
                       end_at=_iso(gone + timedelta(hours=1)), methods=["in_person"])
    session.add(closed)
    session.commit()

    body = client.post("/api/open-houses/route", json={
        "open_house_ids": [closed.id, mid, near], "optimize": True,
        "start_at": _iso(NOW)}).json()
    assert [s["open_house_id"] for s in body["stops"]] == [near, mid, closed.id]


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
