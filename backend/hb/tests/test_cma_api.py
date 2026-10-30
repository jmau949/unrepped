from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from hb.db.models import MarketMetric, PriceIndex, Property, Sale

TODAY = date.today()


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.cma as cma_module
    import hb.api.listings as listings_module
    import hb.api.overbid as overbid_module
    import hb.api.tracker as tracker_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (cma_module, overbid_module, listings_module, tracker_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))
    from hb.main import app
    return TestClient(app)


def _month(n):
    y, m = TODAY.year, TODAY.month - n
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


@pytest.fixture
def seeded(session):
    for n in range(0, 8):
        session.add(PriceIndex(geo_type="zip", geo_id="94087", month=_month(n),
                               index_value=1.0, source="blend"))
    for n in range(0, 3):
        session.add(MarketMetric(geo_type="zip", geo_id="94087", period_start=_month(n) + "-01",
                                 period="monthly", metric="median_ppsf", value=1400, source="redfin"))
    subj = Property(address_norm="100 SUBJECT ST", zip="94087", city="Sunnyvale",
                    lat=37.350, lon=-122.030, beds=3, baths=2.0, sqft=1600,
                    lot_sqft=5000, year_built=1975, condition_tag="dated",
                    property_type="single_family")
    session.add(subj)
    session.flush()
    for i, (sqft, price) in enumerate(
        [(1500, 2_150_000), (1700, 2_300_000), (1600, 2_200_000),
         (1550, 2_180_000), (1650, 2_250_000), (1620, 2_210_000)]
    ):
        p = Property(address_norm=f"{i} COMP AVE", zip="94087", city="Sunnyvale",
                     lat=37.350 + 0.001 * (i + 1), lon=-122.030 + 0.001, beds=3, baths=2.0,
                     sqft=sqft, lot_sqft=5000, year_built=1975, condition_tag="dated",
                     property_type="single_family")
        session.add(p)
        session.flush()
        session.add(Sale(property_id=p.id, sale_date=(TODAY - timedelta(days=40 + i * 5)).isoformat(),
                         sale_price=price, original_list_price=price, sp_lp=1.0,
                         source="realtor_sold_scan"))
    session.commit()
    return subj


def test_toggle_off_all_comps_keeps_run_alive(client, seeded):
    """Zero-included recompute skipped persistence, so the
    workbench held id=null and every later PATCH 404'd. The empty run must
    persist with a real id and keep accepting toggles."""
    run = client.post("/api/cma/run", json={"property_id": seeded.id}).json()
    included = [c["sale_id"] for c in run["comps"] if c["included"]]

    for sale_id in included:  # toggle everything off
        run = client.patch(f"/api/cma/runs/{run['id']}/comps",
                           json={"sale_id": sale_id, "included": False}).json()
        assert run["id"], "every recompute must persist a run id"

    assert run["estimate"] is None
    assert run["confidence"] == "low"

    # the workbench is still usable: toggle one back on via the NEW run id
    revived = client.patch(f"/api/cma/runs/{run['id']}/comps",
                           json={"sale_id": included[0], "included": True})
    assert revived.status_code == 200
    assert revived.json()["estimate"] is not None


def test_run_shape(client, seeded):
    r = client.post("/api/cma/run", json={"property_id": seeded.id})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] and body["estimate"] and body["confidence"] in ("low", "medium", "high")
    assert len(body["comps"]) == 6
    comp = body["comps"][0]
    assert set(comp["adjustments"]) == {"time", "sqft", "baths", "lot", "condition"}
    assert "distance_mi" in comp and "similarity_score" in comp


def test_run_unknown_property_404(client, seeded):
    assert client.post("/api/cma/run", json={"property_id": "nope"}).status_code == 404


def test_comp_toggle_creates_new_run(client, seeded):
    run = client.post("/api/cma/run", json={"property_id": seeded.id}).json()
    sale_id = run["comps"][0]["sale_id"]
    r = client.patch(f"/api/cma/runs/{run['id']}/comps",
                     json={"sale_id": sale_id, "included": False})
    assert r.status_code == 200
    new = r.json()
    assert new["id"] != run["id"]  # history preserved
    toggled = next(c for c in new["comps"] if c["sale_id"] == sale_id)
    assert toggled["included"] is False


def test_adjustment_override_round_trips(client, seeded):
    run = client.post("/api/cma/run", json={"property_id": seeded.id}).json()
    sale_id = run["comps"][0]["sale_id"]
    r = client.patch(f"/api/cma/runs/{run['id']}/adjustments",
                     json={"sale_id": sale_id, "overrides": {"sqft": 50_000}})
    assert r.status_code == 200
    new = r.json()
    edited = next(c for c in new["comps"] if c["sale_id"] == sale_id)
    assert edited["adjustments"]["sqft"] == 50_000
    # override persists through a follow-up recompute
    r2 = client.patch(f"/api/cma/runs/{new['id']}/comps",
                      json={"sale_id": sale_id, "included": True})
    edited2 = next(c for c in r2.json()["comps"] if c["sale_id"] == sale_id)
    assert edited2["adjustments"]["sqft"] == 50_000


def test_run_history(client, seeded):
    client.post("/api/cma/run", json={"property_id": seeded.id})
    client.post("/api/cma/run", json={"property_id": seeded.id})
    hist = client.get("/api/cma/runs", params={"property_id": seeded.id}).json()
    assert len(hist) == 2
    assert all("estimate" in h and "n_comps" in h for h in hist)
