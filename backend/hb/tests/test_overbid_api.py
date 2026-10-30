from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from hb.db.models import Listing, Property, Sale

TODAY = date.today()


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.listings as listings_module
    import hb.api.overbid as overbid_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (overbid_module, listings_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))
    from hb.main import app
    return TestClient(app)


@pytest.fixture
def seeded(session):
    prop = Property(address_norm="1 SUBJECT WAY", zip="94087", city="Sunnyvale",
                    lat=37.35, lon=-122.03, beds=3, baths=2.0, sqft=1600,
                    property_type="single_family")
    session.add(prop)
    session.flush()
    lst = Listing(property_id=prop.id, source="realtor", source_listing_id="SUBJ1",
                  status="active", list_price=2_050_000, original_list_price=2_050_000,
                  list_date="2026-06-20", dom_source=10)
    session.add(lst)
    session.flush()
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
    return lst


def test_overbid_shape(client, seeded):
    body = client.get(f"/api/overbid/{seeded.id}").json()
    assert body["basis"] in ("fresh", "stale")
    assert body["n_comps"] == 10
    for key in ("list_price", "p25", "p50", "p75", "predicted", "histogram", "comps",
                "n_eff", "window_days", "atypical_pricing"):
        assert key in body
    assert body["predicted"]["low"] <= body["predicted"]["point"] <= body["predicted"]["high"]


def test_overbid_404(client, seeded):
    assert client.get("/api/overbid/nope").status_code == 404


def test_predicted_sale_in_listings(client, seeded):
    body = client.get("/api/listings", params={"status": "active"}).json()
    item = next(i for i in body["items"] if i["id"] == seeded.id)
    assert item["predicted_sale"] is not None
    assert item["predicted_sale"]["basis"] in ("fresh", "stale")
    assert item["predicted_sale"]["point"] > 0
