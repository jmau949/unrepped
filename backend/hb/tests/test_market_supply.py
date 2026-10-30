from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from hb.db.models import Listing, MarketMetric, Property, Sale
from hb.engine.supply import LIVE_WINDOWS
from hb.pipelines import market_supply

# --- compute_live_supply -----------------------------------------------------


def test_live_supply_is_window_months_times_active_over_sales():
    rows = market_supply.compute_live_supply(
        {("zip", "94402"): 8}, {("zip", "94402"): 72}, "2026-08-01", 3
    )
    assert rows[0]["value"] == pytest.approx(0.333, abs=1e-3)
    assert rows[0]["period"] == "3m"
    assert rows[0]["period_start"] == "2026-08-01"
    assert rows[0]["metric"] == "months_supply_live"
    assert rows[0]["source"] == "derived"


def test_live_supply_window_scales_the_rate_not_the_stock():
    """Same 8 active homes; 144 sales over 6 months is the same monthly pace as
    72 over 3, so months of supply is unchanged and only the label moves."""
    six = market_supply.compute_live_supply(
        {("zip", "94402"): 8}, {("zip", "94402"): 144}, "2026-08-01", 6
    )
    assert six[0]["value"] == pytest.approx(0.333, abs=1e-3)
    assert six[0]["period"] == "6m"


def test_live_thin_zip_borrows_its_city():
    rows = market_supply.compute_live_supply(
        {("zip", "94063"): 7, ("city", "Redwood City"): 90},
        {("zip", "94063"): 4, ("city", "Redwood City"): 300},
        "2026-08-01",
        3,
    )
    by_geo = {(r["geo_type"], r["geo_id"]): r for r in rows}
    assert by_geo[("city", "Redwood City")]["value"] == pytest.approx(0.9)
    assert by_geo[("zip", "94063")]["source"] == "derived_city"
    assert by_geo[("zip", "94063")]["value"] == pytest.approx(0.9)


def test_live_zero_active_is_a_real_zero_not_a_gap():
    rows = market_supply.compute_live_supply({}, {("zip", "94402"): 72}, "2026-08-01", 3)
    assert rows[0]["value"] == pytest.approx(0.0)


def test_live_thin_city_emits_nothing():
    assert market_supply.compute_live_supply(
        {("zip", "94402"): 3, ("city", "San Mateo"): 3},
        {("zip", "94402"): 2, ("city", "San Mateo"): 2},
        "2026-08-01",
        3,
    ) == []


# --- run() -------------------------------------------------------------------


def _seed_listings(session, zip_code, active, sold, sale_date):
    for i in range(max(active, sold)):
        prop = Property(address_norm=f"{i} test st {zip_code} {sale_date}", zip=zip_code,
                        city="San Mateo")
        session.add(prop)
        session.flush()
        if i < active:
            session.add(Listing(property_id=prop.id, source="realtor",
                                source_listing_id=f"{zip_code}-{i}-{sale_date}",
                                status="active"))
        if i < sold:
            session.add(Sale(property_id=prop.id, sale_date=sale_date, sale_price=2_000_000))


def test_run_writes_every_window_and_is_idempotent(engine, session):
    today = date.today()
    # 72 sales 10 days back land in every window; 24 more at ~5 months back
    # land only in the 6/9/12-month windows
    _seed_listings(session, "94402", active=8, sold=72,
                   sale_date=(today - timedelta(days=10)).isoformat())
    _seed_listings(session, "94402", active=0, sold=24,
                   sale_date=(today - timedelta(days=150)).isoformat())
    session.commit()

    assert market_supply.run(engine) == "ok"
    assert market_supply.run(engine) == "ok"  # idempotent re-run

    rows = session.execute(
        select(MarketMetric).where(MarketMetric.metric == "months_supply_live")
    ).scalars().all()
    # one zip + one city row per window; no duplicates from run 2
    assert len(rows) == 2 * len(LIVE_WINDOWS)
    by_key = {(r.geo_type, r.period): r for r in rows}
    assert {p for _, p in by_key} == {"3m", "6m", "9m", "12m"}
    assert all(r.period_start == today.isoformat() for r in rows)

    # 3m: 3 * 8 / 72 ; 6m: 6 * 8 / 96 — the older sales stretch the denominator
    assert by_key[("zip", "3m")].value == pytest.approx(0.333, abs=1e-3)
    assert by_key[("zip", "6m")].value == pytest.approx(0.5, abs=1e-3)
    assert by_key[("zip", "12m")].value == pytest.approx(1.0, abs=1e-3)
    # the ZIP rolls up into its city via settings.geo.zip_to_city, not properties.city
    assert by_key[("city", "3m")].geo_id == "San Mateo"


def test_run_replaces_a_stale_row_when_the_basis_flips(engine, session):
    """source is part of the unique key, so an upsert alone would leave a dup."""
    today = date.today().isoformat()
    session.add(MarketMetric(
        geo_type="zip", geo_id="94402", period_start=today, period="3m",
        metric="months_supply_live", value=9.9, source="derived_city",
    ))
    _seed_listings(session, "94402", active=8, sold=72,
                   sale_date=(date.today() - timedelta(days=10)).isoformat())
    session.commit()

    assert market_supply.run(engine) == "ok"

    rows = session.execute(
        select(MarketMetric).where(MarketMetric.metric == "months_supply_live",
                                   MarketMetric.geo_type == "zip",
                                   MarketMetric.period == "3m")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "derived"
    assert rows[0].value == pytest.approx(0.333, abs=1e-3)


def test_run_keeps_history_and_never_touches_published_redfin_rows(engine, session):
    session.add_all([
        MarketMetric(geo_type="zip", geo_id="94402", period_start="2026-06-01", period="3m",
                     metric="months_supply", value=0.5, source="redfin"),
        MarketMetric(geo_type="zip", geo_id="94402", period_start="2026-08-01", period="3m",
                     metric="months_supply_live", value=0.4, source="derived"),
    ])
    _seed_listings(session, "94402", active=8, sold=72,
                   sale_date=(date.today() - timedelta(days=10)).isoformat())
    session.commit()

    assert market_supply.run(engine) == "ok"

    kept = session.execute(
        select(MarketMetric.metric, MarketMetric.period_start, MarketMetric.value).where(
            MarketMetric.period_start.in_(("2026-06-01", "2026-08-01")))
    ).all()
    assert sorted(kept) == [
        ("months_supply", "2026-06-01", 0.5),
        ("months_supply_live", "2026-08-01", 0.4),
    ]


# --- history replay / backfill ----------------------------------------------


def test_status_at_replays_the_event_log():
    events = [("2026-08-10T12:00:00+00:00", "active"), ("2026-09-01T12:00:00+00:00", "pending")]
    assert market_supply._status_at("sold", events, "2026-08-05") == "active"
    assert market_supply._status_at("sold", events, "2026-08-20") == "pending"
    assert market_supply._status_at("sold", events, "2026-09-10") == "sold"
    # an event observed on the cutoff morning's scan has not happened yet
    assert market_supply._status_at("sold", events, "2026-08-10") == "active"
    assert market_supply._status_at("active", [], "2026-08-05") == "active"


def test_run_backfills_every_morning_since_the_first_scan(engine, session):
    """First scan six days ago saw 8 active homes; one went pending two days
    ago. Every window gets a row for each morning after the first scan, with
    the active count replayed from the event log."""
    from hb.db.models import ListingEvent

    today = date.today()
    first_scan = (today - timedelta(days=6)).isoformat() + "T12:00:00+00:00"
    _seed_listings(session, "94402", active=8, sold=72,
                   sale_date=(today - timedelta(days=40)).isoformat())
    session.flush()
    listings = session.execute(select(Listing)).scalars().all()
    for listing in listings:
        listing.first_seen = first_scan
        session.add(ListingEvent(listing_id=listing.id, event_type="new", old_value=None,
                                 new_value="2000000", observed_at=first_scan))
    pending = listings[0]
    pending.status = "pending"
    session.add(ListingEvent(
        listing_id=pending.id, event_type="pending", old_value="active", new_value="pending",
        observed_at=(today - timedelta(days=2)).isoformat() + "T12:00:00+00:00",
    ))
    session.commit()

    assert market_supply.run(engine) == "ok"

    rows = session.execute(
        select(MarketMetric).where(MarketMetric.metric == "months_supply_live",
                                   MarketMetric.geo_type == "zip")
    ).scalars().all()
    by_key = {(r.period_start, r.period): r.value for r in rows}
    mornings = [(today - timedelta(days=n)).isoformat() for n in range(5, 0, -1)]
    assert {d for d, _ in by_key} == set(mornings) | {today.isoformat()}
    assert all((d, p) in by_key for d in mornings for p in ("3m", "6m", "9m", "12m"))
    # the pending event was observed on the d-2 scan: that morning still had 8
    # active, the next morning 7, and so does today's live count
    assert by_key[((today - timedelta(days=3)).isoformat(), "3m")] == pytest.approx(3 * 8 / 72, abs=1e-3)
    assert by_key[((today - timedelta(days=2)).isoformat(), "3m")] == pytest.approx(3 * 8 / 72, abs=1e-3)
    assert by_key[((today - timedelta(days=1)).isoformat(), "3m")] == pytest.approx(3 * 7 / 72, abs=1e-3)
    assert by_key[((today - timedelta(days=1)).isoformat(), "12m")] == pytest.approx(12 * 7 / 72, abs=1e-3)
    assert by_key[(today.isoformat(), "3m")] == pytest.approx(3 * 7 / 72, abs=1e-3)

    # a second run finds nothing missing and writes nothing new
    total = session.execute(select(func.count()).select_from(MarketMetric)).scalar_one()
    assert market_supply.run(engine) == "ok"
    assert session.execute(select(func.count()).select_from(MarketMetric)).scalar_one() == total


def test_backfill_leaves_recorded_mornings_alone(engine, session):
    """A morning that already has a row for a window keeps it — the recorded
    value is what the app saw that day, not a replay."""
    from hb.db.models import ListingEvent

    today = date.today()
    first_scan = (today - timedelta(days=3)).isoformat() + "T12:00:00+00:00"
    _seed_listings(session, "94402", active=8, sold=72,
                   sale_date=(today - timedelta(days=40)).isoformat())
    session.flush()
    listing = session.execute(select(Listing)).scalars().first()
    listing.first_seen = first_scan
    session.add(ListingEvent(listing_id=listing.id, event_type="new", old_value=None,
                             new_value="2000000", observed_at=first_scan))
    recorded = (today - timedelta(days=1)).isoformat()
    session.add(MarketMetric(geo_type="zip", geo_id="94402", period_start=recorded, period="3m",
                             metric="months_supply_live", value=0.777, source="derived"))
    session.commit()

    assert market_supply.run(engine) == "ok"
    rows = session.execute(
        select(MarketMetric.period, MarketMetric.value).where(
            MarketMetric.metric == "months_supply_live", MarketMetric.geo_type == "zip",
            MarketMetric.period_start == recorded)
    ).all()
    by_period = dict(rows)
    assert by_period["3m"] == 0.777
    assert set(by_period) == {"3m", "6m", "9m", "12m"}
