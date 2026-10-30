import pandas as pd
import pytest
from sqlalchemy import func, select

from hb.db.models import Listing, ListingEvent, Property, Sale
from hb.pipelines import backfill_sales


def _sold_row(**over):
    r = {
        "property_id": "P900", "listing_id": "L900", "mls_id": "M900",
        "full_street_line": "42 Old Sold St", "street": "42 Old Sold St",
        "unit": None, "city": "Sunnyvale", "state": "CA", "zip_code": "94087",
        "latitude": 37.35, "longitude": -122.03, "beds": 3, "full_baths": 2,
        "half_baths": 0, "sqft": 1600, "lot_sqft": 5000, "year_built": 1975,
        "list_price": 2_000_000, "sold_price": 2_200_000,
        "last_sold_date": "2024-05-10 00:00:00", "days_on_mls": 12,
    }
    r.update(over)
    return r


@pytest.fixture
def env(session, monkeypatch, set_geography):
    set_geography(cities=["Sunnyvale"])
    monkeypatch.setattr(backfill_sales.time, "sleep", lambda *_: None)
    rows: list[dict] = []
    monkeypatch.setattr(backfill_sales, "fetch_sold",
                        lambda city, df, dt: pd.DataFrame(rows))
    return rows


def test_backfill_writes_comp_only(engine, session, env):
    env.append(_sold_row())
    assert backfill_sales.run(engine) == "ok"

    sale = session.execute(select(Sale)).scalar_one()
    assert sale.sale_date == "2024-05-10" and sale.sale_price == 2_200_000
    assert sale.original_list_price == 2_000_000
    assert sale.sp_lp == pytest.approx(2_200_000 / 2_000_000, abs=1e-4)
    assert sale.had_price_cut is False
    # comp-only: no listings, no events, no alerts spam
    assert session.execute(select(func.count()).select_from(Listing)).scalar_one() == 0
    assert session.execute(select(func.count()).select_from(ListingEvent)).scalar_one() == 0
    # property was resolved
    assert session.execute(select(func.count()).select_from(Property)).scalar_one() == 1


def test_backfill_idempotent(engine, session, env):
    env.append(_sold_row())
    backfill_sales.run(engine)
    backfill_sales.run(engine)  # same window, same data
    assert session.execute(select(func.count()).select_from(Sale)).scalar_one() == 1


def test_backfill_never_clobbers_scan_recorded_sale(engine, session, env):
    """Gap-filler contract: a sale the daily scan recorded (with real price-cut
    history) must survive a backfill over the same window untouched."""
    from hb.pipelines.resolve import resolve

    property_id, _ = resolve(session, {
        "street": "42 Old Sold St", "city": "Sunnyvale", "state": "CA",
        "zip": "94087", "lat": 37.35, "lon": -122.03, "beds": 3, "baths": 2.0,
        "sqft": 1600, "property_type": "single_family",
    })
    session.add(Sale(
        property_id=property_id, sale_date="2024-05-10", sale_price=2_200_000,
        list_price_at_sale=2_000_000, original_list_price=2_290_000,  # pre-cut
        sp_lp=round(2_200_000 / 2_290_000, 4), had_price_cut=True,
        source="realtor_sold_scan",
    ))
    session.commit()

    env.append(_sold_row())  # same home/date; source only shows final list $2.0M
    assert backfill_sales.run(engine) == "ok"

    sale = session.execute(select(Sale)).scalar_one()
    assert sale.had_price_cut is True                      # not reset to False
    assert sale.original_list_price == 2_290_000           # pre-cut value kept
    assert sale.sp_lp == pytest.approx(2_200_000 / 2_290_000, abs=1e-4)


def test_backfill_skips_incomplete_rows(engine, session, env):
    env.append(_sold_row(sold_price=None, last_sold_price=None))  # no price -> skip
    backfill_sales.run(engine)
    assert session.execute(select(func.count()).select_from(Sale)).scalar_one() == 0
