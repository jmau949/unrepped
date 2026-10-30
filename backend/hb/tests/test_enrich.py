from datetime import date

import pytest
from sqlalchemy import func, select

from hb.db.models import AppSetting, AvmSnapshot, Listing, Property, Sale, TrackedListing
from hb.pipelines import enrich

TODAY = date.today().isoformat()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_rentcast_active_comparables_never_become_sales(monkeypatch):
    """Only verifiably closed comparables (removedDate) may enter `sales` —
    active listings at asking price were fabricated as comps."""
    payload = {
        "price": 2_500_000, "priceRangeLow": 2_400_000, "priceRangeHigh": 2_600_000,
        "comparables": [
            {"price": 2_600_000, "listedDate": "2026-07-01T00:00:00Z",
             "lastSeenDate": "2026-07-10T00:00:00Z", "status": "Active",
             "formattedAddress": "1 Active St", "zipCode": "94087"},
            {"price": 2_450_000, "removedDate": "2026-06-20T00:00:00Z",
             "status": "Inactive", "formattedAddress": "2 Closed Ave", "zipCode": "94087"},
            {"price": 2_500_000, "removedDate": "2026-06-25T00:00:00Z",
             "formattedAddress": "3 Sold Ct", "zipCode": "94087"},
            {"price": 2_550_000, "listedDate": "2026-06-01T00:00:00Z",
             "formattedAddress": "4 No Close Date Rd", "zipCode": "94087"},
        ],
    }
    monkeypatch.setattr(enrich.settings, "rentcast_api_key", "k")
    monkeypatch.setattr(enrich.httpx, "get", lambda *a, **kw: _FakeResp(payload))

    out = enrich.fetch_rentcast_avm("x")
    assert [c["address"] for c in out["comps"]] == ["2 Closed Ave", "3 Sold Ct"]
    assert all(c["sale_date"] in ("2026-06-20", "2026-06-25") for c in out["comps"])


def test_zestimate_percent_bounds_converted_to_dollars(monkeypatch):
    payload = {"zestimate": 2_300_000, "zestimateLowPercent": "5",
               "zestimateHighPercent": "4"}
    monkeypatch.setattr(enrich.settings, "rapidapi_key", "k")
    monkeypatch.setattr(enrich.httpx, "get", lambda *a, **kw: _FakeResp(payload))

    out = enrich.fetch_zestimate("x")
    assert out == {"value": 2_300_000, "low": 2_185_000, "high": 2_392_000}


def test_zestimate_missing_percents_yield_null_bounds(monkeypatch):
    monkeypatch.setattr(enrich.settings, "rapidapi_key", "k")
    monkeypatch.setattr(enrich.httpx, "get",
                        lambda *a, **kw: _FakeResp({"zestimate": 2_300_000}))
    out = enrich.fetch_zestimate("x")
    assert out == {"value": 2_300_000, "low": None, "high": None}


def test_realtor_estimate_picks_best_value_and_parses(monkeypatch):
    """fetch_realtor_estimate picks the isBestHomeValue estimate, converts the
    string baths_consolidated to float, and dedups photo hrefs (live shape:
    CoreLogic best + Quantarium)."""
    payload = {"data": {"home": {
        "description": {"beds": 4, "baths_consolidated": "3.5", "sqft": 2480,
                        "lot_sqft": 5000, "year_built": 2013},
        "primary_photo": {"href": "https://img/1.jpg"},
        "photos": [{"href": "https://img/1.jpg"}, {"href": "https://img/2.jpg"}],
        "estimates": {"currentValues": [
            {"source": {"type": "corelogic", "name": "Cotality"}, "estimate": 3_700_000,
             "estimateHigh": 4_200_000, "estimateLow": 3_200_000, "isBestHomeValue": True},
            {"source": {"type": "quantarium", "name": "Quantarium"}, "estimate": 3_100_000,
             "estimateHigh": 3_400_000, "estimateLow": 2_700_000, "isBestHomeValue": False},
        ]},
    }}}
    monkeypatch.setattr(enrich.realtor_gql, "post", lambda *a, **kw: payload)

    out = enrich.fetch_realtor_estimate("x", mpr_id="123")
    assert out["estimate"] == 3_700_000  # best-value (corelogic), not quantarium
    assert out["low"] == 3_200_000 and out["high"] == 4_200_000
    assert out["property"] == {"beds": 4, "baths": 3.5, "sqft": 2480,
                               "lot_sqft": 5000, "year_built": 2013}
    assert out["photo_urls"] == ["https://img/1.jpg", "https://img/2.jpg"]  # deduped


def test_realtor_estimate_none_when_no_match(monkeypatch):
    monkeypatch.setattr(enrich.realtor_gql, "resolve_mpr_id", lambda a: None)
    assert enrich.fetch_realtor_estimate("nowhere") is None


def test_run_path_fires_new_comp_sold(engine, session, monkeypatch, tmp_path):
    """RentCast comps created via the CLI/API enrich path (not
    the scan) must still drive the new_comp_sold rule, exactly once."""
    from hb import config
    from hb.db.models import Alert
    from hb.pipelines.resolve import resolve

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "rentcast_api_key", "test-key")
    monkeypatch.setattr(config.settings, "zillow_wrapper_enabled", False)
    monkeypatch.setattr(enrich.time, "sleep", lambda *_: None)
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: None)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: RENTCAST)

    # tracked home near the RENTCAST comp (55 Comp Ln @ 37.351,-122.031)
    pid, _ = resolve(session, {"street": "10 Subject St", "city": "Sunnyvale",
                               "state": "CA", "zip": "94087", "lat": 37.3512,
                               "lon": -122.0312, "beds": 3, "baths": 2.0, "sqft": 1600,
                               "property_type": "single_family"})
    lst = Listing(property_id=pid, source="realtor", source_listing_id="T1",
                  status="active", list_price=2_300_000, original_list_price=2_300_000,
                  list_date="2026-07-01")
    session.add(lst)
    session.flush()
    session.add(TrackedListing(listing_id=lst.id))
    session.add(AppSetting(key="alert_rules", value={"new_comp_sold": {"enabled": True}}))
    session.commit()

    assert enrich.run(engine, property_id=pid) == "ok"
    alerts = session.execute(select(Alert).where(Alert.type == "new_comp_sold")).scalars().all()
    assert len(alerts) == 1

    assert enrich.run(engine, property_id=pid) == "ok"  # re-run: dedup holds
    alerts = session.execute(select(Alert).where(Alert.type == "new_comp_sold")).scalars().all()
    assert len(alerts) == 1


@pytest.fixture
def env(session, monkeypatch, tmp_path):
    from hb import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "rentcast_api_key", "test-key")
    monkeypatch.setattr(config.settings, "zillow_wrapper_enabled", False)
    monkeypatch.setattr(enrich.time, "sleep", lambda *_: None)
    return session


def _property(session, **over):
    fields = dict(address_norm="10 SUBJECT ST", zip="94087", city="Sunnyvale",
                  street="10 Subject St", lat=37.35, lon=-122.03, beds=None, baths=None,
                  sqft=None, property_type="single_family")
    fields.update(over)
    p = Property(**fields)
    session.add(p)
    session.flush()
    return p


REALTOR = {"estimate": 2_250_000, "low": 2_100_000, "high": 2_400_000,
           "photo_urls": [], "property": {"beds": 3, "baths": 2.0, "sqft": 1600}}
RENTCAST = {"value": 2_300_000, "low": 2_150_000, "high": 2_450_000,
            "comps": [{"sale_date": "2026-06-15", "sale_price": 2_280_000,
                       "address": "55 Comp Ln", "city": "Sunnyvale", "state": "CA",
                       "zip": "94087", "lat": 37.351, "lon": -122.031, "beds": 3,
                       "baths": 2.0, "sqft": 1580}]}


def test_realtor_fills_nulls_and_snapshots(env, monkeypatch):
    prop = _property(env)
    env.commit()
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: REALTOR)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: RENTCAST)

    errors: list[str] = []
    enrich.enrich_one(env, prop, errors)
    env.commit()

    assert prop.beds == 3 and prop.sqft == 1600  # NULL-filled
    sources = {a.source for a in env.execute(select(AvmSnapshot)).scalars().all()}
    assert {"realtor_estimate", "rentcast"} <= sources


def test_d13_one_snapshot_per_source_per_day(env, monkeypatch):
    prop = _property(env)
    env.commit()
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: REALTOR)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: RENTCAST)

    for _ in range(2):  # same day, twice
        errors: list[str] = []
        enrich.enrich_one(env, prop, errors)
        env.commit()

    for source in ("realtor_estimate", "rentcast"):
        n = env.execute(
            select(func.count()).select_from(AvmSnapshot)
            .where(AvmSnapshot.property_id == prop.id, AvmSnapshot.source == source)
        ).scalar_one()
        assert n == 1


def test_rentcast_comps_land_as_sales(env, monkeypatch):
    prop = _property(env)
    env.commit()
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: None)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: RENTCAST)

    errors: list[str] = []
    enrich.enrich_one(env, prop, errors)
    env.commit()

    sale = env.execute(select(Sale).where(Sale.source == "rentcast")).scalar_one()
    assert sale.sale_date == "2026-06-15" and sale.sale_price == 2_280_000


def test_budget_guard_refuses_without_calling(env, monkeypatch):
    from hb import config

    prop = _property(env)
    env.add(AppSetting(key="rentcast_budget",
                       value={"month": date.today().strftime("%Y-%m"),
                              "calls": config.settings.rentcast_monthly_limit}))
    env.commit()

    calls = []
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: None)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: calls.append(a) or RENTCAST)

    errors: list[str] = []
    enrich.enrich_one(env, prop, errors)
    assert calls == []  # exhausted budget -> no call
    assert any("budget exhausted" in e for e in errors)
    assert enrich.rentcast_remaining(env) == 0


def test_realtor_failure_records_miss_and_continues(env, monkeypatch):
    prop = _property(env)
    env.commit()

    def boom(_, mpr_id=None):
        raise RuntimeError("realtor down")

    monkeypatch.setattr(enrich, "fetch_realtor_estimate", boom)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: RENTCAST)

    errors: list[str] = []
    enrich.enrich_one(env, prop, errors)
    env.commit()
    assert any("realtor" in e for e in errors)
    # rentcast still ran despite redfin failing
    assert env.execute(
        select(func.count()).select_from(AvmSnapshot).where(AvmSnapshot.source == "rentcast")
    ).scalar_one() == 1


def test_gallery_skips_existing_files(env, monkeypatch):
    from hb import config

    prop = _property(env)
    lst = Listing(property_id=prop.id, source="realtor", source_listing_id="L1",
                  status="active", list_price=2_000_000)
    env.add(lst)
    env.commit()

    fetched = []
    monkeypatch.setattr(enrich, "fetch_photo", lambda url: fetched.append(url) or b"jpg")
    rf = {**REALTOR, "photo_urls": ["http://x/a.jpg", "http://x/b.jpg"]}
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: rf)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: None)

    enrich.enrich_one(env, prop, [])
    env.commit()
    assert len(fetched) == 2
    assert len(lst.photo_paths) == 2
    photos = list((config.settings.photos_dir).rglob("*.jpg"))
    assert len(photos) == 2

    enrich.enrich_one(env, prop, [])  # second run: files exist -> no re-fetch
    assert len(fetched) == 2


def test_run_all_tracked(env, monkeypatch):
    prop = _property(env)
    lst = Listing(property_id=prop.id, source="realtor", source_listing_id="L1",
                  status="active", list_price=2_000_000)
    env.add(lst)
    env.flush()
    env.add(TrackedListing(listing_id=lst.id, stage="saved"))
    env.commit()
    monkeypatch.setattr(enrich, "fetch_realtor_estimate", lambda a, mpr_id=None: REALTOR)
    monkeypatch.setattr(enrich, "fetch_rentcast_avm", lambda a: None)

    n = enrich.enrich_tracked(env)
    assert n == 1
    assert env.execute(
        select(func.count()).select_from(AvmSnapshot).where(AvmSnapshot.source == "realtor_estimate")
    ).scalar_one() == 1
