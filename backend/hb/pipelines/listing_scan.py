"""listing-scan pipeline — docs/05-pipelines.md §4.

Daily HomeHarvest scan per target city (for_sale / pending / sold, single
family), entity resolution, diff-only event emission with one shared
observed_at, delist detection by absence, sold→sales comps capture, and
idempotent photo download. Ingests ALL prices (the target band never filters
ingestion — docs/05 §4 price-band note).
"""

import logging
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import (Listing, ListingEvent, ListingGroup, PipelineRun, Property, Sale,
                          utcnow_iso)
from hb.db.upsert import upsert
from hb.pipelines import listing_text
from hb.pipelines.base import JobRunner
from hb.pipelines.resolve import resolve

log = logging.getLogger(__name__)

SCAN_TYPES = [("for_sale", None), ("pending", 45), ("sold", 30)]

# HomeHarvest status -> our listing status
STATUS_MAP = {"FOR_SALE": "active", "PENDING": "pending", "CONTINGENT": "pending", "SOLD": "sold"}


def fetch_homeharvest(city: str, listing_type: str, past_days: int | None) -> pd.DataFrame:
    """Seam for tests. Verified HomeHarvest 0.8.18 fields: docs/03 §2.1."""
    from homeharvest import scrape_property

    kwargs = {"location": f"{city}, {settings.geo.state}", "listing_type": listing_type,
              "property_type": ["single_family"]}
    if past_days:
        kwargs["past_days"] = past_days
    return scrape_property(**kwargs)


def fetch_photo(url: str) -> bytes:
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _val(row, key):
    v = row.get(key)
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v) else v


def _date_part(v) -> str | None:
    if v is None:
        return None
    return str(v)[:10]


def _resolve_record(row: dict) -> dict:
    full_baths = _val(row, "full_baths") or 0
    half_baths = _val(row, "half_baths") or 0
    baths = float(full_baths) + 0.5 * float(half_baths) if (full_baths or half_baths) else None
    return {
        "street": _val(row, "full_street_line") or _val(row, "street") or "",
        "unit": _val(row, "unit") or "",
        "city": _val(row, "city"),
        "state": _val(row, "state") or settings.geo.state,
        "zip": str(_val(row, "zip_code") or ""),
        "lat": _val(row, "latitude"),
        "lon": _val(row, "longitude"),
        "beds": int(_val(row, "beds")) if _val(row, "beds") is not None else None,
        "baths": baths,
        "sqft": int(_val(row, "sqft")) if _val(row, "sqft") is not None else None,
        "lot_sqft": int(_val(row, "lot_sqft")) if _val(row, "lot_sqft") is not None else None,
        "year_built": int(_val(row, "year_built")) if _val(row, "year_built") is not None else None,
        "property_type": "single_family",
    }


def _source_listing_id(row: dict) -> str | None:
    for key in ("listing_id", "mls_id", "property_id"):
        v = _val(row, key)
        if v is not None:
            return str(v)
    return None


# The photo URL blobs are already stored first-class in `photo_urls`; everything
# else in the source record is kept verbatim (docs/05 §4.2) so fields we don't
# model yet — mls_status contingency detail, hoa_fee, estimated_value,
# price_per_sqft, the listing description — survive ingest instead of being
# discarded at the door. The listing side lives here too: agent_name/email/phones,
# office_*, broker_name, mls/mls_id are read back by `hb/listing_contact.py`.
_RAW_DROP = {"primary_photo", "alt_photos"}


def _json_scalar(value):
    """pandas/numpy value -> JSON-safe Python value.

    NaN/NaT -> None; nested lists/dicts (the advertiser phone lists) are recursed
    rather than stringified, so `agent_phones` lands as a JSON array the reader
    can walk.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _json_scalar(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_scalar(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return str(value)  # array-like: keep a readable trace rather than crash
    if isinstance(value, (bool, int, float, str)):
        return value
    item = getattr(value, "item", None)  # numpy scalar -> Python scalar
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def _raw_payload(row: dict) -> dict:
    return {k: _json_scalar(v) for k, v in row.items() if k not in _RAW_DROP}


class ScanStats:
    def __init__(self) -> None:
        self.events = 0
        self.upserted = 0
        self.touched_properties: set[str] = set()
        self.seen_listing_ids: set[str] = set()  # drives delist-by-absence
        self.photo_jobs: list[tuple[str, str, list[str]]] = []  # (listing_id, property_id, urls)
        self.new_sale_ids: set[str] = set()  # sales created this run -> new_comp_sold
        self.conditions_tagged = 0  # condition inferred from remarks
        self.offer_dates_found = 0  # offer_due_at parsed from remarks
        self.photos_blocked = 0  # photos not fetched because the CDN refused us (403)


def _emit(session: Session, listing_id: str, event_type: str, old, new, observed_at: str,
          stats: ScanStats) -> None:
    session.add(ListingEvent(
        listing_id=listing_id, event_type=event_type,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        observed_at=observed_at,
    ))
    stats.events += 1


def _had_price_cut(session: Session, listing_id: str) -> bool:
    events = session.execute(
        select(ListingEvent).where(
            ListingEvent.listing_id == listing_id,
            ListingEvent.event_type == "price_change",
        )
    ).scalars().all()
    return any(
        e.old_value and e.new_value and int(e.new_value) < int(e.old_value) for e in events
    )


def _photo_urls(row: dict) -> list[str]:
    """Primary + full gallery image URLs (homeharvest returns `alt_photos` as a
    comma-separated string), primary first, deduped."""
    urls: list[str] = []
    primary = _val(row, "primary_photo")
    if primary:
        urls.append(str(primary))
    alt = _val(row, "alt_photos")
    if alt:
        urls.extend(u.strip() for u in str(alt).split(",") if u.strip())
    seen: set = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def process_row(session: Session, row: dict, observed_at: str, stats: ScanStats) -> None:
    source_id = _source_listing_id(row)
    zip5 = str(_val(row, "zip_code") or "")
    if not source_id or not zip5:
        raise ValueError(f"record missing listing id or zip: {row.get('street')}")

    status = STATUS_MAP.get(str(_val(row, "status") or ""), None)
    if status is None:
        mls_status = str(_val(row, "mls_status") or "").lower()
        status = "pending" if "conting" in mls_status or "pending" in mls_status else "active"

    record = _resolve_record(row)
    # a home on the market is described by its live listing: beds/baths/sqft
    # from a for-sale or pending record revise the property (docs/05 §5); a
    # sold record is history and only fills gaps
    property_id, _ = resolve(session, record, "realtor",
                             str(_val(row, "property_id") or source_id),
                             authoritative=status != "sold")
    stats.touched_properties.add(property_id)

    # signals that exist only in the public remarks (docs/05 §4.7)
    text = _val(row, "text")
    prop = session.get(Property, property_id)
    if prop is not None and listing_text.apply_condition(prop, text):
        stats.conditions_tagged += 1

    list_price = _val(row, "list_price")
    list_price = int(list_price) if list_price is not None else None
    sold_price = _val(row, "sold_price") or _val(row, "last_sold_price")
    sold_price = int(sold_price) if sold_price is not None else None
    photo_urls = _photo_urls(row)

    existing = session.execute(
        select(Listing).where(Listing.source == "realtor",
                              Listing.source_listing_id == source_id)
    ).scalar_one_or_none()

    if existing is None:
        listing = Listing(
            property_id=property_id,
            source="realtor",
            source_listing_id=source_id,
            url=_val(row, "property_url"),
            status=status,
            list_price=list_price,
            original_list_price=list_price,
            list_date=_date_part(_val(row, "list_date")),
            pending_date=_date_part(_val(row, "pending_date")),
            # last_sold_date/price on a FOR_SALE record is the property's
            # PREVIOUS sale (often decades old) — only a sold record's dates
            # belong to this episode (set in the sold block below)
            sold_date=_date_part(_val(row, "last_sold_date")) if status == "sold" else None,
            sold_price=sold_price if status == "sold" else None,
            dom_source=int(_val(row, "days_on_mls")) if _val(row, "days_on_mls") is not None else None,
            photo_urls=photo_urls,
            raw=_raw_payload(row),
            first_seen=observed_at,
            last_seen=observed_at,
        )
        session.add(listing)
        session.flush()
        stats.upserted += 1
        _emit(session, listing.id, "new", None, list_price, observed_at, stats)
    else:
        listing = existing
        if list_price is not None and listing.list_price != list_price:
            _emit(session, listing.id, "price_change", listing.list_price, list_price,
                  observed_at, stats)
            listing.list_price = list_price
            stats.upserted += 1
        if listing.original_list_price is None and list_price is not None:
            listing.original_list_price = list_price
        if status != listing.status:
            event = {
                "pending": "pending",
                "sold": "sold",
                "active": "back_on_market" if listing.status == "pending" else "status_change",
            }.get(status, "status_change")
            _emit(session, listing.id, event, listing.status, status, observed_at, stats)
            listing.status = status
            stats.upserted += 1
            if status == "sold":
                # closing makes the row unread again (docs/08 §2b): the sale
                # price is the new thing to read, so a view earned while the
                # home was on the market does not count. Gated on the
                # transition, never on `status == "sold"` — the sold scan
                # re-pulls a rolling 30-day window, so a state-triggered clear
                # would wipe the stamp daily for a month.
                listing.viewed_at = None
        if status == "pending":
            listing.pending_date = listing.pending_date or _date_part(_val(row, "pending_date"))
        merged = list(listing.photo_urls or [])
        for u in photo_urls:
            if u not in merged:
                merged.append(u)
        if merged != (listing.photo_urls or []):
            listing.photo_urls = merged
        listing.last_seen = observed_at
        if listing.dom_source is None and _val(row, "days_on_mls") is not None:
            listing.dom_source = int(_val(row, "days_on_mls"))
        # source snapshot refresh — audit metadata, not a tracked field change,
        # so it never counts toward items_upserted (docs/05 §1 idempotency)
        raw = _raw_payload(row)
        if raw != (listing.raw or {}):
            listing.raw = raw

    # offer date from the remarks — fill only, never overwrite: a value already
    # here was either parsed earlier or set by hand in the UI, and both beat a
    # re-parse of prose the agent may have since edited
    if listing.offer_due_at is None:
        due = listing_text.parse_offer_due(text, listing.list_date)
        if due:
            listing.offer_due_at = due
            stats.offer_dates_found += 1

    # sold records feed the comps DB (docs/05 §4.3)
    if status == "sold" and sold_price:
        sale_date = _date_part(_val(row, "last_sold_date")) or date.today().isoformat()
        listing.sold_price = sold_price
        listing.sold_date = sale_date
        original = listing.original_list_price or list_price
        sale_row, changed = upsert(
            session, Sale,
            {
                "property_id": property_id,
                "listing_id": listing.id,
                "sale_date": sale_date,
                "sale_price": sold_price,
                "list_price_at_sale": list_price,
                "original_list_price": original,
                "sp_lp": round(sold_price / original, 4) if original else None,
                "dom": listing.dom_source,
                "had_price_cut": _had_price_cut(session, listing.id),
                "source": "realtor_sold_scan",
            },
            ["property_id", "sale_date"],
        )
        if changed:
            stats.upserted += 1
            stats.new_sale_ids.add(sale_row.id)

    stats.seen_listing_ids.add(listing.id)
    if settings.save_photos and listing.photo_urls:
        stats.photo_jobs.append((listing.id, property_id, list(listing.photo_urls)))


def _detect_delistings(session: Session, city: str, observed_at: str, stats: ScanStats) -> None:
    """Active realtor listings in `city` not seen by today's full for_sale scan
    (and not pending/sold today) are delisted — docs/05 §4.4. Absence is tracked
    by the run's seen-ID set (timestamps collide at second granularity)."""
    candidates = session.execute(
        select(Listing)
        .join(Property, Listing.property_id == Property.id)
        .where(
            Listing.source == "realtor",
            Listing.status == "active",
            Property.city == city,
        )
    ).scalars().all()
    stale = [c for c in candidates if c.id not in stats.seen_listing_ids]
    for listing in stale:
        _emit(session, listing.id, "delisted", "active", "delisted", observed_at, stats)
        listing.status = "delisted"
        listing.delist_date = date.today().isoformat()
        stats.upserted += 1


def _sync_sale_cdom(session: Session, property_ids: set[str]) -> int:
    """Copy stitched cumulative DOM from the listing group onto the sale row.

    `relist.stitch` writes CDOM to `listing_groups` only, but the overbid model's
    stale routing (docs/06 §5.2) and the comp grid read `sales.cumulative_dom`.
    Must run AFTER stitching. Idempotent: writes only on a value change.
    """
    updated = 0
    for property_id in sorted(property_ids):
        sales = session.execute(
            select(Sale).where(Sale.property_id == property_id,
                               Sale.listing_id.is_not(None))
        ).scalars().all()
        for sale in sales:
            listing = session.get(Listing, sale.listing_id)
            if listing is None or listing.listing_group_id is None:
                continue
            group = session.get(ListingGroup, listing.listing_group_id)
            if group is None or group.cumulative_dom is None:
                continue
            if sale.cumulative_dom != group.cumulative_dom:
                sale.cumulative_dom = group.cumulative_dom
                updated += 1
    return updated


PHOTO_WORKERS = 4  # parallel fetches from the image CDN: what a browser does for one gallery
PHOTO_PROGRESS_EVERY = 200  # a progress line this often; a first run can be 15,000+ files
PHOTO_RATE_GUESS = 5.0  # files/s that PHOTO_WORKERS and the per-file pause give: the
                        # up-front estimate, replaced by the measured rate as it goes
PHOTO_BACKOFF_S = 5.0  # first pause after the CDN answers 429/503; doubles, capped at 60 s
PHOTO_RETRIES = 3
PHOTO_RETRY_PAUSE_S = 2.0  # one worker's pause after its connection dropped or a 5xx; doubles
PHOTO_BLOCK_AFTER = 8  # 403s in a row, no success between: the CDN is refusing us, not a file
PHOTO_BLOCK_PAUSE_S = 60.0  # every worker's pause then; doubles per round
PHOTO_BLOCK_ROUNDS = 3  # refused again after this many pauses: the photos stop for this run


@dataclass(frozen=True)
class _PhotoJob:
    listing_id: str
    property_id: str
    url: str
    dest: Path
    rel: str  # path recorded in listings.photo_paths, relative to data_dir


class _Throttle:
    """Shared by the photo workers: a 429/503 from the CDN pauses every one of
    them, for longer each time it repeats; the next success resets the pause.

    A 403 is different. One file can be forbidden on its own (skipped; the next
    scan tries it again), but the CDN's rate limit answers 403 too, to every
    request: PHOTO_BLOCK_AFTER of them in a row with no success between is
    that, and every worker pauses PHOTO_BLOCK_PAUSE_S, doubling per round.
    Refused again after PHOTO_BLOCK_ROUNDS pauses, the tail stops for this run
    (`stopped`) rather than log a 403 for every queued file and prolong the
    block."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pause_until = 0.0
        self._backoff = PHOTO_BACKOFF_S
        self._refusals = 0  # 403s in a row since the last success
        self._rounds = 0  # pauses taken for 403s since the last success
        self.stopped = threading.Event()

    def wait(self) -> None:
        delay = self._pause_until - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def slow_down(self) -> float:
        with self._lock:
            pause = self._backoff
            self._backoff = min(self._backoff * 2, 60.0)
            self._pause_until = max(self._pause_until, time.monotonic() + pause)
        return pause

    def refused(self) -> tuple[str, float]:
        """A 403: ("skip", 0) for a lone one; ("pause", seconds) when this call
        started a pause for everyone; ("wait", 0) when one is already running,
        so the file is retried after it; ("stop", 0) to end the tail."""
        with self._lock:
            now = time.monotonic()
            if now < self._pause_until:
                return "wait", 0.0
            self._refusals += 1
            if self._rounds == 0 and self._refusals < PHOTO_BLOCK_AFTER:
                return "skip", 0.0
            if self._rounds >= PHOTO_BLOCK_ROUNDS:
                self.stopped.set()
                return "stop", 0.0
            pause = PHOTO_BLOCK_PAUSE_S * 2 ** self._rounds
            self._rounds += 1
            self._refusals = 0
            self._pause_until = now + pause
            return "pause", pause

    def ok(self) -> None:
        with self._lock:
            self._backoff = PHOTO_BACKOFF_S
            self._refusals = 0
            self._rounds = 0


def _photo_dest(listing_id: str, property_id: str, n: int, url: str) -> Path:
    ext = ".jpg" if ".jpg" in url.lower() else ".webp" if ".webp" in url.lower() else ".jpg"
    return settings.photos_dir / property_id / f"{listing_id}-{n}{ext}"


def _hms(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60:02d}m"
    return f"{minutes}m" if minutes else f"{int(seconds)}s"


def _transient(exc: Exception) -> bool:
    """A failure worth another try in this run: the connection dropped or timed
    out, or the server erred (5xx). A 4xx means the file is gone; not retried."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _fetch_one(job: _PhotoJob, throttle: _Throttle) -> bool:
    """One worker's share: fetch and write a single photo; True when a file was
    written. Only files and HTTP here — the session stays on the main thread.

    Two kinds of retry, PHOTO_RETRIES each: a 429/503 is the CDN telling every
    worker to back off (the shared throttle); a dropped connection, a timeout
    or another 5xx is this one request's bad luck, so only this worker pauses
    (PHOTO_RETRY_PAUSE_S, doubling) and tries again. A 403 is the throttle's
    call (`_Throttle.refused`): a lone one skips the file, a run of them pauses
    everyone, a persistent one stops the tail."""
    for attempt in range(PHOTO_RETRIES + 1):
        if throttle.stopped.is_set():
            return False
        throttle.wait()
        try:
            content = fetch_photo(job.url)
        except Exception as exc:  # noqa: BLE001 — per-item tolerance
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if attempt < PHOTO_RETRIES and status in (429, 503):
                pause = throttle.slow_down()
                log.info("listing-scan: the photo CDN asked us to slow down (%d); pausing %.0f s",
                         status, pause)
                continue
            if status == 403:
                verdict, pause = throttle.refused()
                if verdict == "pause":
                    log.warning("listing-scan: the photo CDN is refusing requests (403); "
                                "pausing %.0f s before trying again", pause)
                if verdict in ("pause", "wait"):
                    continue
                if verdict == "stop":
                    return False
                # "skip": a lone 403 is that file, not us; the next scan tries it again
            if attempt < PHOTO_RETRIES and _transient(exc):
                pause = PHOTO_RETRY_PAUSE_S * 2 ** attempt
                log.info("listing-scan: photo fetch failed (%s), retrying in %.0f s: %s",
                         status or type(exc).__name__, pause, job.url)
                time.sleep(pause)
                continue
            log.warning("photo download failed (%s): %s", job.url, exc)
            return False
        throttle.ok()
        job.dest.parent.mkdir(parents=True, exist_ok=True)
        job.dest.write_bytes(content)
        time.sleep(random.uniform(0.3, 0.6))  # per connection: a browser loading a gallery
        return True
    return False


def _download_photos(stats: ScanStats, session: Session) -> int:
    """Download the full gallery (primary + alt_photos) per listing, indexed
    -0..-N. Idempotent (docs/05 §4.6): a file already on disk is never re-fetched
    (but is still recorded in photo_paths).

    The photos come from the listing site's image CDN, not its pages, so this is
    the one place the scan is not sequential (docs/03 §5): PHOTO_WORKERS threads
    fetch in parallel, each pausing after every file, and a 429/503 pauses them
    all. Still the slow part of a first run, so it says up front how many files
    are coming and logs progress with the time left."""
    todo: list[_PhotoJob] = []
    for listing_id, property_id, urls in stats.photo_jobs:
        for n, url in enumerate(urls):
            dest = _photo_dest(listing_id, property_id, n, url)
            todo.append(_PhotoJob(listing_id, property_id, url, dest,
                                  str(dest.relative_to(settings.data_dir))))
    pending = [job for job in todo if not job.dest.exists()]
    if pending:
        log.info("listing-scan: %d photos to download for %d listings, %d at a time: roughly %s. "
                 "Progress prints every %d photos; `make serve` in another terminal opens "
                 "the app meanwhile", len(pending), len(stats.photo_jobs), PHOTO_WORKERS,
                 _hms(len(pending) / PHOTO_RATE_GUESS), PHOTO_PROGRESS_EVERY)

    started = time.monotonic()
    saved = 0
    throttle = _Throttle()
    pool = ThreadPoolExecutor(max_workers=PHOTO_WORKERS, thread_name_prefix="photo")
    try:
        for done in as_completed([pool.submit(_fetch_one, job, throttle) for job in pending]):
            if done.result():
                saved += 1
                if saved % PHOTO_PROGRESS_EVERY == 0:
                    rate = saved / max(time.monotonic() - started, 1e-9)
                    log.info("listing-scan: photos %d/%d saved, about %s left",
                             saved, len(pending), _hms((len(pending) - saved) / rate))
            if throttle.stopped.is_set():
                break
    finally:
        # Ctrl+C must stop here, not drain 15,000 queued downloads first
        pool.shutdown(wait=False, cancel_futures=True)
    if throttle.stopped.is_set():
        stats.photos_blocked = len(pending) - saved
        log.warning("listing-scan: the photo CDN kept refusing us (403) through %d pauses: "
                    "stopping the photos for this run, %d of %d saved. The next scan "
                    "fetches the rest", PHOTO_BLOCK_ROUNDS, saved, len(pending))
    elif pending:
        log.info("listing-scan: photos done: %d saved in %s", saved,
                 _hms(time.monotonic() - started))

    # bookkeeping on the main thread: every file now on disk, in gallery order,
    # recorded on its listing (files that already existed included)
    on_disk: dict[str, list[str]] = defaultdict(list)
    for job in todo:
        if job.dest.exists():
            on_disk[job.listing_id].append(job.rel)
    for listing_id, rels in on_disk.items():
        listing = session.get(Listing, listing_id)
        if listing is None:
            continue
        paths = list(listing.photo_paths or [])
        paths += [rel for rel in rels if rel not in paths]
        if paths != (listing.photo_paths or []):
            listing.photo_paths = paths
    return saved


def _first_scan(session: Session) -> bool:
    """True until a listing-scan has completed (ok or partial) in this database:
    a new user's first scan is the long one, and it should say so, once."""
    done = session.execute(
        select(PipelineRun).where(PipelineRun.job == "listing-scan",
                                  PipelineRun.status.in_(("ok", "partial"))).limit(1)
    ).scalars().first()
    return done is None


def run(engine=None) -> str:
    with JobRunner("listing-scan", engine) as runner:
        observed_at = utcnow_iso()
        stats = ScanStats()
        session = make_session(runner.engine)
        try:
            cities = list(settings.target_cities)
            first = _first_scan(session)
            if first:
                log.info("listing-scan: first scan of %s (%s). This is the slow one: about an "
                         "hour per 500 homes for sale, mostly the photos. Progress prints as "
                         "it goes", settings.geo.name, ", ".join(cities))
            else:
                log.info("listing-scan: %s", ", ".join(cities))
            for n, city in enumerate(cities, 1):
                city_for_sale_ok = False
                for listing_type, past_days in SCAN_TYPES:
                    log.info("listing-scan: %s (%d/%d): %s", city, n, len(cities),
                             listing_type.replace("_", " "))
                    with runner.item(f"{city}/{listing_type}"):
                        df = fetch_homeharvest(city, listing_type, past_days)
                        for _, row in df.iterrows():
                            process_row(session, row.to_dict(), observed_at, stats)
                        if listing_type == "for_sale":
                            city_for_sale_ok = True
                        session.commit()
                    time.sleep(random.uniform(2, 5))
                if city_for_sale_ok:
                    _detect_delistings(session, city, observed_at, stats)
                    session.commit()

            from hb.alerts import rules
            from hb.pipelines import relist

            stats.events += relist.stitch(session, stats.touched_properties, observed_at)
            _sync_sale_cdom(session, stats.touched_properties)
            session.commit()

            # daily auto-enrich of tracked listings (docs/05 §7) — external
            # calls, fully guarded so a failure never breaks the scan. Runs
            # before alert evaluation so its RentCast comps feed new_comp_sold.
            try:
                from hb.pipelines import enrich
                enriched = enrich.enrich_tracked(session, stats.new_sale_ids)
                if enriched:
                    log.info("auto-enriched %d tracked properties", enriched)
            except Exception as exc:  # noqa: BLE001
                log.warning("auto-enrich failed: %s", exc)

            # evaluate alerts BEFORE the long photo tail: a crash mid-download
            # must not permanently skip this run's event alerts (each run only
            # evaluates its own observed_at). Not on a first scan: every home is
            # new to the database, not to the buyer, and a fresh install must
            # not open with an alert for each one (docs/09 §1).
            if first:
                log.info("listing-scan: first scan: no alerts; they start with the next scan")
            else:
                run_events = session.execute(
                    select(ListingEvent).where(ListingEvent.observed_at == observed_at)
                ).scalars().all()
                rules.evaluate(session, run_events, observed_at,
                               new_sale_ids=stats.new_sale_ids)
                session.commit()

            # refresh Realtor price history for the properties we just scraped,
            # BEFORE the long photo tail so the timeline populates sooner
            # (external calls, fully guarded — never breaks the scan). Watched
            # homes ride along whether or not the scan saw them: off the market,
            # that history is the only place a later sale shows up (docs/05 §11).
            # refresh_one's 7-day staleness gate makes this weekly, not daily.
            try:
                from hb import watchlist
                from hb.pipelines import price_history, sale_history
                price_history.refresh_many(
                    session, stats.touched_properties | watchlist.watched_property_ids(session))
                # replay the refreshed timelines onto sales: fills the price-cut
                # history and CDOM the scan itself was too young to observe
                sale_history.apply_all(session, stats.touched_properties)
            except Exception as exc:  # noqa: BLE001
                log.warning("price-history refresh failed: %s", exc)

            saved = _download_photos(stats, session)
            session.commit()
            if stats.photos_blocked:
                runner.errors.append(f"photos: the CDN refused requests (403); "
                                     f"{stats.photos_blocked} left for the next scan")

            runner.items_upserted = stats.upserted
            runner.events_emitted = stats.events
            log.info(
                "listing-scan: %d field-changes, %d events, %d properties touched, "
                "%d photos, %d conditions tagged, %d offer dates",
                stats.upserted, stats.events, len(stats.touched_properties), saved,
                stats.conditions_tagged, stats.offer_dates_found,
            )
        finally:
            session.close()

    # open houses attach to the active listings this run just stored
    # (docs/05 §4c) — its own pipeline_runs row; JobRunner suppresses its
    # failures, so it never fails the scan
    from hb.pipelines import open_houses
    open_houses.run(runner.engine)
    return runner.status
