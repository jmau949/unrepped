"""Tour endpoints — docs/07-api-spec.md §Tours, docs/13-tour-playbook.md.

The buyer's own observations, plus the seed (`/field-data`) the Field page
loads for the day's homes and saves back to as you tap.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb import tour_spec, watchlist
from hb.db.engine import make_session
from hb.db.models import (
    HazardFlag,
    Listing,
    ListingGroup,
    Property,
    PropertyTour,
    utcnow_iso,
)

router = APIRouter(prefix="/api/tours", tags=["tours"])

KINDS = ["open_house", "private", "drive_by", "second_visit"]
VERDICTS = ["offer", "maybe", "pass"]


def facts_for(session: Session, prop: Property) -> dict:
    """The property context that prunes the checklist and writes the context notes."""
    from hb.api.listings import _sqft_mismatch

    hazards = session.execute(
        select(HazardFlag.hazard).where(HazardFlag.property_id == prop.id)
    ).scalars().all()
    return {
        "year_built": prop.year_built,
        "sqft": prop.sqft,
        "assessor_sqft": prop.assessor_sqft,
        "sqft_mismatch": _sqft_mismatch(prop),
        "hazards": list(hazards),
    }


def tour_out(tour: PropertyTour, facts: dict) -> dict:
    """Serialize a tour with its roll-up attached, so no client reimplements the rules."""
    rollup = tour_spec.evaluate(tour.checklist, items=tour_spec.items_for(facts))
    low = tour.repair_low if tour.repair_low is not None else rollup["costs"]["low"]
    high = tour.repair_high if tour.repair_high is not None else rollup["costs"]["high"]
    return {
        "id": tour.id,
        "property_id": tour.property_id,
        "listing_id": tour.listing_id,
        "toured_on": tour.toured_on,
        "kind": tour.kind,
        "checklist": tour.checklist or {},
        "agent_answers": tour.agent_answers or {},
        "gut_score": tour.gut_score,
        "verdict": tour.verdict,
        "notes": tour.notes,
        "repair_low": tour.repair_low,
        "repair_high": tour.repair_high,
        "source": tour.source,
        "created_at": tour.created_at,
        "updated_at": tour.updated_at,
        "flags": rollup["flags"],
        "costs": {**rollup["costs"], "low": low, "high": high,
                  "overridden": tour.repair_low is not None or tour.repair_high is not None},
        "unanswered": rollup["unanswered"],
    }


# --- static paths first: they would otherwise be captured by /{tour_id} ---


@router.get("/checklist")
def checklist(listing_id: str | None = None, property_id: str | None = None) -> dict:
    """The checklist pruned to one home, plus what the app already knows about it."""
    with make_session() as session:
        prop = _resolve_property(session, listing_id, property_id)
        facts = facts_for(session, prop)
        return {"property_id": prop.id, "facts": facts, **tour_spec.spec_for(facts)}


@router.get("/field-data")
def field_data(listing_ids: str = Query(..., description="comma-separated listing ids")
               ) -> dict:
    """Seed for the Field page (docs/08 §11) — everything it needs for the day's
    homes in one call.

    Each home is the full `_field_home()` payload: facts, pricing, CMA/predicted
    ranges, the age-pruned spec (carrying `flag_when`, so flags raise with no
    round trip), and any tour already recorded.
    """
    ids = [i.strip() for i in listing_ids.split(",") if i.strip()]
    if not ids:
        raise HTTPException(422, "listing_ids required")
    with make_session() as session:
        homes = [_field_home(session, i) for i in ids]
    return {"generated_at": utcnow_iso(), "homes": homes}


class TourImport(BaseModel):
    property_id: str | None = None
    listing_id: str | None = None
    toured_on: str
    kind: str | None = None
    checklist: dict | None = None
    agent_answers: dict | None = None
    gut_score: int | None = None
    verdict: str | None = None
    notes: str | None = None


class ImportRequest(BaseModel):
    tours: list[TourImport] | None = None


@router.post("/import")
def import_tours(req: ImportRequest) -> dict:
    """Recover field captures from the Field page's "Copy answers" JSON.

    The one path back into the DB when the normal POST→PATCH save could not run
    (docs/08 §11). Gap-fill only, deliberately unlike the sync
    PATCH: an incoming value is taken only where the app has nothing, and a
    genuine disagreement is reported under `conflicts` rather than applied — so
    replaying a stale backup can never revert an in-app edit.
    """
    created = updated = unchanged = 0
    conflicts: list[dict] = []
    errors: list[dict] = []

    incoming_tours = list(req.tours or [])
    if not incoming_tours:
        raise HTTPException(422, "nothing to import — paste the app's Copy-backup JSON")

    with make_session() as session:
        # a backup may carry listing ids only; resolve them to properties
        for incoming in incoming_tours:
            if incoming.property_id is None and incoming.listing_id:
                listing = session.get(Listing, incoming.listing_id)
                if listing is not None:
                    incoming.property_id = listing.property_id
        for incoming in incoming_tours:
            prop = (session.get(Property, incoming.property_id)
                    if incoming.property_id else None)
            if prop is None:
                errors.append({"property_id": incoming.property_id,
                               "toured_on": incoming.toured_on,
                               "error": "unknown property"})
                continue
            row = session.execute(
                select(PropertyTour).where(
                    PropertyTour.property_id == incoming.property_id,
                    PropertyTour.toured_on == incoming.toured_on,
                )
            ).scalar_one_or_none()

            if row is None:
                session.add(PropertyTour(
                    property_id=incoming.property_id,
                    listing_id=incoming.listing_id,
                    toured_on=incoming.toured_on,
                    kind=incoming.kind or "open_house",
                    checklist=incoming.checklist or {},
                    agent_answers=incoming.agent_answers or {},
                    gut_score=incoming.gut_score,
                    verdict=incoming.verdict,
                    notes=incoming.notes,
                    source="offline_kit",
                ))
                watchlist.set_watching(prop, True)
                created += 1
                continue

            changed = _merge(row, incoming, conflicts)
            if changed:
                row.updated_at = utcnow_iso()
                updated += 1
            else:
                unchanged += 1
        session.commit()

    return {"created": created, "updated": updated, "unchanged": unchanged,
            "conflicts": conflicts, "errors": errors}


def _merge(row: PropertyTour, incoming: TourImport, conflicts: list[dict]) -> bool:
    """Fill gaps only. Returns whether anything actually changed."""
    changed = False

    def note_conflict(field: str, existing, offered) -> None:
        conflicts.append({"property_id": row.property_id, "toured_on": row.toured_on,
                          "field": field, "existing": existing, "incoming": offered})

    for field in ("listing_id", "gut_score", "verdict", "notes", "kind"):
        offered = getattr(incoming, field)
        if offered is None or offered == "":
            continue
        existing = getattr(row, field)
        if existing == offered:
            continue  # re-importing the same file has to be a true no-op
        # `kind` always has a value, so only a non-default existing one is a real edit
        if existing in (None, "") or (field == "kind" and existing == "open_house"):
            setattr(row, field, offered)
            changed = True
        else:
            note_conflict(field, existing, offered)

    for field in ("checklist", "agent_answers"):
        offered_map = getattr(incoming, field) or {}
        if not offered_map:
            continue
        current = dict(getattr(row, field) or {})
        field_changed = False
        for key, value in offered_map.items():
            if value is None or value == "":
                continue
            if key not in current or current[key] in (None, ""):
                current[key] = value
                field_changed = True
            elif current[key] != value:
                note_conflict(f"{field}.{key}", current[key], value)
        if field_changed:
            # reassign: SQLAlchemy JSON columns are not mutation-tracked
            setattr(row, field, current)
            changed = True

    return changed


# --- collection + item routes ---


@router.get("")
def list_tours(property_id: str | None = None, listing_id: str | None = None) -> list[dict]:
    with make_session() as session:
        prop = _resolve_property(session, listing_id, property_id)
        facts = facts_for(session, prop)
        rows = session.execute(
            select(PropertyTour)
            .where(PropertyTour.property_id == prop.id)
            .order_by(PropertyTour.toured_on.desc())
        ).scalars().all()
        return [tour_out(t, facts) for t in rows]


class TourRequest(BaseModel):
    property_id: str | None = None
    listing_id: str | None = None
    toured_on: str | None = None
    kind: str | None = None


@router.post("")
def create_tour(req: TourRequest) -> dict:
    with make_session() as session:
        prop = _resolve_property(session, req.listing_id, req.property_id)
        toured_on = req.toured_on or date.today().isoformat()
        kind = req.kind or "open_house"
        if kind not in KINDS:
            raise HTTPException(422, f"kind must be one of {KINDS}")
        existing = session.execute(
            select(PropertyTour).where(
                PropertyTour.property_id == prop.id,
                PropertyTour.toured_on == toured_on,
            )
        ).scalar_one_or_none()
        if existing:
            return tour_out(existing, facts_for(session, prop))  # idempotent
        row = PropertyTour(property_id=prop.id, listing_id=req.listing_id,
                           toured_on=toured_on, kind=kind)
        session.add(row)
        watchlist.set_watching(prop, True)  # touring a home watches it (docs/08 §5b)
        session.commit()
        return tour_out(row, facts_for(session, prop))


class TourPatch(BaseModel):
    kind: str | None = None
    checklist: dict | None = None
    agent_answers: dict | None = None
    gut_score: int | None = None
    verdict: str | None = None
    notes: str | None = None
    repair_low: int | None = None
    repair_high: int | None = None


@router.patch("/{tour_id}")
def patch_tour(tour_id: str, patch: TourPatch) -> dict:
    with make_session() as session:
        row = session.get(PropertyTour, tour_id)
        if row is None:
            raise HTTPException(404, "tour not found")
        if patch.kind is not None:
            if patch.kind not in KINDS:
                raise HTTPException(422, f"kind must be one of {KINDS}")
            row.kind = patch.kind
        if patch.verdict is not None:
            if patch.verdict and patch.verdict not in VERDICTS:
                raise HTTPException(422, f"verdict must be one of {VERDICTS}")
            row.verdict = patch.verdict or None
        if patch.gut_score is not None:
            if not 1 <= patch.gut_score <= 5:
                raise HTTPException(422, "gut_score must be 1-5")
            row.gut_score = patch.gut_score
        if patch.notes is not None:
            row.notes = patch.notes or None
        if patch.repair_low is not None:
            row.repair_low = patch.repair_low
        if patch.repair_high is not None:
            row.repair_high = patch.repair_high
        # JSON columns merge, like tracked_listings.disclosure_checklist
        if patch.checklist is not None:
            row.checklist = {**(row.checklist or {}), **patch.checklist}
        if patch.agent_answers is not None:
            row.agent_answers = {**(row.agent_answers or {}), **patch.agent_answers}
        row.updated_at = utcnow_iso()
        prop = session.get(Property, row.property_id)
        session.commit()
        return tour_out(row, facts_for(session, prop))


@router.delete("/{tour_id}")
def delete_tour(tour_id: str) -> dict:
    with make_session() as session:
        row = session.get(PropertyTour, tour_id)
        if row is None:
            raise HTTPException(404, "tour not found")
        session.delete(row)
        session.commit()
        return {"deleted": tour_id}


# --- helpers ---


def _resolve_property(session: Session, listing_id: str | None,
                      property_id: str | None) -> Property:
    if property_id:
        prop = session.get(Property, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        return prop
    if listing_id:
        listing = session.get(Listing, listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        prop = session.get(Property, listing.property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        return prop
    raise HTTPException(422, "listing_id or property_id required")


def _field_home(session: Session, listing_id: str) -> dict:
    """Everything the Field page shows about one home."""
    from hb.api.listings import _summary, attach_posture
    from hb.engine import valuation

    listing = session.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(404, f"listing not found: {listing_id}")
    prop = session.get(Property, listing.property_id)
    facts = facts_for(session, prop)
    # the group carries cumulative DOM — the leverage signal worth having in hand
    group = (session.get(ListingGroup, listing.listing_group_id)
             if listing.listing_group_id else None)

    cache: dict = {}
    summary = _summary(session, listing, prop, group, False)
    summary.predicted_sale = valuation.predicted_sale(session, listing, prop, cache)
    attach_posture(session, summary, listing, prop, cache)
    predicted = summary.predicted_sale or {}

    existing = session.execute(
        select(PropertyTour).where(PropertyTour.property_id == prop.id)
        .order_by(PropertyTour.toured_on.desc())
    ).scalars().first()

    return {
        "listing_id": listing.id,
        "property_id": prop.id,
        "address": summary.address,
        "city": prop.city,
        "zip": prop.zip,
        "beds": prop.beds,
        "baths": prop.baths,
        "sqft": prop.sqft,
        "lot_sqft": prop.lot_sqft,
        "year_built": prop.year_built,
        "list_price": listing.list_price,
        "original_list_price": listing.original_list_price,
        "posture": summary.posture,
        "cumulative_dom": summary.cumulative_dom,
        "price_cuts": summary.price_cut_count,
        "offer_due_at": listing.offer_due_at,
        "cma_estimate": cache.get(("cma_estimate", prop.id)),
        "predicted_low": predicted.get("low"),
        "predicted_point": predicted.get("point"),
        "predicted_high": predicted.get("high"),
        "facts": facts,
        "spec": tour_spec.spec_for(facts),
        "existing": tour_out(existing, facts) if existing else None,
    }
