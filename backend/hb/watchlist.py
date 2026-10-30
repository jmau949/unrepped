"""Watchlist — every home the buyer saved or toured, and what happened to it
(docs/08 §5b, docs/07 §Watchlist).

A property is watched when `properties.watched_at` is set: the detail page's
Watch button, adding the home to the tracker, or logging a tour of it all stamp
it, so untracking or passing never drops it. Removing the home clears it.
Keying on the property, not the listing, is what lets a relisted home — a new
listing row — stay on the list as the same home.

The scan keeps these homes fresh: alert scope (alerts/rules.py) and the weekly
Realtor price-history refresh (listing_scan.py) both read
`watched_property_ids`. The history is what reveals a sale after the home left
the market, which the city scan alone can no longer see.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.models import (
    Listing, ListingEvent, ListingGroup, Property, PropertyTour, TrackedListing, utcnow_iso,
)


def watched_property_ids(session: Session) -> set[str]:
    """Properties on the Watchlist."""
    return set(session.execute(
        select(Property.id).where(Property.watched_at.is_not(None))
    ).scalars())


def set_watching(prop: Property, watching: bool) -> None:
    """Put a home on the Watchlist (keeping its first stamp) / take it off."""
    prop.watched_at = (prop.watched_at or utcnow_iso()) if watching else None


def is_watching(prop: Property) -> bool:
    return prop.watched_at is not None


def current_listing(session: Session, property_id: str) -> Listing | None:
    """The property's latest marketing episode — what the home is doing now."""
    return session.execute(
        select(Listing)
        .where(Listing.property_id == property_id)
        .order_by(Listing.list_date.desc().nulls_last(), Listing.first_seen.desc())
        .limit(1)
    ).scalar_one_or_none()


def _public_record_sale(prop: Property, listing: Listing) -> dict | None:
    """A Realtor-history sale dated on/after this episode began — the home sold
    after leaving the market (or before the scan saw it close)."""
    start = listing.list_date or listing.first_seen[:10]
    for entry in prop.price_history or []:  # newest first
        if "sold" in str(entry.get("event") or "").lower() and entry.get("price"):
            if entry.get("date") and entry["date"] >= start:
                return {"price": entry["price"], "date": entry["date"]}
            return None
    return None


def _involvement(session: Session, prop_id: str) -> dict:
    tracked = session.execute(
        select(TrackedListing)
        .join(Listing, TrackedListing.listing_id == Listing.id)
        .where(Listing.property_id == prop_id)
        .order_by(TrackedListing.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    tours = session.execute(
        select(PropertyTour)
        .where(PropertyTour.property_id == prop_id)
        .order_by(PropertyTour.toured_on.desc())
    ).scalars().all()
    last = tours[0] if tours else None
    return {
        "tracked_id": tracked.id if tracked else None,
        "stage": tracked.stage if tracked else None,
        "my_max_bid": tracked.my_max_bid if tracked else None,
        "tour_count": len(tours),
        "last_toured_on": last.toured_on if last else None,
        "verdict": last.verdict if last else None,
        "gut_score": last.gut_score if last else None,
    }


def _last_change(session: Session, prop_id: str) -> dict | None:
    event = session.execute(
        select(ListingEvent)
        .join(Listing, ListingEvent.listing_id == Listing.id)
        .where(Listing.property_id == prop_id)
        .order_by(ListingEvent.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if event is None:
        return None
    return {"event_type": event.event_type, "old_value": event.old_value,
            "new_value": event.new_value, "observed_at": event.observed_at}


def rows(session: Session) -> list[dict]:
    """One row per watched home, most recently changed first."""
    from hb.api.listings import _summary  # lazy: the API layer imports this module

    out = []
    for prop_id in watched_property_ids(session):
        prop = session.get(Property, prop_id)
        listing = current_listing(session, prop_id)
        if prop is None or listing is None:
            continue
        group = session.get(ListingGroup, listing.listing_group_id) if listing.listing_group_id else None
        summary = _summary(session, listing, prop, group, True).model_dump()

        sold_price, sold_date, sold_source = listing.sold_price, listing.sold_date, None
        status = listing.status
        if status == "sold" and sold_price:
            sold_source = "listing"
        elif (record := _public_record_sale(prop, listing)) is not None:
            sold_price, sold_date, sold_source = record["price"], record["date"], "public_record"
            status = "sold"

        involvement = _involvement(session, prop_id)
        max_bid = involvement["my_max_bid"]
        ask = listing.original_list_price
        out.append({
            **summary,
            "status": status,
            "sold_price": sold_price,
            "sold_date": sold_date,
            "sold_source": sold_source,
            "sp_lp": round(sold_price / ask, 4) if sold_price and ask else None,
            "vs_max_bid": sold_price - max_bid if sold_price and max_bid else None,
            "involvement": involvement,
            "last_change": _last_change(session, prop_id),
            "watched_at": prop.watched_at,
        })
    out.sort(key=lambda r: (r["last_change"] or {}).get("observed_at") or "", reverse=True)
    return out
