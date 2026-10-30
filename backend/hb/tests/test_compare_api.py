from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from hb.db.models import (
    BuyerProfile,
    CmaRun,
    Listing,
    Property,
    Sale,
    TrackedListing,
)

TODAY = date.today()


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.compare as compare_module
    import hb.api.listings as listings_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (compare_module, listings_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))
    from hb.main import app
    return TestClient(app)


@pytest.fixture
def seeded(session):
    session.add(BuyerProfile(id="default", cash_available=800_000,
                             down_payment=450_000, rate_assumption=6.5))

    rich_prop = Property(address_norm="1 RICH WAY", zip="94087", city="Sunnyvale",
                         lat=37.35, lon=-122.03, beds=3, baths=2.0, sqft=1600,
                         property_type="single_family")
    bare_prop = Property(address_norm="2 BARE CT", zip="94087", city="Sunnyvale",
                         lat=38.10, lon=-121.00, beds=3, baths=2.0, sqft=None,
                         property_type="single_family")
    session.add_all([rich_prop, bare_prop])
    session.flush()
    rich = Listing(property_id=rich_prop.id, source="realtor", source_listing_id="RICH1",
                   status="active", list_price=2_050_000, original_list_price=2_050_000,
                   list_date="2026-06-20", dom_source=10)
    bare = Listing(property_id=bare_prop.id, source="realtor", source_listing_id="BARE1",
                   status="active", list_price=None, original_list_price=None,
                   list_date="2026-06-25")
    session.add_all([rich, bare])
    session.flush()
    session.add(TrackedListing(listing_id=rich.id, stage="disclosures", my_max_bid=2_300_000,
                               disclosure_checklist={"packet_received": True}))
    session.add(CmaRun(property_id=rich_prop.id, estimate=2_250_000, low=2_150_000,
                       high=2_350_000, confidence="high", params={}))
    for i, r in enumerate((1.08, 1.10, 1.12, 1.12, 1.14, 1.15, 1.11, 1.13, 1.10, 1.12)):
        p = Property(address_norm=f"{i} COMP RD", zip="94087", city="Sunnyvale",
                     lat=37.35, lon=-122.03, beds=3, baths=2.0, sqft=1600,
                     property_type="single_family")
        session.add(p)
        session.flush()
        session.add(Sale(property_id=p.id, sale_date=(TODAY - timedelta(days=5 + i)).isoformat(),
                         sale_price=round(2_050_000 * r), original_list_price=2_050_000,
                         sp_lp=r, source="realtor_sold_scan"))
    session.commit()
    return rich, bare


def test_compare_shape_and_graceful_nulls(client, seeded):
    rich, bare = seeded
    body = client.get(f"/api/compare?listing_ids={rich.id},{bare.id}").json()
    assert len(body) == 2
    rich_item, bare_item = body
    for item in body:
        for key in ("cma", "piti_at_point", "price_per_sqft", "hazard_flags",
                    "sqft_mismatch", "tracked", "predicted_sale", "list_price", "address"):
            assert key in item

    assert rich_item["cma"]["estimate"] == 2_250_000
    assert rich_item["predicted_sale"]["point"] > 0
    assert rich_item["piti_at_point"] > 0
    assert rich_item["price_per_sqft"] == round(2_050_000 / 1600)
    assert rich_item["tracked"]["stage"] == "disclosures"
    assert rich_item["tracked"]["my_max_bid"] == 2_300_000

    # bare listing: no CMA, no comps nearby, no sqft, untracked — nulls, not a 500
    assert bare_item["cma"] is None
    assert bare_item["piti_at_point"] is None
    assert bare_item["price_per_sqft"] is None
    assert bare_item["tracked"] is None
    assert bare_item["hazard_flags"] == []
    assert bare_item["sqft_mismatch"] is False


def test_compare_id_count_bounds(client, seeded):
    rich, _ = seeded
    assert client.get("/api/compare?listing_ids=").status_code == 422
    five = ",".join([rich.id] * 5)
    assert client.get(f"/api/compare?listing_ids={five}").status_code == 422


def test_compare_unknown_id_404(client, seeded):
    assert client.get("/api/compare?listing_ids=nope").status_code == 404
