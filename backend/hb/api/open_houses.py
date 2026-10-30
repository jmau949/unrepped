"""Open-house endpoints — docs/07-api-spec.md §Open houses.

The distance origin ("home") lives in the `settings` KV row `home_location`
as {address, lat, lon}: one place, edited from the page, geocoded once per
change. HOME_ADDRESS only seeds it on first read.

The buyer's schedule is the set of slots with `scheduled_at` set — kept in
the DB, so it survives reloads and devices, and the pipeline flags a scheduled
slot `cancelled_at` rather than deleting it. `schedule_position` is the
buyer's visiting order: a new slot goes last, `PUT /schedule/order`
rearranges, and a day's route drives that order.
"""

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hb.api.listings import _summary
from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import (
    AppSetting,
    Listing,
    ListingGroup,
    OpenHouse,
    Property,
    TrackedListing,
    utcnow_iso,
)
from hb.geo import haversine_miles
from hb.open_houses import geocode
from hb.open_houses.route import (
    MAPS_MAX_STOPS,
    HaversineEstimator,
    Stop,
    drive_legs,
    maps_url,
    suggested_order,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/open-houses", tags=["open-houses"])

SETTING_KEY = "home_location"


class OriginIn(BaseModel):
    address: str


class RouteIn(BaseModel):
    open_house_ids: list[str]  # visiting order
    optimize: bool = False  # True = answer in the planner's suggested order instead
    start_at: str | None = None  # optimize only: ISO-8601; default = as the first window opens
    dwell_min: int = 20  # optimize only: minutes at each stop


class OrderIn(BaseModel):
    open_house_ids: list[str]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _geocode(address: str) -> geocode.GeoPoint | None:
    try:
        return geocode.GEOCODER.geocode(address)
    except Exception as exc:  # noqa: BLE001 — geocoder outage must not 500 the page
        log.warning("geocode failed for %r: %s", address, exc)
        raise HTTPException(502, f"geocoder unavailable: {exc}") from exc


def load_origin(session: Session) -> dict | None:
    """{address, lat, lon}, or None when no home is set. Seeds from
    HOME_ADDRESS on first read; a seed that fails to geocode stays unset."""
    row = session.get(AppSetting, SETTING_KEY)
    if row and row.value:
        return row.value
    if not settings.home_address.strip():
        return None
    try:
        point = geocode.GEOCODER.geocode(settings.home_address.strip())
    except Exception as exc:  # noqa: BLE001
        log.warning("seeding home_location failed: %s", exc)
        return None
    if point is None:
        return None
    return _save_origin(session, point)


def _save_origin(session: Session, point: geocode.GeoPoint) -> dict:
    value = {"address": point.address, "lat": point.lat, "lon": point.lon}
    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        session.add(AppSetting(key=SETTING_KEY, value=value))
    else:
        row.value = value
        row.updated_at = utcnow_iso()
    session.commit()
    return value


def _default_window(now: datetime) -> tuple[datetime, datetime]:
    """Now -> the end of the coming Sunday (today, if it is Sunday), local time."""
    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    sunday = local.date() + timedelta(days=(6 - local.weekday()) % 7)
    end = datetime.combine(sunday + timedelta(days=1), time.min, tzinfo=tz)
    return now, end


def _parse(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(422, f"{field}: not an ISO-8601 datetime") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(settings.timezone))


def _distance(origin: dict | None, prop: Property) -> float | None:
    if not origin or origin.get("lat") is None or prop.lat is None or prop.lon is None:
        return None
    return round(haversine_miles(origin["lat"], origin["lon"], prop.lat, prop.lon), 1)


def _rows_stmt():
    return (
        select(OpenHouse, Listing, Property, ListingGroup, TrackedListing.id)
        .join(Listing, OpenHouse.listing_id == Listing.id)
        .join(Property, Listing.property_id == Property.id)
        .outerjoin(ListingGroup, Listing.listing_group_id == ListingGroup.id)
        .outerjoin(TrackedListing, TrackedListing.listing_id == Listing.id)
    )


def _items(session: Session, rows, origin: dict | None,
           max_miles: float | None = None) -> list[dict]:
    """One payload per slot, with the embedded ListingSummary built once per home."""
    summaries: dict[str, dict] = {}
    items = []
    for oh, listing, prop, group, tracked_id in rows:
        distance = _distance(origin, prop)
        if max_miles is not None and (distance is None or distance > max_miles):
            continue
        if listing.id not in summaries:
            summaries[listing.id] = _summary(session, listing, prop, group,
                                             tracked_id is not None).model_dump()
        items.append({
            "id": oh.id, "listing_id": listing.id, "source": oh.source,
            "start_at": oh.start_at, "end_at": oh.end_at,
            "description": oh.description, "href": oh.href, "methods": oh.methods,
            "scheduled": oh.scheduled_at is not None,
            "cancelled": oh.cancelled_at is not None,
            "distance_mi": distance, "listing": summaries[listing.id],
        })
    return items


def _stop_label(prop: Property) -> str:
    street = f"{prop.address_norm.title()}{' #' + prop.unit if prop.unit else ''}"
    return ", ".join(p for p in (street, prop.city, f"{prop.state or settings.geo.state} {prop.zip}".strip()) if p)


@router.get("")
def list_open_houses(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    max_miles: float | None = None,
    city: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    sort: str = Query(default="time"),
) -> dict:
    now = datetime.now(timezone.utc)
    default_from, default_to = _default_window(now)
    start = _parse(from_, "from") if from_ else default_from
    end = _parse(to, "to") if to else default_to

    with make_session() as session:
        origin = load_origin(session)
        stmt = _rows_stmt().where(
            Listing.status == "active", OpenHouse.cancelled_at.is_(None),
            OpenHouse.end_at > _iso(start), OpenHouse.start_at < _iso(end))
        if city:
            stmt = stmt.where(Property.city.in_([c.strip() for c in city.split(",")]))
        if min_price:
            stmt = stmt.where(Listing.list_price >= min_price)
        if max_price:
            stmt = stmt.where(Listing.list_price <= max_price)
        items = _items(session, session.execute(stmt).all(), origin, max_miles)

        keys = {
            "time": lambda i: (i["start_at"], i["distance_mi"] or 0),
            "distance": lambda i: (i["distance_mi"] is None, i["distance_mi"] or 0, i["start_at"]),
            "price": lambda i: (i["listing"]["list_price"] or 0, i["start_at"]),
        }
        items.sort(key=keys.get(sort, keys["time"]))
        return {"origin": origin, "from": _iso(start), "to": _iso(end),
                "timezone": settings.timezone, "items": items}


@router.get("/schedule")
def get_schedule() -> dict:
    """Every scheduled slot that hasn't ended, in the buyer's order — including ones
    upstream cancelled and ones whose home has since gone pending, so the
    buyer sees why a visit is off rather than having it vanish."""
    with make_session() as session:
        origin = load_origin(session)
        rows = session.execute(
            _rows_stmt()
            .where(OpenHouse.scheduled_at.is_not(None), OpenHouse.end_at > utcnow_iso())
            .order_by(OpenHouse.schedule_position, OpenHouse.start_at)
        ).all()
        return {"origin": origin, "timezone": settings.timezone,
                "items": _items(session, rows, origin)}


@router.put("/{open_house_id}/schedule")
def schedule(open_house_id: str) -> dict:
    with make_session() as session:
        oh = session.get(OpenHouse, open_house_id)
        if oh is None:
            raise HTTPException(404, "open house not found")
        if oh.scheduled_at is None:
            last = session.execute(select(func.max(OpenHouse.schedule_position))).scalar()
            oh.scheduled_at = utcnow_iso()
            oh.schedule_position = (last or 0) + 1
            session.commit()
        return {"id": oh.id, "scheduled": True}


@router.put("/schedule/order")
def reorder_schedule(body: OrderIn) -> dict:
    """Put these scheduled slots (normally one day's) in the given order. They
    swap among the positions they already hold, so other days keep theirs."""
    ids = body.open_house_ids
    if not ids or len(set(ids)) != len(ids):
        raise HTTPException(422, "give each scheduled open house once")
    with make_session() as session:
        rows = session.execute(
            select(OpenHouse).where(OpenHouse.id.in_(ids), OpenHouse.scheduled_at.is_not(None))
        ).scalars().all()
        by_id = {oh.id: oh for oh in rows}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise HTTPException(404, f"not on the schedule: {', '.join(missing)}")
        positions = sorted(oh.schedule_position or 0 for oh in rows)
        for position, oh_id in zip(positions, ids):
            by_id[oh_id].schedule_position = position
        session.commit()
        return {"open_house_ids": ids}


@router.delete("/{open_house_id}/schedule")
def unschedule(open_house_id: str) -> dict:
    with make_session() as session:
        oh = session.get(OpenHouse, open_house_id)
        if oh is None:
            raise HTTPException(404, "open house not found")
        if oh.cancelled_at is not None:
            # only the schedule kept a cancelled slot alive — nothing else wants it
            session.delete(oh)
        else:
            oh.scheduled_at = oh.schedule_position = None
        session.commit()
        return {"id": open_house_id, "scheduled": False}


@router.get("/origin")
def get_origin() -> dict:
    with make_session() as session:
        return {"origin": load_origin(session)}


@router.put("/origin")
def put_origin(body: OriginIn) -> dict:
    address = body.address.strip()
    if not address:
        raise HTTPException(422, "address is required")
    point = _geocode(address)
    if point is None:
        raise HTTPException(422, f"couldn't find that address: {address}")
    with make_session() as session:
        return {"origin": _save_origin(session, point)}


@router.post("/route")
def route(body: RouteIn) -> dict:
    """The drive into each stop in the order given — every stop is kept, there
    are no visit times. `optimize` answers in the planner's suggested order."""
    if not body.open_house_ids:
        raise HTTPException(422, "pick at least one open house")
    with make_session() as session:
        origin = load_origin(session)
        if not origin or origin.get("lat") is None:
            raise HTTPException(422, "set your home address first")
        rows = session.execute(
            select(OpenHouse, Listing, Property)
            .join(Listing, OpenHouse.listing_id == Listing.id)
            .join(Property, Listing.property_id == Property.id)
            .where(OpenHouse.id.in_(body.open_house_ids))
        ).all()
        found = {oh.id: (oh, listing, prop) for oh, listing, prop in rows}
        missing = [i for i in body.open_house_ids if i not in found]
        if missing:
            raise HTTPException(404, f"unknown open house id(s): {', '.join(missing)}")

        listing_of, stops = {}, []
        for oh_id in dict.fromkeys(body.open_house_ids):
            oh, listing, prop = found[oh_id]
            listing_of[oh.id] = listing.id
            stops.append(Stop(id=oh.id, label=_stop_label(prop), lat=prop.lat, lon=prop.lon,
                              start_at=datetime.fromisoformat(oh.start_at),
                              end_at=datetime.fromisoformat(oh.end_at)))

    home = (origin["lat"], origin["lon"])
    estimator = HaversineEstimator(settings.route_avg_mph, settings.route_detour_factor)
    if body.optimize:
        stops = suggested_order(
            home, stops, start_at=_parse(body.start_at, "start_at") if body.start_at else None,
            dwell_min=body.dwell_min, estimator=estimator)
    legs = drive_legs(home, stops, estimator)
    return {
        "origin": origin,
        "total_drive_min": round(sum(leg.drive_min or 0 for leg in legs), 1),
        "maps_url": maps_url(origin["address"], stops),
        "maps_stops": min(len(stops), MAPS_MAX_STOPS),
        "stops": [{
            "open_house_id": leg.stop.id, "listing_id": listing_of[leg.stop.id],
            "address": leg.stop.label, "start_at": _iso(leg.stop.start_at),
            "end_at": _iso(leg.stop.end_at), "drive_min": leg.drive_min,
            "drive_miles": leg.drive_miles,
        } for leg in legs],
    }
