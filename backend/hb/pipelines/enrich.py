"""enrich pipeline — on-demand + daily-for-tracked (docs/05-pipelines.md §7).

Three external AVMs, each isolated so one failure is a recorded miss and the run
continues:
1. **Realtor.com** (free, no key): home-value estimate + details (NULL-fill) +
   gallery photos via the frontdoor GraphQL →
   `avm_snapshots(source='realtor_estimate')`. (Replaced Redfin, whose stingray
   API now sits behind AWS WAF and 403s every request.)
2. **RentCast** (needs `RENTCAST_API_KEY`, budget-guarded): `/avm/value` →
   `avm_snapshots(source='rentcast')`. The comparables in the response are sale
   *listings* at their asking prices, so none of them is stored as a sale.
3. **Zestimate** (optional, behind `ZILLOW_WRAPPER_ENABLED` + `RAPIDAPI_KEY`).

Snapshots key on `(property_id, source, as_of=today)` so a same-day re-run is a
no-op (matrix D13). External calls go through `fetch_*` seams so tests never hit
the network.
"""

import logging
import random
import time
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import (
    AppSetting, AvmSnapshot, Listing, Property, TrackedListing, utcnow_iso,
)
from hb.db.upsert import upsert
from hb.pipelines import realtor_gql
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

ENRICH_STAGES = ("saved", "toured", "disclosures", "offer_prep", "offered")


# --- external seams (monkeypatched in tests) ---------------------------------

_ESTIMATE_QUERY = (
    "query GetHomeDetails($property_id: ID!) { home(property_id: $property_id) { "
    "description { beds baths_consolidated sqft lot_sqft year_built } "
    "primary_photo(https: true) { href } photos(https: true) { href } "
    "estimates { currentValues: current_values { source { type name } "
    "estimate estimateHigh: estimate_high estimateLow: estimate_low "
    "isBestHomeValue: isbest_homevalue } } } }"
)


def fetch_realtor_estimate(address: str, mpr_id: str | None = None) -> dict | None:
    """Realtor.com home-value estimate + details + photos via the frontdoor
    GraphQL (free, no key, no WAF). Prefers the scan-stored mpr id (one call);
    falls back to resolving the address. Returns
    ``{estimate, low, high, photo_urls, property:{...}}`` or None. Raises on
    transport error — the caller records a miss and continues.
    """
    mid = mpr_id or realtor_gql.resolve_mpr_id(address)
    if not mid:
        return None
    j = realtor_gql.post(_ESTIMATE_QUERY, {"property_id": mid}, "GetHomeDetails")
    home = ((j.get("data") or {}).get("home")) or {}
    cv = (home.get("estimates") or {}).get("currentValues") or []
    best = next((e for e in cv if e.get("isBestHomeValue")), cv[0] if cv else None)
    if not best or best.get("estimate") is None:
        return None
    desc = home.get("description") or {}
    baths = desc.get("baths_consolidated")  # string like "3.5"
    photos = [
        p["href"] for p in ([home.get("primary_photo")] + (home.get("photos") or []))
        if p and p.get("href")
    ]
    return {
        "estimate": int(best["estimate"]),
        "low": int(best["estimateLow"]) if best.get("estimateLow") is not None else None,
        "high": int(best["estimateHigh"]) if best.get("estimateHigh") is not None else None,
        "photo_urls": list(dict.fromkeys(photos)),  # dedup, keep order
        "property": {
            "beds": desc.get("beds"),
            "baths": float(baths) if baths not in (None, "") else None,
            "sqft": desc.get("sqft"),
            "lot_sqft": desc.get("lot_sqft"),
            "year_built": desc.get("year_built"),
        },
    }


def fetch_rentcast_avm(address: str) -> dict | None:
    """RentCast `/avm/value` (needs `RENTCAST_API_KEY`). Returns
    ``{value, low, high}``. Raises on error. The response's `comparables` are
    listings whose `price` is an asking price (and `removedDate` the day the
    listing came down, not a closing), so they are not read."""
    resp = httpx.get(
        "https://api.rentcast.io/v1/avm/value",
        params={"address": address},
        headers={"X-Api-Key": settings.rentcast_api_key, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"value": int(data["price"]), "low": data.get("priceRangeLow"),
            "high": data.get("priceRangeHigh")}


def fetch_zestimate(address: str) -> dict | None:
    """Zestimate via a RapidAPI Zillow wrapper (needs `RAPIDAPI_KEY`, gated by
    `ZILLOW_WRAPPER_ENABLED`). Returns ``{value, low, high}``. Raises on error."""
    resp = httpx.get(
        "https://zillow-com1.p.rapidapi.com/property",
        params={"address": address},
        headers={"X-RapidAPI-Key": settings.rapidapi_key,
                 "X-RapidAPI-Host": "zillow-com1.p.rapidapi.com"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    z = data.get("zestimate")
    if not z:
        return None
    # zestimateLow/HighPercent are PERCENTAGES (e.g. 5 = ±5%); AvmSnapshot.low/high
    # are dollar fields for every source — convert.
    low_pct, high_pct = data.get("zestimateLowPercent"), data.get("zestimateHighPercent")
    return {
        "value": int(z),
        "low": round(int(z) * (1 - float(low_pct) / 100)) if low_pct is not None else None,
        "high": round(int(z) * (1 + float(high_pct) / 100)) if high_pct is not None else None,
    }


def fetch_photo(url: str) -> bytes:
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


# --- RentCast budget guard ---------------------------------------------------

def _budget_state(session: Session) -> tuple[AppSetting | None, dict]:
    row = session.get(AppSetting, "rentcast_budget")
    month = date.today().strftime("%Y-%m")
    val = dict(row.value) if row and row.value else {}
    if val.get("month") != month:  # roll over at month boundary
        val = {"month": month, "calls": 0}
    return row, val


def rentcast_remaining(session: Session) -> int:
    _, val = _budget_state(session)
    return max(0, settings.rentcast_monthly_limit - val.get("calls", 0))


def rentcast_quota(session: Session) -> int | None:
    """Remaining RentCast calls this month for the UI, or None when no
    RENTCAST_API_KEY is set — then RentCast is unused and shown nowhere."""
    return rentcast_remaining(session) if settings.rentcast_api_key else None


def _spend_rentcast(session: Session) -> None:
    row, val = _budget_state(session)
    val["calls"] = val.get("calls", 0) + 1
    if row is None:
        session.add(AppSetting(key="rentcast_budget", value=val))
    else:
        row.value = val
        row.updated_at = utcnow_iso()


# --- helpers -----------------------------------------------------------------

def _address(prop: Property) -> str:
    street = prop.street or prop.address_norm
    return f"{street}, {prop.city or ''}, {prop.state} {prop.zip}".replace("  ", " ")


def _snapshot(session: Session, property_id: str, source: str, value: int,
              low: int | None, high: int | None, as_of: str) -> None:
    upsert(session, AvmSnapshot,
           {"property_id": property_id, "source": source, "value": value,
            "low": low, "high": high, "as_of": as_of},
           ["property_id", "source", "as_of"])


def _sleep() -> None:
    time.sleep(random.uniform(1.0, 1.5))  # ≥1s jittered between external calls


def _apply_realtor(session: Session, prop: Property, rf: dict, today: str,
                   photos: bool = True) -> int:
    saved = 0
    fillable = rf.get("property") or {}
    for field in ("beds", "baths", "sqft", "lot_sqft", "year_built"):
        if getattr(prop, field) is None and fillable.get(field) is not None:
            setattr(prop, field, fillable[field])
    listing = session.execute(
        select(Listing).where(Listing.property_id == prop.id)
        .order_by(Listing.first_seen.desc()).limit(1)
    ).scalar_one_or_none()
    key = listing.id if listing else prop.id
    if photos:
        saved = _download_gallery(session, prop, key, rf.get("photo_urls") or [], listing)
    if rf.get("estimate"):
        _snapshot(session, prop.id, "realtor_estimate", rf["estimate"],
                  rf.get("low"), rf.get("high"), today)
    return saved


def _download_gallery(session: Session, prop: Property, key: str,
                      urls: list[str], listing: Listing | None) -> int:
    """Idempotent gallery download (docs/05 §4.6): skip any file already on disk."""
    saved = 0
    paths = list(listing.photo_paths) if listing and listing.photo_paths else []
    for n, url in enumerate(urls):
        ext = ".jpg" if ".jpg" in url.lower() else ".webp" if ".webp" in url.lower() else ".jpg"
        dest = settings.photos_dir / prop.id / f"{key}-{n}{ext}"
        rel = str(dest.relative_to(settings.data_dir))
        if dest.exists():
            continue
        try:
            content = fetch_photo(url)
        except Exception as exc:  # noqa: BLE001 — per-photo tolerance
            log.warning("enrich photo failed (%s): %s", url, exc)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        saved += 1
        if listing is not None and rel not in paths:
            paths.append(rel)
        _sleep_photo()
    if listing is not None and paths != (listing.photo_paths or []):
        listing.photo_paths = paths
    return saved


def _sleep_photo() -> None:
    time.sleep(random.uniform(0.3, 0.6))


# --- per-property enrichment -------------------------------------------------

def metered_configured() -> bool:
    """True when a pay-per-call source (RentCast, the Zillow wrapper) is set up."""
    return bool(settings.rentcast_api_key
                or (settings.zillow_wrapper_enabled and settings.rapidapi_key))


def enrich_one(session: Session, prop: Property, errors: list[str],
               skips: list[str] | None = None,
               metered: bool = True, rentcast: bool = False) -> None:
    """Enrich a single property across all sources. Each source is isolated;
    real failures append to `errors` (recorded misses) and the next source runs.
    Config refusals (an optional source left unconfigured or over budget) are not
    failures — they go to `skips` when the caller provides one, so they never flip
    a run to ``failed``; otherwise they fall back to `errors`. ``metered=False``
    is the page-load path: the free Realtor.com estimate and details alone — no
    RentCast or Zillow call to spend, and no gallery download to wait on. RentCast
    is called only with ``rentcast=True`` — the buyer asking for that home by
    hand — because every call comes out of a small monthly allowance; no
    automatic pass (the scan's tracked homes, a page load) ever spends one."""
    address = _address(prop)
    today = date.today().isoformat()
    refusals = skips if skips is not None else errors

    try:
        rf = fetch_realtor_estimate(address, mpr_id=realtor_gql.mpr_id_for(prop))
        if rf:
            _apply_realtor(session, prop, rf, today, photos=metered)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"realtor {prop.id}: {exc}")
    if not metered:
        return
    _sleep()

    if not rentcast:
        pass  # not asked for by hand: no call, nothing to report
    elif rentcast_remaining(session) <= 0:
        refusals.append(f"rentcast {prop.id}: monthly budget exhausted")  # clean refusal, no call
    elif not settings.rentcast_api_key:
        refusals.append(f"rentcast {prop.id}: no API key")
    else:
        try:
            rc = fetch_rentcast_avm(address)
            if rc:
                _snapshot(session, prop.id, "rentcast", rc["value"], rc.get("low"),
                          rc.get("high"), today)
                _spend_rentcast(session)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"rentcast {prop.id}: {exc}")
        _sleep()

    if settings.zillow_wrapper_enabled and settings.rapidapi_key:
        try:
            z = fetch_zestimate(address)
            if z:
                _snapshot(session, prop.id, "zestimate", z["value"], z.get("low"),
                          z.get("high"), today)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"zestimate {prop.id}: {exc}")


def enrich_tracked(session: Session) -> int:
    """Enrich every actively-tracked property once (daily auto-enrich inside the
    scan run). Returns the number of properties enriched."""
    prop_ids = session.execute(
        select(Property.id)
        .join(Listing, Listing.property_id == Property.id)
        .join(TrackedListing, TrackedListing.listing_id == Listing.id)
        .where(TrackedListing.stage.in_(ENRICH_STAGES))
        .distinct()
    ).scalars().all()
    errors: list[str] = []
    for pid in prop_ids:
        prop = session.get(Property, pid)
        if prop is not None:
            enrich_one(session, prop, errors)
    session.commit()
    for e in errors:
        log.info("enrich miss: %s", e)
    return len(prop_ids)


def run(engine=None, property_id: str | None = None, all_tracked: bool = False,
        metered: bool = True, rentcast: bool = False) -> str:
    with JobRunner("enrich", engine) as runner:
        session = make_session(runner.engine)
        try:
            if property_id:
                targets = [property_id]
            elif all_tracked:
                targets = session.execute(
                    select(Property.id)
                    .join(Listing, Listing.property_id == Property.id)
                    .join(TrackedListing, TrackedListing.listing_id == Listing.id)
                    .where(TrackedListing.stage.in_(ENRICH_STAGES)).distinct()
                ).scalars().all()
            else:
                log.warning("enrich called without --property-id or --all-tracked: no-op")
                targets = []
            for pid in targets:
                with runner.item(pid):
                    prop = session.get(Property, pid)
                    if prop is None:
                        raise ValueError(f"unknown property {pid}")
                    errors: list[str] = []
                    skips: list[str] = []
                    enrich_one(session, prop, errors, skips=skips,
                               metered=metered, rentcast=rentcast)
                    runner.errors.extend(errors)  # real failures only — drive run status
                    for s in skips:  # config refusals: logged, never fail the run
                        log.info("enrich skip: %s", s)
                    session.commit()
                    runner.items_upserted += 1
        finally:
            session.close()
    return runner.status
