"""Tracker endpoints — docs/07-api-spec.md §Tracker."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from hb import watchlist
from hb.api.listings import _summary, attach_posture
from hb.db.engine import make_session
from hb.db.models import (
    Alert, Deal, Listing, ListingGroup, Property, TrackedListing, utcnow_iso,
)

router = APIRouter(prefix="/api/tracker", tags=["tracker"])

# `won` is acceptance; `closing` is the escrow that follows it (docs/14). Kept as two
# stages because the work, the clock and the page are different.
STAGES = ["saved", "toured", "disclosures", "offer_prep", "offered", "won", "closing",
          "lost", "passed"]


class TrackRequest(BaseModel):
    listing_id: str


class TrackPatch(BaseModel):
    stage: str | None = None
    notes: str | None = None
    my_max_bid: int | None = None
    disclosure_checklist: dict | None = None


@router.get("")
def list_tracked() -> list[dict]:
    from hb.engine import valuation

    with make_session() as session:
        rows = session.execute(
            select(TrackedListing, Listing, Property, ListingGroup)
            .join(Listing, TrackedListing.listing_id == Listing.id)
            .join(Property, Listing.property_id == Property.id)
            .outerjoin(ListingGroup, Listing.listing_group_id == ListingGroup.id)
            .order_by(TrackedListing.created_at)
        ).all()
        out = []
        cache: dict = {}  # tracked homes cluster in few ZIPs — share sample loads
        deal_ids = {
            d.listing_id: d.id
            for d in session.execute(select(Deal)).scalars()
        }
        for t, lst, prop, group in rows:
            summary = _summary(session, lst, prop, group, True)
            summary.predicted_sale = valuation.predicted_sale(session, lst, prop, cache)
            attach_posture(session, summary, lst, prop, cache)
            cma_estimate = cache.get(("cma_estimate", prop.id))
            out.append({
                "id": t.id,
                "stage": t.stage,
                "notes": t.notes,
                "my_max_bid": t.my_max_bid,
                "disclosure_checklist": t.disclosure_checklist or {},
                "offer_due_at": lst.offer_due_at,
                "deal_id": deal_ids.get(lst.id),
                "cma_estimate": cma_estimate,
                "overbid_point": (summary.predicted_sale or {}).get("point"),
                "listing": summary.model_dump(),
            })
        return out


@router.post("")
def track(req: TrackRequest) -> dict:
    with make_session() as session:
        listing = session.get(Listing, req.listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        existing = session.execute(
            select(TrackedListing).where(TrackedListing.listing_id == req.listing_id)
        ).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "stage": existing.stage}  # idempotent
        row = TrackedListing(listing_id=req.listing_id)
        session.add(row)
        # tracking a home also watches it, so untracking later keeps it on the
        # Watchlist (docs/08 §5b)
        watchlist.set_watching(session.get(Property, listing.property_id), True)
        session.commit()
        return {"id": row.id, "stage": row.stage}


@router.patch("/{tracked_id}")
def patch_tracked(tracked_id: str, patch: TrackPatch) -> dict:
    with make_session() as session:
        row = session.get(TrackedListing, tracked_id)
        if row is None:
            raise HTTPException(404, "not tracked")
        if patch.stage is not None:
            if patch.stage not in STAGES:
                raise HTTPException(422, f"stage must be one of {STAGES}")
            row.stage = patch.stage
        if patch.notes is not None:
            row.notes = patch.notes
        if patch.my_max_bid is not None:
            row.my_max_bid = patch.my_max_bid
        if patch.disclosure_checklist is not None:
            row.disclosure_checklist = {**(row.disclosure_checklist or {}),
                                        **patch.disclosure_checklist}
        row.updated_at = utcnow_iso()
        session.commit()
        return {"id": row.id, "stage": row.stage, "notes": row.notes,
                "my_max_bid": row.my_max_bid,
                "disclosure_checklist": row.disclosure_checklist}


@router.delete("/{tracked_id}")
def untrack(tracked_id: str) -> dict:
    with make_session() as session:
        row = session.get(TrackedListing, tracked_id)
        if row is None:
            raise HTTPException(404, "not tracked")
        # Alerts carry this row as provenance (`alerts.tracked_listing_id` is a real
        # FK and `PRAGMA foreign_keys=ON`), so deleting a tracked home that ever
        # fired an alert would raise IntegrityError. Detach rather than cascade:
        # the alert stays in the inbox and still points at the home via listing_id,
        # and dedup_key is a plain string, so nothing is deduped away by this.
        session.execute(
            update(Alert)
            .where(Alert.tracked_listing_id == tracked_id)
            .values(tracked_listing_id=None)
        )
        session.delete(row)
        session.commit()
        return {"deleted": tracked_id}
