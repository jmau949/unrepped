"""Listings endpoints — docs/07-api-spec.md §Listings."""

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hb import listing_contact, watchlist
from hb.api.contacts import contact_out
from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import (
    AvmSnapshot,
    Contact,
    HazardFlag,
    Listing,
    ListingEvent,
    ListingGroup,
    OpenHouse,
    Property,
    TrackedListing,
    utcnow_iso,
)
from hb.engine import exposure
from hb.schools_match import schools_for_property

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["listings"])


class ListingSummary(BaseModel):
    id: str
    property_id: str
    address: str
    city: str | None
    zip: str
    lat: float | None
    lon: float | None
    status: str
    list_price: int | None
    original_list_price: int | None
    sold_price: int | None
    sold_date: str | None
    beds: int | None
    baths: float | None
    sqft: int | None
    list_date: str | None
    dom_source: int | None
    cumulative_dom: int | None
    price_cut_count: int
    cut_pct: float | None  # % off the original ask; None when never reduced
    is_relist: bool
    predicted_sale: dict | None
    posture: str | None = None             # underpriced | near_market | overpriced | unknown
    posture_confidence: str | None = None  # low | medium | high
    posture_p_below_list: float | None = None  # P(sells below the current asking price)
    photo_url: str | None
    url: str | None
    tracked: bool
    viewed_at: str | None  # detail-page open in this status; NULL = unread
    # soonest open house not yet over: {start_at, end_at} UTC ISO (docs/05 §4c)
    next_open_house: dict | None = None


class EventOut(BaseModel):
    event_type: str
    old_value: str | None
    new_value: str | None
    observed_at: str


def _sqft_mismatch(prop: Property) -> bool:
    """>15% listing-vs-assessor sqft divergence (docs/05 §8) — computed at read
    time, NULL-safe: no assessor data ⇒ no flag."""
    return bool(
        prop.sqft and prop.assessor_sqft
        and abs(prop.sqft - prop.assessor_sqft) / prop.assessor_sqft > 0.15
    )


def _cut_pct(listing: Listing) -> float | None:
    """How far the current ask sits below the original one, in percent. Derived
    from the two prices rather than from `price_change` events so a listing we
    started observing mid-campaign — or one backfilled with no event rows — still
    reports its reduction."""
    original, current = listing.original_list_price, listing.list_price
    if not original or not current or current >= original:
        return None
    return round((original - current) / original * 100, 1)


def _next_open_house(session: Session, listing: Listing) -> dict | None:
    if listing.status != "active":
        return None
    row = session.execute(
        select(OpenHouse.start_at, OpenHouse.end_at)
        .where(OpenHouse.listing_id == listing.id, OpenHouse.end_at > utcnow_iso(),
               OpenHouse.cancelled_at.is_(None))
        .order_by(OpenHouse.start_at)
        .limit(1)
    ).first()
    return {"start_at": row.start_at, "end_at": row.end_at} if row else None


def _open_houses(session: Session, listing: Listing) -> list[dict]:
    """Every slot for this home not yet over, soonest first (docs/07 §Listings).

    Unlike the badge this keeps cancelled slots: a cancelled row only exists when
    the buyer had scheduled it (05 §4c), and the page should say the visit is off
    rather than silently drop it. Empty once the home is no longer active — the
    schedule page is where a stale scheduled visit gets explained.
    """
    if listing.status != "active":
        return []
    rows = session.execute(
        select(OpenHouse)
        .where(OpenHouse.listing_id == listing.id, OpenHouse.end_at > utcnow_iso())
        .order_by(OpenHouse.start_at)
    ).scalars().all()
    return [
        {"id": oh.id, "source": oh.source, "start_at": oh.start_at, "end_at": oh.end_at,
         "description": oh.description, "href": oh.href, "methods": oh.methods,
         "scheduled": oh.scheduled_at is not None,
         "cancelled": oh.cancelled_at is not None}
        for oh in rows
    ]


def _remarks(listing: Listing) -> str | None:
    """The listing agent's public remarks, kept verbatim in `listings.raw.text`
    by the scan (05 §4.2); None when the source carried none."""
    text = (listing.raw or {}).get("text")
    return text.strip() or None if isinstance(text, str) else None


def _photo_url(listing: Listing) -> str | None:
    if listing.photo_paths:
        return "/photos/" + listing.photo_paths[0].replace("\\", "/").removeprefix("photos/")
    return listing.photo_urls[0] if listing.photo_urls else None


def _summary(session: Session, listing: Listing, prop: Property,
             group: ListingGroup | None, tracked: bool) -> ListingSummary:
    return ListingSummary(
        id=listing.id,
        property_id=prop.id,
        address=f"{prop.address_norm.title()}{' #' + prop.unit if prop.unit else ''}",
        city=prop.city,
        zip=prop.zip,
        lat=prop.lat,
        lon=prop.lon,
        status=listing.status,
        list_price=listing.list_price,
        original_list_price=listing.original_list_price,
        sold_price=listing.sold_price,
        sold_date=listing.sold_date,
        beds=prop.beds,
        baths=prop.baths,
        sqft=prop.sqft,
        list_date=listing.list_date,
        dom_source=listing.dom_source,
        cumulative_dom=group.cumulative_dom if group else None,
        price_cut_count=exposure.price_cut_count(session, listing.id),
        cut_pct=_cut_pct(listing),
        is_relist=bool(group and group.episode_count > 1),
        predicted_sale=None,
        photo_url=_photo_url(listing),
        url=listing.url,
        tracked=tracked,
        viewed_at=listing.viewed_at,
        next_open_house=_next_open_house(session, listing),
    )


def attach_predicted(session: Session, page_items: list[ListingSummary],
                     orm_by_id: dict, cache: dict | None = None) -> None:
    """Fill `predicted_sale` for the returned page only (overbid per listing is
    non-trivial), memoizing comp-sample loads, per-property CMA lookups, each
    listing's exposure and the city-level area-median-DOM aggregate across the
    page. All routers serve the same blended number via
    valuation.predicted_sale. The `cache` is threaded all the way down to
    overbid/posture/exposure — new call sites must pass it or the page falls
    back to one query per listing."""
    from hb.engine import valuation

    cache = cache if cache is not None else {}
    for item in page_items:
        pair = orm_by_id.get(item.id)
        if pair is None:
            continue
        listing, prop = pair
        item.predicted_sale = valuation.predicted_sale(session, listing, prop, cache)
        attach_posture(session, item, listing, prop, cache)


def attach_posture(session: Session, item: ListingSummary, listing: Listing,
                   prop: Property, cache: dict | None = None):
    """Fill the lightweight posture strings on a summary (docs/06 §5.6). Returns
    the full PostureResult so the detail endpoint can serve it; None on failure
    (posture must never 500 a page)."""
    from hb.engine import posture, valuation

    try:
        cache = cache if cache is not None else {}
        cma_key = ("cma_estimate", prop.id)
        if cma_key not in cache:
            cache[cma_key] = valuation.latest_cma_estimate(session, prop.id)
        post = posture.classify(session, listing, prop, item.predicted_sale,
                                cma_estimate=cache[cma_key], cache=cache)
        item.posture = post.posture
        item.posture_confidence = post.confidence
        item.posture_p_below_list = post.p_below_list
        return post
    except Exception as exc:  # noqa: BLE001
        log.warning("posture failed for listing %s: %s", listing.id, exc)
        return None


@router.get("/listings")
def list_listings(
    status: str | None = Query(default="active"),
    city: str | None = None,
    zip: str | None = None,
    q: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_sold_price: int | None = None,
    max_sold_price: int | None = None,
    min_beds: int | None = None,
    has_price_cut: bool = False,
    min_cut_pct: float | None = None,
    stale_only: bool = False,
    sort: str = Query(default="list_date"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> dict:
    with make_session() as session:
        stmt = (
            select(Listing, Property, ListingGroup, TrackedListing.id)
            .join(Property, Listing.property_id == Property.id)
            .outerjoin(ListingGroup, Listing.listing_group_id == ListingGroup.id)
            .outerjoin(TrackedListing, TrackedListing.listing_id == Listing.id)
        )
        if status and status != "any":
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            stmt = stmt.where(Listing.status.in_(statuses))
        if city:
            stmt = stmt.where(Property.city.in_([c.strip() for c in city.split(",")]))
        if zip:
            stmt = stmt.where(Property.zip == zip)
        if q and q.strip():
            # every whitespace-separated token must hit one of the text columns,
            # so "sunnyvale maple" narrows instead of widening. ZIP matches on a
            # PREFIX: a substring match makes any street number in the query
            # ("1 maple") collide with the digits inside every ZIP.
            for token in q.lower().split():
                like = f"%{token}%"
                stmt = stmt.where(or_(
                    func.lower(Property.address_norm).like(like),
                    func.lower(func.coalesce(Property.city, "")).like(like),
                    func.lower(Property.unit).like(like),
                    Property.zip.like(f"{token}%"),
                ))
        if min_price:
            stmt = stmt.where(Listing.list_price >= min_price)
        if max_price:
            stmt = stmt.where(Listing.list_price <= max_price)
        if min_sold_price:
            stmt = stmt.where(Listing.sold_price >= min_sold_price)
        if max_sold_price:
            stmt = stmt.where(Listing.sold_price <= max_sold_price)
        if min_beds:
            stmt = stmt.where(Property.beds >= min_beds)

        rows = session.execute(stmt).all()

        orm_by_id = {listing.id: (listing, prop) for listing, prop, group, tracked_id in rows}
        items = [
            _summary(session, listing, prop, group, tracked_id is not None)
            for listing, prop, group, tracked_id in rows
        ]

        if has_price_cut:
            items = [i for i in items if i.price_cut_count > 0 or i.cut_pct is not None]
        if min_cut_pct:
            items = [i for i in items if (i.cut_pct or 0) >= min_cut_pct]
        cache: dict = {}
        if stale_only:
            from hb.engine import overbid

            median_dom = exposure.area_median_dom(session, None, cache)
            if median_dom:
                items = [
                    i for i in items
                    if (i.cumulative_dom or i.dom_source or 0)
                    > overbid.STALE_DOM_MULTIPLIER * median_dom
                ]

        keys = {
            "list_date": lambda i: i.list_date or "",
            "price": lambda i: i.list_price or 0,
            "sold_date": lambda i: i.sold_date or "",
            "sold_price": lambda i: i.sold_price or 0,
            "cdom": lambda i: i.cumulative_dom or i.dom_source or 0,
            "cut": lambda i: i.cut_pct or 0,
        }
        items.sort(key=keys.get(sort, keys["list_date"]), reverse=True)

        total = len(items)
        page = items[offset:offset + limit]
        attach_predicted(session, page, orm_by_id, cache)
        return {"total": total, "items": [i.model_dump() for i in page]}


@router.get("/listings/{listing_id}")
def listing_detail(listing_id: str) -> dict:
    with make_session() as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        # opening the detail page IS the "viewed" action (docs/08 §2b); the
        # first view in a status wins. listing-scan clears the stamp when the
        # home closes, so a sold listing restamps on its next open.
        if listing.viewed_at is None:
            listing.viewed_at = utcnow_iso()
            session.commit()
        prop = session.get(Property, listing.property_id)
        group = session.get(ListingGroup, listing.listing_group_id) if listing.listing_group_id else None
        tracked = session.execute(
            select(TrackedListing).where(TrackedListing.listing_id == listing_id)
        ).scalar_one_or_none()

        events = session.execute(
            select(ListingEvent)
            .where(ListingEvent.listing_id == listing_id)
            .order_by(ListingEvent.observed_at)
        ).scalars().all()

        episodes = []
        if group:
            episodes = [
                # the price this episode STARTED at, not e.list_price: that
                # column tracks the live price, so a timeline "Listed" row
                # built from it silently rewrites itself on every price cut
                {"listing_id": e.id, "source": e.source, "list_date": e.list_date,
                 "original_list_price": e.original_list_price or e.list_price,
                 "pending_date": e.pending_date,
                 "delist_date": e.delist_date, "sold_date": e.sold_date,
                 "sold_price": e.sold_price, "status": e.status}
                for e in session.execute(
                    select(Listing).where(Listing.listing_group_id == group.id)
                    .order_by(Listing.list_date)
                ).scalars().all()
            ]

        avms = session.execute(
            select(AvmSnapshot).where(AvmSnapshot.property_id == prop.id)
            .order_by(AvmSnapshot.as_of.desc())
        ).scalars().all()
        latest_by_source: dict[str, AvmSnapshot] = {}
        for a in avms:
            latest_by_source.setdefault(a.source, a)

        hazards = session.execute(
            select(HazardFlag).where(HazardFlag.property_id == prop.id)
        ).scalars().all()

        schools = schools_for_property(session, prop.lat, prop.lon, prop.zip)

        # the people behind this listing: saved by hand on the detail page (docs/08 §3 1c)
        contacts = session.execute(
            select(Contact).where(Contact.listing_id == listing_id).order_by(Contact.kind)
        ).scalars().all()

        summary = _summary(session, listing, prop, group, tracked is not None)
        from hb.engine import valuation
        summary.predicted_sale = valuation.predicted_sale(session, listing, prop)
        post = attach_posture(session, summary, listing, prop)
        assessor_mismatch = _sqft_mismatch(prop)
        return {
            **summary.model_dump(),
            "posture_detail": asdict(post) if post else None,
            "offer_due_at": listing.offer_due_at,
            "sold_price": listing.sold_price,
            "sold_date": listing.sold_date,
            "photos": [
                "/photos/" + p.replace("\\", "/").removeprefix("photos/")
                for p in (listing.photo_paths or [])
            ] or ([listing.photo_urls[0]] if listing.photo_urls else []),
            "events": [EventOut.model_validate(e, from_attributes=True).model_dump()
                       for e in events],
            "listing_group": {
                "cumulative_dom": group.cumulative_dom,
                "episode_count": group.episode_count,
                "ended_by": group.ended_by,
                "episodes": episodes,
            } if group else None,
            "property": {
                "condition_tag": prop.condition_tag,
                "condition_notes": prop.condition_notes,
                "lot_sqft": prop.lot_sqft,
                "year_built": prop.year_built,
                "assessor_sqft": prop.assessor_sqft,
                "sqft_mismatch": assessor_mismatch,
                "schools": schools,
            },
            "avm_snapshots": [
                {"source": a.source, "value": a.value, "low": a.low, "high": a.high,
                 "as_of": a.as_of}
                for a in latest_by_source.values()
            ],
            "hazard_flags": [{"hazard": h.hazard, "zone_value": h.zone_value,
                              "checked_at": h.checked_at} for h in hazards],
            "price_history": prop.price_history or [],
            # the agent's pitch and the ways in — the two things a portal shows
            # under the photos that the summary chip only hints at
            "remarks": _remarks(listing),
            "open_houses": _open_houses(session, listing),
            "timezone": settings.timezone,
            "tracked_id": tracked.id if tracked else None,
            "tracked_stage": tracked.stage if tracked else None,
            "watching": watchlist.is_watching(prop),
            # the listing side off the MLS record — direct line, never a portal
            # lead form (docs/14 §2.3); null when the source carried no advertiser
            "listing_contact": listing_contact.from_raw(listing.raw),
            "contacts": [contact_out(c) for c in contacts],
        }


@router.get("/listings/{listing_id}/brief", response_class=PlainTextResponse)
def listing_brief(listing_id: str) -> PlainTextResponse:
    """Everything known about this home as pasteable markdown (docs/13 §9)."""
    from hb.brief import build_brief

    with make_session() as session:
        try:
            md = build_brief(session, listing_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


class ListingPatch(BaseModel):
    offer_due_at: str | None = None


@router.patch("/listings/{listing_id}")
def patch_listing(listing_id: str, patch: ListingPatch) -> dict:
    with make_session() as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        if patch.offer_due_at is not None:
            listing.offer_due_at = patch.offer_due_at or None
        session.commit()
        return {"id": listing.id, "offer_due_at": listing.offer_due_at}


@router.post("/properties/{property_id}/enrich")
def enrich_property(property_id: str) -> dict:
    """Trigger the enrich pipeline inline for one property (docs/07 §Listings)."""
    from hb.pipelines import enrich

    with make_session() as session:
        if session.get(Property, property_id) is None:
            raise HTTPException(404, "property not found")
        bind = session.get_bind()
    enrich.run(engine=bind, property_id=property_id)
    with make_session() as session:
        avms = session.execute(
            select(AvmSnapshot).where(AvmSnapshot.property_id == property_id)
            .order_by(AvmSnapshot.as_of.desc())
        ).scalars().all()
        latest: dict[str, AvmSnapshot] = {}
        for a in avms:
            latest.setdefault(a.source, a)
        return {
            "avm_snapshots": [
                {"source": a.source, "value": a.value, "low": a.low, "high": a.high,
                 "as_of": a.as_of}
                for a in latest.values()
            ],
            "rentcast_quota_remaining": enrich.rentcast_quota(session),
        }


class PropertyPatch(BaseModel):
    condition_tag: str | None = None
    condition_notes: str | None = None


@router.patch("/properties/{property_id}")
def patch_property(property_id: str, patch: PropertyPatch) -> dict:
    with make_session() as session:
        prop = session.get(Property, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        if patch.condition_tag is not None:
            if patch.condition_tag not in ("renovated", "dated", "fixer", ""):
                raise HTTPException(422, "condition_tag must be renovated|dated|fixer")
            prop.condition_tag = patch.condition_tag or None
        if patch.condition_notes is not None:
            prop.condition_notes = patch.condition_notes or None
        prop.updated_at = utcnow_iso()
        session.commit()
        return {"id": prop.id, "condition_tag": prop.condition_tag,
                "condition_notes": prop.condition_notes}
