import pytest
from fastapi.testclient import TestClient

from hb.db.models import (
    Alert,
    AppSetting,
    BuyerProfile,
    Listing,
    ListingEvent,
    ListingGroup,
    Property,
    School,
)


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.affordability as afford_module
    import hb.api.alerts as alerts_module
    import hb.api.contacts as contacts_module
    import hb.api.listings as listings_module
    import hb.api.market as market_module
    import hb.api.ops as ops_module
    import hb.api.tracker as tracker_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (ops_module, market_module, listings_module, tracker_module,
                alerts_module, afford_module, contacts_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


@pytest.fixture
def seeded(session):
    # rows normally created by the alembic seed migration (create_all skips it)
    session.add(BuyerProfile(id="default"))
    session.add(AppSetting(key="alert_rules", value={
        "price_cut": {"enabled": True}, "rate_move": {"enabled": True, "bps_threshold": 25},
    }))
    rows = []
    for i, (price, zip5, status) in enumerate([
        (2_500_000, "94087", "active"),
        (3_200_000, "94301", "active"),
        (1_900_000, "94061", "pending"),
    ]):
        prop = Property(address_norm=f"{i} SEED AVE", zip=zip5,
                        city={"94087": "Sunnyvale", "94301": "Palo Alto",
                              "94061": "Redwood City"}[zip5],
                        beds=3 + i, baths=2.0, sqft=1500 + 100 * i, lat=37.3, lon=-122.0)
        session.add(prop)
        session.flush()
        lst = Listing(property_id=prop.id, source="realtor", source_listing_id=f"S{i}",
                      status=status, list_price=price, original_list_price=price,
                      list_date="2026-07-01")
        session.add(lst)
        session.flush()
        rows.append(lst)
    # a price cut on the first listing
    session.add(ListingEvent(listing_id=rows[0].id, event_type="price_change",
                             old_value="2600000", new_value="2500000",
                             observed_at="2026-07-10T00:00:00+00:00"))
    # CA-schools master rows near the seeded properties (all at 37.3,-122.0):
    # one near school per level, plus a far elementary that must NOT be chosen.
    session.add_all([
        School(nces_id="C1", name="Near Elementary", level="elementary",
               lat=37.301, lon=-122.001, district="Test USD", county="Santa Clara",
               rating=9, pct_met=68.0),
        School(nces_id="C2", name="Near Middle", level="middle",
               lat=37.305, lon=-122.004, district="Test USD", county="Santa Clara"),
        School(nces_id="C3", name="Near High", level="high",
               lat=37.31, lon=-122.01, district="Test HSD", county="Santa Clara", rating=8),
        School(nces_id="C4", name="Far Elementary", level="elementary",
               lat=38.0, lon=-121.0, district="Other USD", county="Sacramento", rating=3),
    ])
    session.commit()
    return rows


def test_list_filters_and_shape(client, seeded):
    body = client.get("/api/listings", params={"status": "active"}).json()
    assert body["total"] == 2
    item = body["items"][0]
    assert {"id", "address", "zip", "list_price", "cumulative_dom", "price_cut_count",
            "is_relist", "predicted_sale", "posture", "posture_confidence",
            "posture_p_below_list", "tracked"} <= set(item)
    assert item["posture"] in ("underpriced", "near_market", "overpriced", "unknown")

    cut_only = client.get("/api/listings",
                          params={"status": "active", "has_price_cut": True}).json()
    assert cut_only["total"] == 1
    assert cut_only["items"][0]["price_cut_count"] == 1

    banded = client.get("/api/listings",
                        params={"status": "any", "min_price": 2_000_000,
                                "max_price": 3_000_000}).json()
    assert banded["total"] == 1


def test_text_search_matches_address_city_and_zip(client, seeded):
    """`q` is an AND over whitespace tokens, each matching address/city/unit/zip."""
    by_address = client.get("/api/listings", params={"status": "any", "q": "1 seed"}).json()
    assert by_address["total"] == 1
    assert by_address["items"][0]["address"] == "1 Seed Ave"

    # case-insensitive city match, and a ZIP substring
    assert client.get("/api/listings",
                      params={"status": "any", "q": "sunnyvale"}).json()["total"] == 1
    assert client.get("/api/listings", params={"status": "any", "q": "943"}).json()["total"] == 1

    # tokens narrow rather than widen: no row is both in Sunnyvale and "#2 SEED"
    assert client.get("/api/listings",
                      params={"status": "any", "q": "sunnyvale 2 seed"}).json()["total"] == 0
    assert client.get("/api/listings",
                      params={"status": "any", "q": "nothing-here"}).json()["total"] == 0


def test_cut_pct_derives_from_original_ask(client, seeded, session):
    """`cut_pct` comes from original-vs-current price, so `min_cut_pct` catches
    reductions with no observed `price_change` event."""
    prop = Property(address_norm="9 SLASHED WAY", zip="94087", city="Sunnyvale",
                    beds=3, baths=2.0, sqft=1500, lat=37.3, lon=-122.0)
    session.add(prop)
    session.flush()
    session.add(Listing(property_id=prop.id, source="realtor", source_listing_id="CUT9",
                        status="active", list_price=2_700_000,
                        original_list_price=3_000_000, list_date="2026-06-01"))
    session.commit()

    body = client.get("/api/listings", params={"status": "active", "sort": "cut"}).json()
    top = body["items"][0]
    assert top["cut_pct"] == 10.0 and top["price_cut_count"] == 0  # no event row
    # the seeds never moved off their original ask, event row or not
    assert {i["cut_pct"] for i in body["items"]} == {10.0, None}

    # has_price_cut sees the derived cut; min_cut_pct grades it
    assert client.get("/api/listings", params={
        "status": "active", "has_price_cut": True}).json()["total"] == 2
    assert client.get("/api/listings", params={
        "status": "active", "min_cut_pct": 5}).json()["total"] == 1
    assert client.get("/api/listings", params={
        "status": "active", "min_cut_pct": 25}).json()["total"] == 0


def test_list_multi_status(client, seeded, session):
    _add_sold(session, zip5="94087", city="Sunnyvale", original=2_400_000,
              sold_price=2_650_000, sold_date="2026-07-05", sid="SOLDX")

    body = client.get("/api/listings", params={"status": "active,pending"}).json()
    assert body["total"] == 3  # 2 active + 1 pending, sold excluded
    assert {i["status"] for i in body["items"]} == {"active", "pending"}

    # single-status and "any" behavior unchanged
    assert client.get("/api/listings", params={"status": "pending"}).json()["total"] == 1
    assert client.get("/api/listings", params={"status": "any"}).json()["total"] == 4


def _add_sold(session, *, zip5, city, original, sold_price, sold_date, sid):
    prop = Property(address_norm=f"SOLD {sid} AVE", zip=zip5, city=city,
                    beds=3, baths=2.0, sqft=1600, lat=37.3, lon=-122.0)
    session.add(prop)
    session.flush()
    session.add(Listing(property_id=prop.id, source="realtor", source_listing_id=sid,
                        status="sold", list_price=original, original_list_price=original,
                        sold_price=sold_price, sold_date=sold_date, list_date="2026-06-01"))
    session.commit()


def test_sold_summary_fields_filter_and_sort(client, seeded, session):
    # two in-band solds (by SOLD price) plus one that sold above the band
    _add_sold(session, zip5="94087", city="Sunnyvale", original=2_400_000,
              sold_price=2_650_000, sold_date="2026-07-05", sid="SOLD1")
    _add_sold(session, zip5="94301", city="Palo Alto", original=2_100_000,
              sold_price=2_250_000, sold_date="2026-07-12", sid="SOLD2")
    _add_sold(session, zip5="94301", city="Palo Alto", original=3_100_000,
              sold_price=3_400_000, sold_date="2026-07-09", sid="SOLD3")

    body = client.get("/api/listings", params={
        "status": "sold", "min_sold_price": 2_000_000, "max_sold_price": 3_000_000,
        "sort": "sold_date"}).json()
    assert body["total"] == 2  # the $3.4M sale is excluded by max_sold_price

    # summary now carries sold fields + the original ask for a Δ-vs-ask calc
    first = body["items"][0]
    assert {"sold_price", "sold_date", "original_list_price"} <= set(first)
    # sort=sold_date is newest-first → SOLD2 (2026-07-12) leads
    assert first["sold_date"] == "2026-07-12"
    assert first["sold_price"] == 2_250_000 and first["original_list_price"] == 2_100_000

    # min_sold_price above both in-band sales empties the result
    empty = client.get("/api/listings", params={
        "status": "sold", "min_sold_price": 2_700_000, "max_sold_price": 3_000_000}).json()
    assert empty["total"] == 0


def test_detail_view_stamps_viewed_at(client, seeded, session):
    """Opening the detail page marks a listing viewed (Sold-page indicators,
    docs/08 §2b); re-opening does not move the timestamp while the status holds
    (listing-scan clears it on the transition to sold, see test_listing_scan)."""
    _add_sold(session, zip5="94087", city="Sunnyvale", original=2_400_000,
              sold_price=2_650_000, sold_date="2026-07-05", sid="SOLDV")

    body = client.get("/api/listings", params={"status": "sold"}).json()
    assert body["total"] == 1
    assert body["items"][0]["viewed_at"] is None
    listing_id = body["items"][0]["id"]

    first = client.get(f"/api/listings/{listing_id}").json()["viewed_at"]
    assert first is not None

    # visible on the list, and a second detail view keeps the original stamp
    body = client.get("/api/listings", params={"status": "sold"}).json()
    assert body["items"][0]["viewed_at"] == first
    assert client.get(f"/api/listings/{listing_id}").json()["viewed_at"] == first


def test_detail_and_patches(client, seeded):
    listing_id = seeded[0].id
    detail = client.get(f"/api/listings/{listing_id}").json()
    assert detail["events"][0]["event_type"] == "price_change"
    assert detail["property"]["condition_tag"] is None
    # nearest school per level, elementary → middle → high; the far elementary
    # (C4) must lose to the near one (C1).
    schools = detail["property"]["schools"]
    assert [s["level"] for s in schools] == ["elementary", "middle", "high"]
    assert schools[0]["name"] == "Near Elementary"  # not "Far Elementary"
    assert schools[0]["rating"] == 9 and schools[0]["district"] == "Test USD"
    assert schools[0]["pct_met"] == 68.0
    assert schools[0]["distance_mi"] < 1.0
    assert schools[1]["rating"] is None  # C2 unrated -> null passes through
    # no district polygons seeded -> flagged nearest fallback, ratings list present
    assert all(s["assignment"] == "nearest" for s in schools)
    assert all(s["ratings"] == [] for s in schools)
    assert detail["posture_detail"]["posture"] == detail["posture"]
    assert isinstance(detail["posture_detail"]["signals"], list)
    # the seeded cut listing carries a price-cut signal
    assert any(s["id"] == "price_cuts" for s in detail["posture_detail"]["signals"])

    resp = client.patch(f"/api/listings/{listing_id}", json={"offer_due_at": "2026-07-20"})
    assert resp.json()["offer_due_at"] == "2026-07-20"

    prop_id = detail["property_id"]
    resp = client.patch(f"/api/properties/{prop_id}", json={"condition_tag": "renovated"})
    assert resp.json()["condition_tag"] == "renovated"
    assert client.patch(f"/api/properties/{prop_id}",
                        json={"condition_tag": "bogus"}).status_code == 422


def test_detail_carries_the_listing_side(client, seeded, session):
    """The agent/office/broker block off the MLS record, normalized by
    hb/listing_contact.py, plus the contacts saved on the listing (docs/08 §3 1c)."""
    seeded[0].raw = {
        "agent_name": "Jane Lister", "agent_email": "jlister@example.com",
        "agent_phones": [
            {"ext": None, "primary": True, "type": "Mobile", "number": "6505550123"},
            {"ext": None, "primary": False, "type": "Fax", "number": "6500000000"},
        ],
        "office_name": "Example Realty Group",
        "office_phones": [{"number": "(650) 555-0177", "type": "Office", "primary": True}],
        "broker_name": "Example Realty - Broker", "mls": "SJCA", "mls_id": "ML1",
    }
    session.commit()

    detail = client.get(f"/api/listings/{seeded[0].id}").json()
    side = detail["listing_contact"]
    assert side["agent"]["name"] == "Jane Lister"
    assert [p["number"] for p in side["agent"]["phones"]] == ["6505550123"]  # fax dropped
    assert side["agent"]["phones"][0]["sms"] is True
    assert side["office"]["phones"][0]["number"] == "6505550177"
    assert side["broker"] == {"name": "Example Realty - Broker"}
    assert side["mls"] == {"system": "SJCA", "id": "ML1"}
    assert detail["contacts"] == []

    # no advertiser on the source record -> null, and the page shows its empty state
    assert client.get(f"/api/listings/{seeded[1].id}").json()["listing_contact"] is None


def test_detail_carries_the_remarks(client, seeded, session):
    """The agent's public remarks, kept verbatim in `listings.raw.text` by the
    scan (05 §4.2), reach the page as `remarks`; blank or absent -> null."""
    seeded[0].raw = {"text": "  Corner lot in Briarwood. Offers due Tuesday.  "}
    seeded[1].raw = {"text": ""}
    session.commit()

    assert client.get(f"/api/listings/{seeded[0].id}").json()["remarks"] ==         "Corner lot in Briarwood. Offers due Tuesday."
    assert client.get(f"/api/listings/{seeded[1].id}").json()["remarks"] is None


def test_detail_episodes_carry_prices_and_dates(client, seeded, session):
    # a delisted first episode + the seeded active listing, stitched into a group
    lst = seeded[0]
    group = ListingGroup(property_id=lst.property_id, first_list_date="2026-06-04",
                         cumulative_dom=45, episode_count=2, ended_by="open")
    session.add(group)
    session.flush()
    session.add(Listing(property_id=lst.property_id, source="realtor",
                        source_listing_id="OLD1", status="delisted",
                        list_price=2_880_000, original_list_price=2_880_000,
                        list_date="2026-06-04", delist_date="2026-07-15",
                        listing_group_id=group.id))
    lst.listing_group_id = group.id
    lst.pending_date = "2026-07-22"
    session.commit()

    eps = client.get(f"/api/listings/{lst.id}").json()["listing_group"]["episodes"]
    assert [e["list_date"] for e in eps] == ["2026-06-04", "2026-07-01"]
    assert eps[0]["original_list_price"] == 2_880_000
    assert eps[0]["delist_date"] == "2026-07-15"
    assert eps[1]["pending_date"] == "2026-07-22"
    assert {"sold_date", "sold_price", "status"} <= set(eps[0])


def test_episode_listed_price_survives_a_price_cut(client, seeded, session):
    """The Listed row is the price the episode opened at. Built from the live
    `list_price` it would rewrite itself on every cut, so a home listed at
    $2.399M and cut to $2.35M read "Listed $2.35M" right above
    "Price change $2.399M -> $2.35M" (docs/08 §3)."""
    lst = seeded[0]
    group = ListingGroup(property_id=lst.property_id, first_list_date=lst.list_date,
                         cumulative_dom=41, episode_count=1, ended_by="open")
    session.add(group)
    session.flush()
    lst.listing_group_id = group.id
    lst.original_list_price = 2_399_000
    lst.list_price = 2_350_000  # cut after listing
    session.commit()

    eps = client.get(f"/api/listings/{lst.id}").json()["listing_group"]["episodes"]
    assert eps[0]["original_list_price"] == 2_399_000


def test_detail_returns_cached_price_history(client, seeded, session, monkeypatch):
    from hb.db.models import Property
    from hb.pipelines import price_history
    calls = []
    monkeypatch.setattr(price_history, "fetch_price_history",
                        lambda *a, **k: calls.append(a) or [])
    # history is populated by the scrapes and cached on the property row
    prop = session.get(Property, seeded[0].property_id)
    prop.price_history = [{"date": "2001-12-21", "event": "Sold", "price": 480_000}]
    prop.price_history_fetched_at = "2026-07-15T00:00:00+00:00"
    session.commit()

    detail = client.get(f"/api/listings/{seeded[0].id}").json()
    assert detail["price_history"] == [{"date": "2001-12-21", "event": "Sold", "price": 480_000}]
    assert calls == []  # the detail GET must NOT fetch from Realtor in the request path


def test_tracker_idempotent_and_stages(client, seeded, session):
    listing_id = seeded[0].id
    untracked = client.get(f"/api/listings/{listing_id}").json()
    assert (untracked["tracked_id"], untracked["tracked_stage"]) == (None, None)

    first = client.post("/api/tracker", json={"listing_id": listing_id}).json()
    second = client.post("/api/tracker", json={"listing_id": listing_id}).json()
    assert first["id"] == second["id"]  # idempotent

    tracked = client.get("/api/tracker").json()
    assert len(tracked) == 1
    assert tracked[0]["listing"]["tracked"] is True

    tid = first["id"]
    assert client.patch(f"/api/tracker/{tid}", json={"stage": "toured"}).json()["stage"] == "toured"
    assert client.patch(f"/api/tracker/{tid}", json={"stage": "nope"}).status_code == 422

    detail = client.get(f"/api/listings/{listing_id}").json()
    assert (detail["tracked_id"], detail["tracked_stage"]) == (tid, "toured")

    merged = client.patch(f"/api/tracker/{tid}",
                          json={"disclosure_checklist": {"packet_received": True}}).json()
    assert merged["disclosure_checklist"]["packet_received"] is True

    assert client.delete(f"/api/tracker/{tid}").status_code == 200
    assert client.get("/api/tracker").json() == []
    assert client.get(f"/api/listings/{listing_id}").json()["tracked_stage"] is None


def test_area_median_dom_queried_once_per_page(client, seeded, engine):
    """`exposure.area_median_dom` is a city-level aggregate: same answer for
    every row on the page. overbid.predict, valuation.predicted_sale and
    posture.classify all want it via `exposure.inputs`, so without the shared
    page cache it ran several times per listing and dominated the request.
    Assert the page issues ONE such query however many rows it returns."""
    from sqlalchemy import event

    seen: list[str] = []

    def spy(conn, cursor, statement, params, context, executemany):
        # "median_dom" is a bound parameter, not statement text — match the table
        # and the param together
        if "market_metrics" in statement and "median_dom" in [str(p) for p in (params or ())]:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        body = client.get("/api/listings", params={"status": "any"}).json()
    finally:
        event.remove(engine, "before_cursor_execute", spy)

    assert body["total"] >= 3  # enough rows that an N+1 would show
    assert len(seen) == 1, f"{len(seen)} median_dom queries for {body['total']} listings"


def test_untrack_detaches_alerts(client, seeded, session):
    """Untracking a home that has fired alerts must not 500. `alerts.tracked_listing_id`
    is a real FK and the engine runs with PRAGMA foreign_keys=ON, so the delete has to
    detach the alerts first — and they stay in the inbox, still pointing at the home."""
    listing_id = seeded[0].id
    tid = client.post("/api/tracker", json={"listing_id": listing_id}).json()["id"]
    session.add(Alert(type="offer_date_soon", listing_id=listing_id,
                      tracked_listing_id=tid, dedup_key=f"offer_date_soon:{tid}:x"))
    session.commit()

    assert client.delete(f"/api/tracker/{tid}").status_code == 200
    assert client.get("/api/tracker").json() == []

    kept = client.get("/api/alerts").json()
    assert [a["listing_id"] for a in kept] == [listing_id]  # history survives untracking
    session.expire_all()
    assert session.get(Alert, kept[0]["id"]).tracked_listing_id is None


def test_alert_rules_roundtrip(client, seeded):
    rules = client.get("/api/alerts/rules").json()
    assert rules["price_cut"]["enabled"] is True

    updated = client.put("/api/alerts/rules",
                         json={"price_cut": {"enabled": False}}).json()
    assert updated["price_cut"]["enabled"] is False
    assert "rate_move" in updated  # merge, not replace


def test_profile_and_calc_endpoints(client, seeded):
    profile = client.get("/api/profile").json()
    assert profile["down_payment"] == 0  # dollars, unset by default

    profile["cash_available"] = 600_000
    assert client.put("/api/profile", json=profile).json()["cash_available"] == 600_000

    calc = client.post("/api/affordability/calc",
                       json={"price": 2_200_000, "city": "Sunnyvale", "rate": 6.5,
                             "down_payment": 440_000}).json()
    assert calc["piti"] == pytest.approx(13_721, abs=1)
    assert calc["breakdown"]["pmi"] == 0
