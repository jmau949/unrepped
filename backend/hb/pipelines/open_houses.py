"""open-houses pipeline — docs/05-pipelines.md §4c.

For each enabled source (hb.open_houses.sources), in OPEN_HOUSE_SOURCES order:
fetch every target city's scheduled slots, attach each to the active listing
the scan stored — by the scan's own (source, source_listing_id) when the
source shares it, else by MLS number + ZIP — and upsert on
(listing_id, start_at). A slot several sources report is one row, credited to
the first source; later sources only refresh its `last_seen`.

When every source fetched every city cleanly, future slots that no source
lists any more are deleted (cancelled, or the home went pending) — except
slots on the buyer's schedule, which are stamped `cancelled_at` instead so the
schedule can show it, and revived if upstream lists them again. Any failed
fetch skips the sweep so a transient outage never wipes the calendar. Past
slots are kept. A slot whose listing the scan hasn't stored yet is skipped and
picked up on a later run — so listing-scan runs this job in its tail rather
than it sitting in DAILY_SEQUENCE.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine

from hb.config import settings
from hb.db.models import Listing, OpenHouse, Property, utcnow_iso
from hb.db.upsert import upsert
from hb.open_houses.sources.base import BBox, OpenHouseRecord
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)


BBOX_MARGIN_DEG = 0.005  # ~500 m around the outermost stored home


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class _Active:
    """The active listings a slot can attach to, and each city's bbox."""

    def __init__(self, session) -> None:
        self.by_source_id: dict[tuple[str, str], str] = {}
        self.by_mls: dict[tuple[str, str], str] = {}
        points: dict[str, list[tuple[float, float]]] = {}
        for lid, src, sid, raw, city, zip5, lat, lon in session.execute(
            select(Listing.id, Listing.source, Listing.source_listing_id, Listing.raw,
                   Property.city, Property.zip, Property.lat, Property.lon)
            .join(Property, Listing.property_id == Property.id)
            .where(Listing.status == "active")
        ).all():
            self.by_source_id[(src, sid)] = lid
            mls_id = str((raw or {}).get("mls_id") or "").strip()
            if mls_id:
                self.by_mls[(mls_id, zip5)] = lid
            if city and lat is not None and lon is not None:
                points.setdefault(city, []).append((lon, lat))
        self.bboxes: dict[str, BBox] = {
            city: (min(p[0] for p in pts) - BBOX_MARGIN_DEG, min(p[1] for p in pts) - BBOX_MARGIN_DEG,
                   max(p[0] for p in pts) + BBOX_MARGIN_DEG, max(p[1] for p in pts) + BBOX_MARGIN_DEG)
            for city, pts in points.items()
        }

    def match(self, rec: OpenHouseRecord) -> str | None:
        if rec.listing_source and rec.source_listing_id:
            return self.by_source_id.get((rec.listing_source, rec.source_listing_id))
        if rec.mls_id:
            return self.by_mls.get((rec.mls_id, rec.zip or ""))
        return None


def _sync_source(runner: JobRunner, source, active: _Active,
                 seen: set[tuple[str, str]], now_iso: str) -> None:
    session = runner.session
    unmatched = 0
    for city in settings.target_cities:
        with runner.item(f"{source.name}/{city}"):
            for rec in source.fetch(city, active.bboxes.get(city)):
                listing_id = active.match(rec)
                if listing_id is None:
                    unmatched += 1
                    continue
                start = _iso(rec.start_at)
                if (listing_id, start) in seen:
                    # an earlier source (or city) already wrote this slot
                    session.execute(update(OpenHouse).where(
                        OpenHouse.listing_id == listing_id, OpenHouse.start_at == start,
                    ).values(last_seen=now_iso))
                    continue
                seen.add((listing_id, start))
                row, changed = upsert(session, OpenHouse, {
                    "listing_id": listing_id, "source": source.name, "start_at": start,
                    "end_at": _iso(rec.end_at), "description": rec.description,
                    "href": rec.href, "methods": list(rec.methods), "cancelled_at": None,
                }, ["listing_id", "start_at"])
                row.last_seen = now_iso
                if changed:
                    runner.items_upserted += 1
            session.commit()

    if unmatched:
        log.info("open-houses %s: %d slot(s) with no stored active listing",
                 source.name, unmatched)


def _sweep(session, seen: set[tuple[str, str]], now_iso: str) -> None:
    stale, cancelled = [], []
    for oh_id, listing_id, start, scheduled_at, cancelled_at in session.execute(
        select(OpenHouse.id, OpenHouse.listing_id, OpenHouse.start_at,
               OpenHouse.scheduled_at, OpenHouse.cancelled_at)
        .where(OpenHouse.start_at > now_iso)
    ).all():
        if (listing_id, start) in seen:
            continue
        if scheduled_at is None:
            stale.append(oh_id)
        elif cancelled_at is None:
            cancelled.append(oh_id)
    if stale:
        session.execute(delete(OpenHouse).where(OpenHouse.id.in_(stale)))
    if cancelled:
        session.execute(update(OpenHouse).where(OpenHouse.id.in_(cancelled))
                        .values(cancelled_at=now_iso))
    session.commit()


def run(engine: Engine | None = None) -> str:
    # deferred: the realtor source reuses listing-scan's id helper, and
    # hb.pipelines imports this module while it is still initialising
    from hb.open_houses.sources import enabled_sources

    with JobRunner("open-houses", engine) as runner:
        now_iso = utcnow_iso()
        active = _Active(runner.session)
        seen: set[tuple[str, str]] = set()
        for source in enabled_sources():
            _sync_source(runner, source, active, seen, now_iso)
        if runner.errors:
            log.warning("open-houses: a fetch failed — skipping the cancellation sweep")
        else:
            _sweep(runner.session, seen, now_iso)
    return runner.status
