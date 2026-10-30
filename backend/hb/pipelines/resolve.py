"""Entity resolution — docs/05-pipelines.md §5.

Maps an incoming scraped record to a canonical `properties` row. Correctness of
everything downstream (dedup, comps, CDOM) hinges on this cascade:
  1. exact (address_norm, zip, unit)
  2. fuzzy: same ZIP + same house number + <100 m + sqft within 5% (or unknown)
     + street ratio > 92
  3. create new property
Merges NULL-fill only, except that a record from a listing on the market
(`authoritative=True`) revises the physical attributes: a renovation changes
beds/baths/sqft and the live listing is the freshest description of the house.
Every other disagreement is logged into source_ids, never overwritten. Raw
source addresses are kept for audit.
"""

import logging

from rapidfuzz import fuzz
from scourgify import normalize_address_record
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import Property, utcnow_iso
from hb.geo import haversine_meters

log = logging.getLogger(__name__)

FUZZY_MAX_METERS = 100.0
FUZZY_SQFT_TOLERANCE = 0.05
FUZZY_STREET_RATIO = 92

# property fields fillable from incoming records
_FILLABLE = [
    "street", "city", "state", "lat", "lon", "beds", "baths", "sqft",
    "lot_sqft", "year_built", "property_type",
]
# physical attributes a live listing may revise; the address fields that make up
# the property's identity are never revised
_PHYSICAL = ["beds", "baths", "sqft", "lot_sqft", "year_built", "property_type"]


def _house_number(address_norm: str) -> str | None:
    """Leading house-number token of a normalized line 1; None when it has none."""
    head = address_norm.split(" ", 1)[0] if address_norm else ""
    return head if head[:1].isdigit() else None


def normalize(street: str, city: str | None, state: str | None, zip5: str) -> dict:
    """scourgify normalization with a naive fallback (CRFs break on odd input).
    Returns {address_norm, unit, city, state}."""
    try:
        rec = normalize_address_record(
            {"address_line_1": street, "city": city or "",
             "state": state or settings.geo.state,
             "postal_code": zip5}
        )
        return {
            "address_norm": (rec.get("address_line_1") or "").strip().upper(),
            "unit": (rec.get("address_line_2") or "").strip().upper(),
            "city": (rec.get("city") or city or "").strip().title() or None,
            "state": (rec.get("state") or state or settings.geo.state).strip().upper(),
        }
    except Exception:  # noqa: BLE001 — any parse failure -> deterministic fallback
        return {
            "address_norm": " ".join(street.split()).upper(),
            "unit": "",
            "city": (city or "").strip().title() or None,
            "state": (state or settings.geo.state).strip().upper(),
        }


def _merge(prop: Property, record: dict, source: str, source_id: str | None,
           raw_address: str, *, authoritative: bool = False) -> None:
    """NULL-fill merge + audit trail. A disagreement is logged, never
    overwritten — unless the record is authoritative (a listing on the market)
    and the field is a physical attribute, which it then replaces."""
    changed = False
    conflicts = []
    replaced = []
    for field in _FILLABLE:
        incoming = record.get(field)
        if incoming is None:
            continue
        current = getattr(prop, field)
        if current is None:
            setattr(prop, field, incoming)
            changed = True
        elif current == incoming or field in ("lat", "lon"):  # coords always jitter
            continue
        elif authoritative and field in _PHYSICAL:
            setattr(prop, field, incoming)
            replaced.append({"field": field, "kept": incoming, "replaced": current})
            changed = True
        else:
            conflicts.append({"field": field, "kept": current, "seen": incoming})

    ids = dict(prop.source_ids or {})
    src_list = list(ids.get(source, []))
    if source_id and source_id not in src_list:
        src_list.append(source_id)
        ids[source] = src_list
        changed = True
    raw_list = list(ids.get("raw_addresses", []))
    if raw_address not in raw_list:
        raw_list.append(raw_address)
        ids["raw_addresses"] = raw_list
        changed = True
    if conflicts or replaced:
        before = list(ids.get("conflicts", []))
        conflict_list = [
            c for c in before
            # an entry that recorded the value just replaced describes a row
            # state that no longer exists
            if not any(c.get("field") == r["field"] and c.get("kept") == r["replaced"]
                       for r in replaced)
        ]
        for c in conflicts + replaced:
            if c not in conflict_list:
                conflict_list.append(c)
        if conflict_list != before:
            if conflict_list:
                ids["conflicts"] = conflict_list
            else:
                ids.pop("conflicts", None)
            changed = True
    if changed:
        prop.source_ids = ids
        prop.updated_at = utcnow_iso()


def resolve(session: Session, record: dict, source: str = "realtor",
            source_id: str | None = None, *, authoritative: bool = False) -> tuple[str, bool]:
    """record: {street, unit?, city, state, zip, lat, lon, beds, baths, sqft,
    lot_sqft, year_built, property_type}. `authoritative` marks a record from a
    listing on the market, whose physical attributes revise the property's.
    Returns (property_id, created)."""
    raw_address = f"{record.get('street', '')}, {record.get('city', '')} {record.get('zip', '')}"
    norm = normalize(record.get("street") or "", record.get("city"),
                     record.get("state"), record["zip"])
    unit = norm["unit"] or (record.get("unit") or "").strip().upper()

    # 1. exact
    prop = session.execute(
        select(Property).where(
            Property.address_norm == norm["address_norm"],
            Property.zip == record["zip"],
            Property.unit == unit,
        )
    ).scalar_one_or_none()

    # 2. fuzzy (guarded: needs coordinates)
    if prop is None and record.get("lat") is not None and record.get("lon") is not None:
        house_no = _house_number(norm["address_norm"])
        candidates = session.execute(
            select(Property).where(Property.zip == record["zip"], Property.unit == unit)
        ).scalars().all()
        for cand in candidates:
            # neighbours on a tract street share a floor plan often enough that
            # distance, sqft and a one-digit string difference all pass; the
            # house number is the one token that cannot differ for the same home
            cand_no = _house_number(cand.address_norm)
            if house_no and cand_no and cand_no != house_no:
                continue
            if cand.lat is None or cand.lon is None:
                continue
            if haversine_meters(record["lat"], record["lon"], cand.lat, cand.lon) >= FUZZY_MAX_METERS:
                continue
            if (
                record.get("sqft") and cand.sqft
                and abs(record["sqft"] - cand.sqft) / cand.sqft > FUZZY_SQFT_TOLERANCE
            ):
                continue
            if fuzz.token_sort_ratio(norm["address_norm"], cand.address_norm) <= FUZZY_STREET_RATIO:
                continue
            prop = cand
            log.info("fuzzy-matched '%s' -> property %s ('%s')",
                     norm["address_norm"], cand.id, cand.address_norm)
            break

    created = False
    if prop is None:
        prop = Property(
            address_norm=norm["address_norm"],
            unit=unit,
            zip=record["zip"],
            city=norm["city"],
            state=norm["state"],
            source_ids={},
        )
        session.add(prop)
        created = True

    _merge(prop, record, source, source_id, raw_address, authoritative=authoritative)
    session.flush()
    return prop.id, created
