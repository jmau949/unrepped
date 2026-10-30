import pytest
from fastapi.testclient import TestClient

from hb.db.models import MarketMetric, RateSnapshot


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.market as market_module
    import hb.api.ops as ops_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (ops_module, market_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


def _seed(session):
    for period_start, value in [("2026-03-01", 3000000.0), ("2026-06-10", 3055000.0)]:
        session.add(
            MarketMetric(
                geo_type="zip", geo_id="94087", period_start=period_start,
                period="monthly", metric="median_sale_price", value=value, source="redfin",
            )
        )
    session.add(
        MarketMetric(
            geo_type="zip", geo_id="94087", period_start="2026-06-10",
            period="monthly", metric="avg_sp_lp", value=1.111, source="redfin",
        )
    )
    session.add_all([
        RateSnapshot(date="2026-07-02", series="MORTGAGE30US", value=6.72),
        RateSnapshot(date="2026-07-09", series="MORTGAGE30US", value=6.68),
        RateSnapshot(date="2026-07-09", series="MORTGAGE15US", value=5.91),
    ])
    session.commit()


def test_summary_shape_band_and_delta(client, session):
    _seed(session)
    body = client.get("/api/market/summary").json()

    assert body["target_band"] == {"min": 2_000_000, "max": 3_000_000}
    assert len(body["zips"]) == 1  # only geos with data
    z = body["zips"][0]
    assert z["geo_id"] == "94087"
    assert z["city"] == "Sunnyvale"
    assert z["metrics"]["median_sale_price"] == 3055000.0
    assert z["metrics"]["avg_sp_lp"] == 1.111
    # delta: 3.055M vs 3.0M ~93 days earlier
    assert z["deltas_90d"]["median_sale_price"] == pytest.approx(0.0183, abs=1e-4)
    assert z["deltas_90d"]["avg_sp_lp"] is None  # no 90-day-old point
    assert z["metrics"]["median_dom"] is None  # metric absent -> null


def test_series_endpoint(client, session):
    _seed(session)
    pts = client.get(
        "/api/market/series",
        params={"geo_type": "zip", "geo_id": "94087", "metric": "median_sale_price"},
    ).json()
    assert [p["period_start"] for p in pts] == ["2026-03-01", "2026-06-10"]

    pts = client.get(
        "/api/market/series",
        params={"geo_type": "zip", "geo_id": "94087", "metric": "median_sale_price",
                "since": "2026-05-01"},
    ).json()
    assert len(pts) == 1


def test_rates_endpoint(client, session):
    _seed(session)
    pts = client.get("/api/market/rates").json()
    assert [p["value"] for p in pts] == [6.72, 6.68]

    pts = client.get("/api/market/rates", params={"series": "MORTGAGE15US"}).json()
    assert len(pts) == 1


def _seed_supply(session):
    session.add_all([
        MarketMetric(geo_type="zip", geo_id="94087", period_start=p, period="3m",
                     metric="months_supply", value=v, source="redfin")
        for p, v in [("2026-03-01", 1.0), ("2026-04-01", 0.8), ("2026-06-01", 0.5)]
    ])
    session.add_all([
        MarketMetric(geo_type="zip", geo_id="94087", period_start="2026-09-26", period=period,
                     metric="months_supply_live", value=value, source="derived")
        for period, value in [("3m", 0.3), ("6m", 0.6), ("12m", 1.2)]
    ])
    session.add(MarketMetric(  # yesterday's 3m point must lose to today's
        geo_type="zip", geo_id="94087", period_start="2026-09-25", period="3m",
        metric="months_supply_live", value=0.9, source="derived",
    ))
    session.commit()


def test_supply_endpoint_selects_the_live_window(client, session):
    _seed_supply(session)

    body = client.get("/api/market/supply").json()
    assert body["as_of"]["live_window_months"] == 3
    assert body["as_of"]["live"] == "2026-09-26"
    # the Redfin window is labelled by its start; the end is derived
    assert body["as_of"]["redfin_window_start"] == "2026-06-01"
    assert body["as_of"]["redfin_window_end"] == "2026-08-31"
    z = body["zips"][0]
    assert z["geo_id"] == "94087" and z["city"] == "Sunnyvale"
    assert z["months_supply"] == 0.5 and z["months_supply_basis"] == "redfin"
    assert z["months_supply_live"] == 0.3 and z["months_supply_live_basis"] == "derived"
    assert z["delta_90d"] == pytest.approx(-0.5)  # 0.5 vs the 1.0 of 2026-03-01
    assert z["band"] == "very_tight"

    six = client.get("/api/market/supply", params={"window": 6}).json()
    assert six["as_of"]["live_window_months"] == 6
    assert six["zips"][0]["months_supply_live"] == 0.6
    # a window with no rows yet leaves the live value empty, not another window's
    nine = client.get("/api/market/supply", params={"window": 9}).json()
    assert nine["zips"][0]["months_supply_live"] is None
    assert nine["zips"][0]["months_supply"] == 0.5

    assert client.get("/api/market/supply", params={"window": 5}).status_code == 422


def test_summary_uses_the_default_live_window(client, session):
    _seed_supply(session)
    z = client.get("/api/market/summary").json()["zips"][0]
    assert z["metrics"]["months_supply_live"] == 0.3
    assert z["metrics"]["months_supply"] == 0.5
    assert "pct_price_drops" not in z["metrics"]
