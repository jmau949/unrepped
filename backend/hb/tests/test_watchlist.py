import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hb import watchlist
from hb.alerts import channels, rules
from hb.db.models import (
    Alert, AppSetting, Listing, ListingEvent, Property, PropertyTour, TrackedListing,
)

OBS = "2026-10-20T12:00:00+00:00"


def _home(session, n, price=900_000, status="active", watched=False, **over):
    """A home far below the target band, so only watching can put it in alert scope."""
    prop = Property(address_norm=f"{n} WATCH ST", zip="94087", city="Sunnyvale",
                    beds=3, sqft=1600, watched_at=OBS if watched else None)
    session.add(prop)
    session.flush()
    lst = Listing(property_id=prop.id, source="realtor", source_listing_id=f"W{n}",
                  status=status, list_price=price, original_list_price=price,
                  list_date="2026-08-01", **over)
    session.add(lst)
    session.flush()
    return prop, lst


def _event(session, listing, etype, old=None, new=None, observed=OBS):
    e = ListingEvent(listing_id=listing.id, event_type=etype,
                     old_value=None if old is None else str(old),
                     new_value=None if new is None else str(new), observed_at=observed)
    session.add(e)
    session.flush()
    return e


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.listings as listings_module
    import hb.api.tours as tours_module
    import hb.api.tracker as tracker_module
    import hb.api.watchlist as watchlist_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (watchlist_module, tracker_module, listings_module, tours_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


def test_logging_a_tour_watches_and_remove_drops_it(client, session):
    watched, _ = _home(session, 1, watched=True)
    toured, lst = _home(session, 2)
    _home(session, 3)  # neither saved nor toured
    session.commit()

    client.post("/api/tours", json={"listing_id": lst.id, "toured_on": "2026-08-03"})
    session.expire_all()
    assert watchlist.watched_property_ids(session) == {watched.id, toured.id}

    client.patch(f"/api/watchlist/{toured.id}", json={"watching": False})
    session.expire_all()
    assert watchlist.watched_property_ids(session) == {watched.id}  # the tour stays, the home goes
    assert session.execute(select(PropertyTour)).scalar_one().property_id == toured.id

    client.patch(f"/api/watchlist/{toured.id}", json={"watching": True})
    session.expire_all()
    assert watchlist.watched_property_ids(session) == {watched.id, toured.id}


def test_relisted_home_shows_its_current_episode(session):
    prop, old = _home(session, 1, status="delisted", watched=True)
    session.add(TrackedListing(listing_id=old.id, stage="lost", my_max_bid=850_000))
    new = Listing(property_id=prop.id, source="realtor", source_listing_id="W1b",
                  status="active", list_price=880_000, original_list_price=880_000,
                  list_date="2026-10-01")
    session.add(new)
    session.commit()

    (row,) = watchlist.rows(session)
    assert row["id"] == new.id
    assert row["involvement"]["stage"] == "lost"
    assert row["involvement"]["my_max_bid"] == 850_000


def test_sold_outcome_against_ask_and_max_bid(session):
    _, lst = _home(session, 1, status="sold", sold_price=990_000, sold_date="2026-10-10",
                   watched=True)
    session.add(TrackedListing(listing_id=lst.id, stage="passed", my_max_bid=950_000))
    session.commit()

    (row,) = watchlist.rows(session)
    assert row["sold_source"] == "listing"
    assert row["sp_lp"] == 1.1
    assert row["vs_max_bid"] == 40_000


def test_off_market_sale_comes_from_public_record(session):
    prop, lst = _home(session, 1, status="delisted", watched=True)
    prop.price_history = [
        {"date": "2026-10-05", "event": "Sold", "price": 870_000},
        {"date": "2026-08-01", "event": "Listed for sale", "price": 900_000},
        {"date": "2004-03-01", "event": "Sold", "price": 400_000},
    ]
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    session.commit()

    (row,) = watchlist.rows(session)
    assert row["status"] == "sold"
    assert (row["sold_price"], row["sold_date"], row["sold_source"]) == (
        870_000, "2026-10-05", "public_record")


def test_previous_sale_is_not_this_episodes_outcome(session):
    prop, _ = _home(session, 1, status="delisted", watched=True)
    prop.price_history = [{"date": "2004-03-01", "event": "Sold", "price": 400_000}]
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    session.commit()

    (row,) = watchlist.rows(session)
    assert row["status"] == "delisted"
    assert row["sold_price"] is None


def test_rows_sort_by_latest_change(session):
    quiet, qlst = _home(session, 1, watched=True)
    busy, blst = _home(session, 2, watched=True)
    for prop in (quiet, busy):
        session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    _event(session, qlst, "new", None, 900_000, observed="2026-08-01T12:00:00+00:00")
    _event(session, blst, "price_change", 900_000, 850_000)
    session.commit()

    out = watchlist.rows(session)
    assert [r["property_id"] for r in out] == [busy.id, quiet.id]
    assert out[0]["last_change"]["event_type"] == "price_change"
    assert out[0]["watched_at"] == OBS  # the page's "Recently added" sort key


def test_api_remove_and_seen(client, session):
    prop, _ = _home(session, 1, watched=True)
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    session.commit()

    body = client.get("/api/watchlist").json()
    assert body["last_seen_at"] is None
    assert len(body["items"]) == 1

    first = client.post("/api/watchlist/seen").json()
    assert first["previous"] is None
    assert client.get("/api/watchlist").json()["last_seen_at"] == first["at"]

    off = client.patch(f"/api/watchlist/{prop.id}", json={"watching": False}).json()
    assert off["watching"] is False
    assert client.get("/api/watchlist").json()["items"] == []
    assert client.patch(f"/api/watchlist/{prop.id}", json={"watching": True}).json()["watching"]
    assert len(client.get("/api/watchlist").json()["items"]) == 1
    assert client.patch("/api/watchlist/nope", json={"watching": True}).status_code == 404


def test_tracking_a_home_watches_it_and_untracking_keeps_it(client, session):
    prop, lst = _home(session, 1)
    session.commit()
    assert client.get(f"/api/listings/{lst.id}").json()["watching"] is False

    tid = client.post("/api/tracker", json={"listing_id": lst.id}).json()["id"]
    assert client.get(f"/api/listings/{lst.id}").json()["watching"] is True
    client.delete(f"/api/tracker/{tid}")
    assert [r["property_id"] for r in client.get("/api/watchlist").json()["items"]] == [prop.id]


def test_watch_button_adds_an_untracked_untoured_home(client, session):
    prop, lst = _home(session, 1)
    session.commit()

    assert client.patch(f"/api/watchlist/{prop.id}", json={"watching": True}).json()["watching"]
    assert client.get(f"/api/listings/{lst.id}").json()["watching"] is True
    assert len(client.get("/api/watchlist").json()["items"]) == 1


# --- alerts ------------------------------------------------------------------

def test_passed_home_stays_in_price_cut_scope(session):
    _, lst = _home(session, 1, watched=True)
    session.add(TrackedListing(listing_id=lst.id, stage="passed"))
    ev = _event(session, lst, "price_change", 950_000, 900_000)
    session.commit()

    assert rules.evaluate(session, [ev], OBS) == 1
    alert = session.execute(select(Alert)).scalar_one()
    assert alert.type == "price_cut"
    assert alert.tracked_listing_id is None  # passed is not an active pursuit


def test_removed_home_leaves_alert_scope(session):
    prop, lst = _home(session, 1, watched=True)
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    watchlist.set_watching(prop, False)
    ev = _event(session, lst, "price_change", 950_000, 900_000)
    session.commit()

    assert rules.evaluate(session, [ev], OBS) == 0


def test_watched_status_sold_fires_once_with_max_bid(session):
    _, lst = _home(session, 1, status="sold", sold_price=990_000, watched=True)
    session.add(TrackedListing(listing_id=lst.id, stage="passed", my_max_bid=950_000))
    ev = _event(session, lst, "sold", "pending", "sold")
    session.commit()

    assert rules.evaluate(session, [ev], OBS) == 1
    session.commit()
    assert rules.evaluate(session, [ev], OBS) == 0  # D11

    alert = session.execute(select(Alert)).scalar_one()
    assert alert.type == "watched_status"
    msg = channels.format_alert(session, alert)
    assert "sold" in msg and "$990,000" in msg and "+10.0%" in msg
    assert "$40,000 over your max bid" in msg


def test_watched_status_pending_for_toured_home(session):
    prop, lst = _home(session, 1, status="pending", watched=True)
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    ev = _event(session, lst, "pending", "active", "pending")
    unwatched_prop, other = _home(session, 2, status="pending")
    ev2 = _event(session, other, "pending", "active", "pending")
    session.commit()

    assert rules.evaluate(session, [ev, ev2], OBS) == 1
    alert = session.execute(select(Alert)).scalar_one()
    assert alert.listing_id == lst.id
    assert "went pending" in channels.format_alert(session, alert)


def test_watched_status_rule_can_be_disabled(session):
    session.add(AppSetting(key="alert_rules", value={"watched_status": {"enabled": False}}))
    prop, lst = _home(session, 1, status="delisted", watched=True)
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-08-03"))
    ev = _event(session, lst, "delisted", "active", "delisted")
    session.commit()

    assert rules.evaluate(session, [ev], OBS) == 0
