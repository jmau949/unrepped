from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from hb.db.models import BuyerProfile, Listing, Property, Sale

TODAY = date.today()


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.listings as listings_module
    import hb.api.offer as offer_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (offer_module, listings_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))
    from hb.main import app
    return TestClient(app)


@pytest.fixture
def seeded(session):
    session.add(BuyerProfile(id="default", cash_available=800_000,
                             down_payment=450_000, rate_assumption=6.5))
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


def test_solve_shape(client, seeded):
    body = client.post("/api/offer/solve", json={"listing_id": seeded.id}).json()
    for key in ("max_defensible_bid", "cma_estimate", "predicted", "verdict",
                "verdict_template", "escalation_cap", "gap_capped", "ltv_capped",
                "e_basis", "recommendation", "opening_range", "ceiling", "posture",
                "confidence"):
        assert key in body
    assert body["max_defensible_bid"] > 0
    # the escalation cap is the value-justified ceiling, never above the cash max
    assert body["escalation_cap"] == body["ceiling"] <= body["max_defensible_bid"]
    assert body["predicted"]["basis"] in ("fresh", "stale")
    assert body["recommendation"] in ("underbid", "at_list", "overbid")
    assert body["opening_range"]["low"] <= body["opening_range"]["high"]
    assert body["posture"]["posture"] in ("underpriced", "near_market", "overpriced", "unknown")
    assert body["e_basis"] == "adjusted_blend"
    assert body["verdict"]


def test_solve_overrides_change_answer(client, seeded):
    base = client.post("/api/offer/solve", json={"listing_id": seeded.id}).json()
    tight = client.post("/api/offer/solve", json={
        "listing_id": seeded.id,
        "overrides": {"cash_available": 470_000},  # barely above the down payment
    }).json()
    assert tight["max_defensible_bid"] < base["max_defensible_bid"]


def test_solve_404(client, seeded):
    assert client.post("/api/offer/solve", json={"listing_id": "nope"}).status_code == 404


def test_solve_market_rejected_listing_recommends_underbid(client, session, seeded):
    """Market-rejected shape: CMA far above list, exposure 4x the area median, offer
    date long passed — the ceiling must sit at list, not at 1.05x the CMA."""
    from hb.db.models import CmaRun, ListingGroup, MarketMetric

    session.add(MarketMetric(geo_type="city", geo_id="Sunnyvale", period_start="2026-06-01",
                             period="monthly", metric="median_dom", value=10.0,
                             source="redfin"))
    group = ListingGroup(property_id=seeded.property_id, cumulative_dom=41,
                         episode_count=1, first_list_date=seeded.list_date)
    session.add(group)
    session.flush()
    seeded.listing_group_id = group.id
    seeded.offer_due_at = (TODAY - timedelta(days=30)).isoformat()
    session.add(CmaRun(property_id=seeded.property_id, estimate=2_600_000,
                       low=2_500_000, high=2_750_000, confidence="medium"))
    # deep pockets: without the posture layer the gap cap would be 1.05x the CMA
    profile = session.get(BuyerProfile, "default")
    profile.cash_available = 3_000_000
    profile.down_payment = 1_500_000
    session.commit()

    body = client.post("/api/offer/solve", json={"listing_id": seeded.id}).json()
    assert body["recommendation"] == "underbid"
    assert body["verdict_template"] == "underbid_lingering"
    assert body["posture"]["p_below_list"] >= 0.60
    assert body["posture"]["exposure"]["offer_passed"] is True
    assert body["ceiling"] <= seeded.list_price
    assert body["escalation_cap"] == body["ceiling"]
    assert body["e_basis"] == "adjusted_blend"
    assert body["predicted"]["rejection_weight"] == 1.0
    assert body["predicted"]["point"] <= seeded.list_price  # pulled to list
    assert body["posture"]["posture"] == "overpriced"
    assert body["opening_range"]["high"] < seeded.list_price
    # cash max reflects E = adjusted value (~list), far below 1.05 x CMA on top of cash
    assert body["max_defensible_bid"] < 1.05 * 2_600_000


def test_solve_profile_only(client, seeded):
    body = client.post("/api/offer/solve", json={"city": "Sunnyvale"}).json()
    assert body["predicted"] is None
    assert body["cma_estimate"] is None
    assert body["verdict_template"] == "profile_only"
    assert body["e_basis"] == "none"
    assert body["max_defensible_bid"] > 0
    assert body["verdict"].startswith("You can afford up to")
    assert set(body["limits"]) == {"cash", "down_payment", "payment"}
