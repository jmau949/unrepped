"""price_history — Realtor.com sale/listing history for a property.

homeharvest fetches property data from Realtor's GraphQL but drops the
`property_history` node (its detail query is disabled upstream). This module
issues a minimal `GetHomeDetails` query to the same frontdoor endpoint (browser
headers, no auth token — the exact path the working scan uses) to get the full
Sold / Listed / Price-changed timeline, resolving the address to Realtor's
`mpr_id` first. It's scraping, so it degrades to [] on any failure — never
raises to the caller. `fetch_price_history` is the seam tests monkeypatch.
"""

import logging
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.engine import make_session
from hb.db.models import Listing, Property, Sale, utcnow_iso
from hb.pipelines import realtor_gql
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

_DETAIL_QUERY = (
    "query GetHomeDetails($property_id: ID!) { "
    "home(property_id: $property_id) { property_history { date event_name price } } }"
)


def _history_for(mpr_id: str) -> list[dict]:
    j = realtor_gql.post(_DETAIL_QUERY, {"property_id": mpr_id}, "GetHomeDetails")
    return (((j.get("data") or {}).get("home") or {}).get("property_history")) or []


def _resolve_mpr_id(address: str) -> str | None:
    """Address -> Realtor property (mpr) id via the search-suggestions query."""
    return realtor_gql.resolve_mpr_id(address)


def _parse_history(raw: list[dict]) -> list[dict]:
    """Realtor property_history rows -> deduped [{date, event, price}], newest first."""
    seen: set = set()
    out: list[dict] = []
    for h in raw or []:
        date, event, price = h.get("date"), h.get("event_name"), h.get("price")
        if not date or not event:
            continue
        key = (date, event, price)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": date[:10], "event": event,
                    "price": int(price) if price is not None else None})
    out.sort(key=lambda e: e["date"], reverse=True)
    return out


def fetch_price_history(address: str, mpr_id: str | None = None) -> list[dict]:
    """Realtor sale/listing history for a property: [{date, event, price}] newest
    first. Prefers the given mpr_id (the scan-stored Realtor id — one call, no
    search); if that yields nothing (e.g. a stale/wrong id), falls back to
    resolving the address. Returns [] on any failure — scraping, degrades
    gracefully."""
    try:
        raw = _history_for(mpr_id) if mpr_id else []
        if not raw:
            resolved = _resolve_mpr_id(address)
            if resolved and resolved != mpr_id:
                raw = _history_for(resolved)
    except Exception as exc:  # noqa: BLE001 — scraping; degrade to empty, never raise
        log.warning("price history fetch failed for %r: %s", address, exc)
        return []
    return _parse_history(raw)


# --- population: store price history on properties (run by the scrapes) ------

def _needs_refresh(prop: Property, max_age_days: int = 7) -> bool:
    ts = prop.price_history_fetched_at
    if not ts:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(ts) > timedelta(days=max_age_days)
    except (TypeError, ValueError):
        return True


def _mpr_id(prop: Property) -> str | None:
    return realtor_gql.mpr_id_for(prop)


def _address(prop: Property) -> str:
    street = prop.street or prop.address_norm
    return f"{street}, {prop.city or ''}, {prop.state} {prop.zip}".replace("  ", " ")


def refresh_one(session: Session, prop: Property) -> bool:
    """Fetch + cache a property's Realtor price history when stale/missing.
    Commits per property (persists progress, releases the write lock quickly).
    Fully isolated — any error (locked DB, fetch failure, expired session) is
    logged, rolled back, and swallowed so one property can never abort a batch.
    Returns True if it (re)fetched and committed."""
    try:
        if not _needs_refresh(prop):
            return False
        prop.price_history = fetch_price_history(_address(prop), _mpr_id(prop))
        prop.price_history_fetched_at = utcnow_iso()
        session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — never abort the batch on one property
        log.warning("price-history refresh failed for %s: %s", getattr(prop, "id", "?"), exc)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def _backfill_candidates(session: Session) -> list[Property]:
    """Default backfill scope: every property that is either current inventory or
    a comp. The comp half matters most — `sale_history` replays these timelines
    onto `sales` to recover the price cuts and CDOM the scan was too young to
    observe, and comps are by definition sold, so an inventory-only scope leaves
    the model exactly as blind as before.

    Never-fetched properties come first so an interrupted or `--limit`-ed run
    always makes forward progress instead of re-walking the same head.
    """
    return session.execute(
        select(Property)
        .where(
            Property.id.in_(
                select(Listing.property_id).where(Listing.status.in_(("active", "pending")))
            )
            | Property.id.in_(select(Sale.property_id))
        )
        .order_by(
            Property.price_history_fetched_at.is_(None).desc(),
            Property.price_history_fetched_at,
        )
    ).scalars().all()


def refresh_many(session: Session, property_ids=None, limit: int | None = None) -> int:
    """Refresh Realtor price history for the given properties (or the full
    backfill scope when None). `limit` caps external fetches so a long backfill
    can be run in resumable chunks. Rate-limited between external calls; returns
    the count refreshed. Plain function so the scan can call it inline
    (cf. enrich.enrich_tracked)."""
    if property_ids is None:
        props = _backfill_candidates(session)
    else:
        props = [p for pid in property_ids if (p := session.get(Property, pid)) is not None]
    n = 0
    for prop in props:
        if limit is not None and n >= limit:
            log.info("price-history: stopping at limit %d", limit)
            break
        if not _mpr_id(prop):
            continue
        if refresh_one(session, prop):
            n += 1
            time.sleep(random.uniform(1.0, 1.5))  # polite between Realtor calls
    return n


def run(engine=None, limit: int | None = None) -> str:
    """Standalone backfill (`hb pipeline price-history [--limit N]`): refresh
    price history across current inventory + the comp pool, then replay the
    refreshed timelines onto `sales` so the fetch and the derivation it exists to
    feed never drift apart. A full pass is thousands of ~1 s scrapes — use
    `--limit` to run it in resumable chunks."""
    with JobRunner("price-history", engine) as runner:
        session = make_session(runner.engine)
        try:
            with runner.item("realtor"):
                runner.items_upserted = refresh_many(session, limit=limit)
            with runner.item("derive"):
                from hb.pipelines import sale_history
                sale_history.apply_all(session)
        finally:
            session.close()
    return runner.status
