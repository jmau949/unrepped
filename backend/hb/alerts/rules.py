"""Alert rule evaluation — docs/09-alerts-spec.md §2–3.

Rules run at the end of each listing scan over that run's events plus tracker
state; `check_scan_failure` runs from `hb alerts send`. Every alert row carries a dedup_key (UNIQUE) constructed per docs/09 §3,
inserted with INSERT-or-ignore semantics — re-evaluating the same state emits
nothing new (matrix D11/D12).
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import (
    Alert,
    AppSetting,
    Listing,
    ListingEvent,
    ListingGroup,
    PipelineRun,
    Property,
    Sale,
    TrackedListing,
)
from hb.geo import haversine_miles
from hb.watchlist import watched_property_ids

NEW_COMP_RADIUS_MI = 0.5

log = logging.getLogger(__name__)

OFFER_BUCKETS = [3, 1]

# the watched-home outcomes worth a ping (docs/09 §2); price cuts, relists and
# back-on-market already reach watched homes through the widened scope below
WATCHED_STATUS_EVENTS = {"pending", "sold", "delisted"}


def _rules(session: Session) -> dict:
    row = session.get(AppSetting, "alert_rules")
    return row.value if row else {}


def _enabled(rules: dict, name: str) -> bool:
    return rules.get(name, {}).get("enabled", True)


def _insert(session: Session, **values) -> bool:
    stmt = sqlite_insert(Alert).values(**values).on_conflict_do_nothing(
        index_elements=["dedup_key"]
    )
    return session.execute(stmt).rowcount > 0


def _in_band(price: int | None, widen: float = 0.0) -> bool:
    if price is None:
        return False
    lo = settings.target_price_min * (1 - widen)
    hi = settings.target_price_max * (1 + widen)
    return lo <= price <= hi


def _tracked_listing_ids(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(TrackedListing.listing_id, TrackedListing.id).where(
            TrackedListing.stage.notin_(["won", "lost", "passed"])
        )
    ).all()
    return {listing_id: tid for listing_id, tid in rows}


def _max_bid(session: Session, property_id: str) -> int | None:
    return session.execute(
        select(TrackedListing.my_max_bid)
        .join(Listing, TrackedListing.listing_id == Listing.id)
        .where(Listing.property_id == property_id, TrackedListing.my_max_bid.is_not(None))
        .order_by(TrackedListing.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def evaluate(session: Session, events: list[ListingEvent], observed_at: str,
             new_sale_ids: set[str] | None = None) -> int:
    """Insert alerts for this scan's events + time-based rules. Returns count.

    `new_sale_ids` are the `sales` rows created this run (scan sold records +
    enrich RentCast comps); they drive the `new_comp_sold` rule.
    """
    rules = _rules(session)
    tracked = _tracked_listing_ids(session)
    # every home on the Watchlist stays in scope after the buyer stops pursuing
    # it (lost / passed / toured-only), whatever its price does
    watched = watched_property_ids(session)
    created = 0

    for event in events:
        listing = session.get(Listing, event.listing_id)
        if listing is None:
            continue
        is_tracked = listing.id in tracked
        is_watched = listing.property_id in watched
        in_scope = is_tracked or is_watched or _in_band(listing.list_price, widen=0.20)
        key_base = f"{listing.id}:{event.observed_at}:{event.new_value}"

        if (
            event.event_type == "price_change"
            and _enabled(rules, "price_cut")
            and event.old_value and event.new_value
            and int(event.new_value) < int(event.old_value)
            and in_scope
        ):
            cut_count = session.execute(
                select(ListingEvent).where(
                    ListingEvent.listing_id == listing.id,
                    ListingEvent.event_type == "price_change",
                )
            ).scalars().all()
            downs = sum(
                1 for e in cut_count
                if e.old_value and e.new_value and int(e.new_value) < int(e.old_value)
            )
            created += _insert(
                session, type="price_cut", listing_id=listing.id,
                tracked_listing_id=tracked.get(listing.id),
                dedup_key=f"price_cut:{key_base}",
                payload={"old": int(event.old_value), "new": int(event.new_value),
                         "pct": round(1 - int(event.new_value) / int(event.old_value), 4),
                         "cut_count": downs},
            )

        elif event.event_type == "relisted" and _enabled(rules, "relist") and in_scope:
            group = session.get(ListingGroup, listing.listing_group_id) if listing.listing_group_id else None
            created += _insert(
                session, type="relist", listing_id=listing.id,
                tracked_listing_id=tracked.get(listing.id),
                dedup_key=f"relist:{key_base}",
                payload={"cumulative_dom": group.cumulative_dom if group else None,
                         "episode_count": group.episode_count if group else None},
            )

        elif (
            event.event_type == "back_on_market"
            and _enabled(rules, "back_on_market")
            and in_scope
        ):
            created += _insert(
                session, type="back_on_market", listing_id=listing.id,
                tracked_listing_id=tracked.get(listing.id),
                dedup_key=f"back_on_market:{key_base}",
                payload={},
            )

        elif (
            event.event_type in WATCHED_STATUS_EVENTS
            and _enabled(rules, "watched_status")
            and is_watched
        ):
            created += _insert(
                session, type="watched_status", listing_id=listing.id,
                tracked_listing_id=tracked.get(listing.id),
                dedup_key=f"watched_status:{event.event_type}:{key_base}",
                payload={"event": event.event_type, "list_price": listing.list_price,
                         "original_list_price": listing.original_list_price,
                         "sold_price": listing.sold_price if event.event_type == "sold" else None,
                         "my_max_bid": _max_bid(session, listing.property_id)},
            )

        elif event.event_type == "new" and _enabled(rules, "new_listing_match"):
            prop = session.get(Property, listing.property_id)
            min_beds = rules.get("new_listing_match", {}).get("min_beds", 3)
            if (
                _in_band(listing.list_price)
                and prop is not None
                and prop.zip in settings.target_zips
                and (prop.beds or 0) >= min_beds
            ):
                created += _insert(
                    session, type="new_listing_match", listing_id=listing.id,
                    dedup_key=f"new_listing_match:{key_base}",
                    payload={"price": listing.list_price, "zip": prop.zip,
                             "beds": prop.beds, "sqft": prop.sqft},
                )

    # offer_date_soon: evaluated every scan over tracked listings (docs/09 §3)
    if _enabled(rules, "offer_date_soon"):
        for listing_id, tracked_id in tracked.items():
            listing = session.get(Listing, listing_id)
            if listing is None or not listing.offer_due_at:
                continue
            days_left = (date.fromisoformat(listing.offer_due_at[:10]) - date.today()).days
            # smallest matching bucket wins (else the 3-day key dedups away the 1-day alert)
            bucket = next((b for b in sorted(OFFER_BUCKETS) if 0 <= days_left <= b), None)
            if bucket is not None:
                created += _insert(
                    session, type="offer_date_soon", listing_id=listing_id,
                    tracked_listing_id=tracked_id,
                    dedup_key=f"offer_date_soon:{tracked_id}:{listing.offer_due_at}:{bucket}",
                    payload={"due": listing.offer_due_at, "days_left": days_left},
                )

    # new_comp_sold: a sale created this run near a tracked property (docs/09 §2;
    # radius honors the alert_rules setting). Dedup on (tracked_listing_id,
    # sale_id) ⇒ fires once (D11).
    if new_sale_ids and _enabled(rules, "new_comp_sold"):
        radius_mi = float(
            rules.get("new_comp_sold", {}).get("radius_mi", NEW_COMP_RADIUS_MI)
        )
        tracked_props = session.execute(
            select(TrackedListing.id, Listing.id, Property)
            .join(Listing, TrackedListing.listing_id == Listing.id)
            .join(Property, Listing.property_id == Property.id)
            .where(TrackedListing.stage.notin_(["won", "lost", "passed"]),
                   Property.lat.is_not(None), Property.lon.is_not(None))
        ).all()
        for sale_id in new_sale_ids:
            sale = session.get(Sale, sale_id)
            if sale is None:
                continue
            comp = session.get(Property, sale.property_id)
            if comp is None or comp.lat is None or comp.lon is None:
                continue
            for tracked_id, listing_id, tprop in tracked_props:
                if tprop.id == comp.id:
                    continue  # a tracked home's own sale isn't its comp
                dist = haversine_miles(tprop.lat, tprop.lon, comp.lat, comp.lon)
                if dist > radius_mi:
                    continue
                ppsf = round(sale.sale_price / comp.sqft) if comp.sqft else None
                created += _insert(
                    session, type="new_comp_sold", listing_id=listing_id,
                    tracked_listing_id=tracked_id,
                    dedup_key=f"new_comp_sold:{tracked_id}:{sale_id}",
                    payload={"comp_address": comp.address_norm.title(),
                             "price": sale.sale_price, "ppsf": ppsf,
                             "distance_mi": round(dist, 2), "dom": sale.dom},
                )

    if created:
        log.info("alert rules: %d new alerts", created)
    return created


def check_scan_failure(session: Session) -> int:
    """`scan_failure`: the last 2 finished listing-scan runs both failed (docs/09 §2).

    Run by `hb alerts send`, not by the scan: a scan that fails never reaches
    `evaluate`, and inside a scan its own `running` row is always the newest.
    """
    if not _enabled(_rules(session), "scan_failure"):
        return 0
    recent = session.execute(
        select(PipelineRun.status, PipelineRun.started_at)
        .where(PipelineRun.job == "listing-scan", PipelineRun.status != "running")
        .order_by(PipelineRun.started_at.desc())
        .limit(2)
    ).all()
    if len(recent) < 2 or any(status != "failed" for status, _ in recent):
        return 0
    created = int(_insert(
        session, type="scan_failure",
        dedup_key=f"scan_failure:{date.today().isoformat()}",
        payload={"runs": [started for _, started in recent]},
    ))
    if created:
        log.info("alert rules: listing scan failing")
    return created
