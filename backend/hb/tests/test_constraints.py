import pytest
from sqlalchemy.exc import IntegrityError

from hb.db.models import (
    Alert,
    AvmSnapshot,
    Listing,
    MarketMetric,
    Property,
    Sale,
)


def _property(session, **over):
    p = Property(address_norm="1 ELM ST", zip="94301", **over)
    session.add(p)
    session.flush()
    return p


def _expect_unique_violation(session, row_factory):
    session.add(row_factory())
    session.flush()
    session.add(row_factory())
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_properties_unique_address(session):
    _expect_unique_violation(
        session, lambda: Property(address_norm="9 OAK AVE", zip="94025", unit="")
    )


def test_listings_unique_source_id(session):
    p = _property(session)
    _expect_unique_violation(
        session,
        lambda: Listing(
            property_id=p.id, source="realtor", source_listing_id="R1", status="active"
        ),
    )


def test_sales_unique_property_date(session):
    p = _property(session)
    _expect_unique_violation(
        session,
        lambda: Sale(property_id=p.id, sale_date="2026-06-01", sale_price=2_000_000),
    )


def test_market_metrics_unique_key(session):
    _expect_unique_violation(
        session,
        lambda: MarketMetric(
            geo_type="zip",
            geo_id="94087",
            period_start="2026-06-01",
            period="weekly",
            metric="median_ppsf",
            value=1400.0,
            source="redfin",
        ),
    )


def test_avm_snapshots_unique_key(session):
    p = _property(session)
    _expect_unique_violation(
        session,
        lambda: AvmSnapshot(
            property_id=p.id, source="rentcast", value=2_100_000, as_of="2026-07-14"
        ),
    )


def test_alerts_dedup_key_unique(session):
    _expect_unique_violation(
        session, lambda: Alert(type="price_cut", dedup_key="price_cut:x:1")
    )
