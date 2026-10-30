"""market-supply pipeline — docs/05-pipelines.md §3.5.

Derives `months_supply_live` (zip + city): a now-cast of months of supply from
this app's own scan — active listings today over the trailing closed-sale
rate — computed for every window in LIVE_WINDOWS (3/6/9/12 calendar months).
Redfin's published `months_supply` is a rolling 3-month window that closes
~1 month back; this one is current as of the last scan and lets the buyer pick
the window. ZIPs with too few closed sales in a window borrow their parent
city's figure.

Any morning since the first scan that a window has no row for is backfilled by
replaying the listing event log (which records every status transition with
its observation time), so a newly added window gets the full history at once
and a missed daily run heals itself.

Derived job (like build-index): reads listings / listing_events / sales, writes
market_metrics. No network.
"""

import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import Listing, ListingEvent, MarketMetric, Property, Sale
from hb.db.upsert import bulk_upsert
from hb.engine.supply import LIVE_WINDOWS, live_period, months_ago
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

METRIC = "months_supply_live"
KEY_COLS = ["geo_type", "geo_id", "period_start", "period", "metric", "source"]
DERIVED_SOURCES = ("derived", "derived_city")

# Closed sales per window, below which the ratio is noise rather than signal.
# Higher than build_index.THIN_SALES_THRESHOLD (5) on purpose: that one gates a
# median $/sqft, which is stable; this gates a ratio with sales in the
# denominator, which is not. Independent of window length — it is the minimum
# denominator, not a rate.
THIN_SALES_THRESHOLD = 10

# listing_events whose old_value/new_value are listing statuses.
STATUS_EVENTS = ("pending", "sold", "delisted", "back_on_market", "relisted", "status_change")


def compute_live_supply(
    active: dict[tuple[str, str], int],
    sold: dict[tuple[str, str], int],
    asof: str,
    window_months: int,
) -> list[dict]:
    """Now-cast rows for one window: `window_months * active / sold_in_window`.

    Maps keyed `(geo_type, geo_id)`; `sold` counts closed sales inside the
    trailing window. Thin ZIPs borrow their city (`source='derived_city'`).
    """
    keys = sorted(set(active) | set(sold))
    raw = {
        key: window_months * active.get(key, 0) / sold[key]
        for key in keys
        if sold.get(key, 0) >= THIN_SALES_THRESHOLD
    }

    rows: list[dict] = []
    for key in keys:
        geo_type, geo_id = key
        value, source = raw.get(key), "derived"
        if value is None:
            if geo_type != "zip":
                continue
            city = settings.geo.zip_to_city.get(geo_id)
            value = raw.get(("city", city)) if city else None
            if value is None:
                continue
            source = "derived_city"
        rows.append({
            "geo_type": geo_type,
            "geo_id": geo_id,
            "period_start": asof,
            "period": live_period(window_months),
            "metric": METRIC,
            "value": round(float(value), 3),
            "source": source,
        })
    return rows


def _rollup(rows) -> dict[tuple[str, str], int]:
    """[(zip, count)] -> {('zip', z): n, ('city', c): n}, dropping untargeted ZIPs.

    Cities roll up through the geography's ZIP→city map rather than
    properties.city so the keys stay immune to scraper city-name drift and
    match the fallback lookup.
    """
    out: dict[tuple[str, str], int] = {}
    for zip_code, count in rows:
        city = settings.geo.zip_to_city.get(zip_code)
        if city is None:
            continue
        out[("zip", zip_code)] = out.get(("zip", zip_code), 0) + count
        out[("city", city)] = out.get(("city", city), 0) + count
    return out


def _active_counts(session) -> dict[tuple[str, str], int]:
    rows = session.execute(
        select(Property.zip, func.count())
        .join(Listing, Listing.property_id == Property.id)
        .where(Listing.status == "active")
        .group_by(Property.zip)
    ).all()
    return _rollup(rows)


def _sold_counts(session, since: str, before: str | None = None) -> dict[tuple[str, str], int]:
    """Closed sales per geo with `since <= sale_date` (and `< before` when replaying a past morning)."""
    stmt = (
        select(Property.zip, func.count())
        .join(Sale, Sale.property_id == Property.id)
        .where(Sale.sale_date >= since)
        .group_by(Property.zip)
    )
    if before:
        stmt = stmt.where(Sale.sale_date < before)
    return _rollup(session.execute(stmt).all())


# --- history replay ----------------------------------------------------------


def _status_at(current: str, events: list[tuple[str, str | None]], cutoff: str) -> str:
    """A listing's status as of `cutoff` (exclusive), replaying its status
    events `[(observed_at, old_value), ...]` in observed order: the first
    transition observed at or after the cutoff says what it was before it;
    none means the status has not changed since."""
    for observed_at, old in events:
        if observed_at >= cutoff:
            return old or current
    return current


def _listing_histories(session) -> list[tuple[str, str, str | None, list[tuple[str, str | None]]]]:
    """(zip, current status, first_seen, status events) per listing."""
    listings = session.execute(
        select(Listing.id, Property.zip, Listing.status, Listing.first_seen)
        .join(Property, Property.id == Listing.property_id)
    ).all()
    events = session.execute(
        select(ListingEvent.listing_id, ListingEvent.observed_at, ListingEvent.old_value)
        .where(ListingEvent.event_type.in_(STATUS_EVENTS))
        .order_by(ListingEvent.observed_at)
    ).all()
    by_listing: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for listing_id, observed_at, old in events:
        by_listing[listing_id].append((observed_at, old))
    return [
        (zip_code, status, first_seen, by_listing.get(listing_id, []))
        for listing_id, zip_code, status, first_seen in listings
    ]


def _active_counts_at(histories, cutoff: str) -> dict[tuple[str, str], int]:
    """Active listings per geo as of the morning of `cutoff`: listings first
    seen before it whose replayed status was 'active'."""
    counts: Counter[str] = Counter()
    for zip_code, status, first_seen, events in histories:
        if first_seen is None or first_seen >= cutoff:
            continue
        if _status_at(status, events, cutoff) == "active":
            counts[zip_code] += 1
    return _rollup(counts.items())


def _replace(session, rows: list[dict], period_start: str, period: str) -> int:
    """Truncate-and-replace one day's rows for one window (docs/05 §1 rule 5).

    Scoped to DERIVED_SOURCES and to that `period_start`, so the daily
    history accumulates and published Redfin rows are never touched. The
    delete also clears a stale row when a geo flips between `derived` and
    `derived_city` — `source` is part of the unique key, so an upsert alone
    would leave the old row behind.
    """
    session.query(MarketMetric).filter(
        MarketMetric.metric == METRIC,
        MarketMetric.source.in_(DERIVED_SOURCES),
        MarketMetric.period_start == period_start,
        MarketMetric.period == period,
    ).delete(synchronize_session=False)
    return bulk_upsert(session, MarketMetric, rows, KEY_COLS)


def _backfill(session, today: date) -> int:
    """Write every (morning, window) since the first scan that has no rows yet.

    Each morning is replayed as the daily run would have seen it: listings
    and status events observed before that date, sales dated before it (as the
    sales table stands now — a backfilled row can see a closing the live run
    of that day had not been told about yet).
    """
    first = session.execute(select(func.min(ListingEvent.observed_at))).scalar_one_or_none()
    if first is None:
        return 0
    present = set(
        session.execute(
            select(MarketMetric.period_start, MarketMetric.period)
            .where(MarketMetric.metric == METRIC)
            .distinct()
        ).all()
    )
    histories = None
    written = 0
    day = date.fromisoformat(first[:10]) + timedelta(days=1)  # the morning after
    while day < today:
        asof = day.isoformat()
        missing = [m for m in LIVE_WINDOWS if (asof, live_period(m)) not in present]
        if missing:
            if histories is None:
                histories = _listing_histories(session)
            active = _active_counts_at(histories, asof)
            for months in missing:
                since = months_ago(day, months).isoformat()
                rows = compute_live_supply(
                    active, _sold_counts(session, since, before=asof), asof, months
                )
                written += _replace(session, rows, period_start=asof, period=live_period(months))
        day += timedelta(days=1)
    return written


def run(engine=None) -> str:
    with JobRunner("market-supply", engine) as runner:
        session = make_session(runner.engine)
        try:
            today = date.today()
            asof = today.isoformat()
            active = _active_counts(session)
            for months in LIVE_WINDOWS:
                with runner.item(live_period(months)):
                    since = months_ago(today, months).isoformat()
                    rows = compute_live_supply(
                        active, _sold_counts(session, since), asof, months
                    )
                    runner.items_upserted += _replace(
                        session, rows, period_start=asof, period=live_period(months)
                    )
                    session.commit()
                    log.info(
                        "market-supply live %s: %d rows as of %s", live_period(months), len(rows), asof
                    )
            with runner.item("backfill"):
                written = _backfill(session, today)
                runner.items_upserted += written
                session.commit()
                if written:
                    log.info("market-supply backfill: %d rows for past mornings", written)
        finally:
            session.close()
    return runner.status
