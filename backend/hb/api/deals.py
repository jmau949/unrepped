"""Deals (closing tracker) endpoints — docs/07-api-spec.md §Deals.

One deal per accepted offer. The row holds five numbers off the contract; every
date on the page is derived by `hb.closing_spec` and recomputed on read, so
correcting `accepted_on` re-dates the whole transaction and a spec correction
reprices an open deal (docs/04, docs/14 §15).
"""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select

from hb import closing_spec, packs
from hb.api.contacts import ContactIn, ContactPatch, apply_patch, contact_out, require_kind
from hb.db.engine import make_session
from hb.db.models import Contact, Deal, Listing, Property, TrackedListing, utcnow_iso

router = APIRouter(prefix="/api/deals", tags=["deals"])

STATUSES = ["open", "closed", "cancelled"]


class DealCreate(BaseModel):
    listing_id: str
    accepted_on: str | None = None
    purchase_price: int | None = None
    close_of_escrow_on: str | None = None


class DealPatch(BaseModel):
    accepted_on: str | None = None
    purchase_price: int | None = None
    emd_amount: int | None = None
    emd_sent_on: str | None = None
    emd_business_days: int | None = None
    close_of_escrow_on: str | None = None
    investigation_days: int | None = None
    appraisal_days: int | None = None
    loan_days: int | None = None
    financed: bool | None = None
    loan_type: str | None = None
    escrow_company: str | None = None
    escrow_number: str | None = None
    status: str | None = None
    notes: str | None = None
    checklist: dict | None = None
    # Contingency day-counts use NULL to mean "waived", so a plain PATCH can never
    # express it — `None` already means "not supplied". Name the ones to clear.
    waive: list[str] | None = None


WAIVABLE = {
    "investigation": "investigation_days",
    "appraisal": "appraisal_days",
    "loan": "loan_days",
}


def _deal_dict(row: Deal) -> dict:
    """The contract numbers, in the shape closing_spec expects."""
    return {
        "id": row.id,
        "listing_id": row.listing_id,
        "property_id": row.property_id,
        "accepted_on": row.accepted_on,
        "purchase_price": row.purchase_price,
        "emd_amount": row.emd_amount,
        "emd_sent_on": row.emd_sent_on,
        "emd_business_days": row.emd_business_days,
        "close_of_escrow_on": row.close_of_escrow_on,
        "investigation_days": row.investigation_days,
        "appraisal_days": row.appraisal_days,
        "loan_days": row.loan_days,
        "financed": bool(row.financed),
        "loan_type": row.loan_type,
        "escrow_company": row.escrow_company,
        "escrow_number": row.escrow_number,
        "status": row.status,
        "notes": row.notes,
        "checklist": row.checklist or {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _facts(session, property_id: str) -> dict:
    """Property context the spec prunes on — year_built and city (docs/14 §7)."""
    prop = session.get(Property, property_id)
    if prop is None:
        return {}
    return {"year_built": prop.year_built, "city": prop.city}


def _team_stmt(deal: Deal):
    """The deal's roster: contacts added on the closing page (`deal_id`) plus those
    saved on the listing before the offer (`listing_id`) — the listing agent you
    reached in week one is the same person you negotiate with in escrow."""
    return select(Contact).where(
        or_(Contact.deal_id == deal.id, Contact.listing_id == deal.listing_id)
    ).order_by(Contact.kind)


def _team_member(session, deal: Deal, contact_id: str) -> Contact:
    row = session.get(Contact, contact_id)
    if row is None or (row.deal_id != deal.id and row.listing_id != deal.listing_id):
        raise HTTPException(404, "contact not found")
    return row


def _deal_or_404(session, deal_id: str) -> Deal:
    row = session.get(Deal, deal_id)
    if row is None:
        raise HTTPException(404, "deal not found")
    return row


def deal_out(session, row: Deal, *, detail: bool = False) -> dict:
    """Serialize with the roll-up attached — never stored, always recomputed."""
    facts = _facts(session, row.property_id)
    deal = _deal_dict(row)
    out = dict(deal)
    out["rollup"] = closing_spec.evaluate(deal, deal["checklist"], facts)

    prop = session.get(Property, row.property_id)
    if prop is not None:
        out["address"] = prop.address_norm
        out["city"] = prop.city
        out["zip"] = prop.zip
        out["year_built"] = prop.year_built

    if detail:
        out["spec"] = closing_spec.spec_for(deal, facts, deal["checklist"])
        out["contacts"] = [
            contact_out(c) for c in session.execute(_team_stmt(row)).scalars()
        ]
    return out


# --- static paths first: they would otherwise be captured by /{deal_id} ---


PREVIEW_ESCROW_DAYS = 30


@router.get("/spec")
def get_spec(listing_id: str | None = None, accepted_on: str | None = None,
             close_of_escrow_on: str | None = None,
             investigation_days: int | None = None,
             appraisal_days: int | None = None,
             loan_days: int | None = None) -> dict:
    """Preview the task spec for a hypothetical deal — no row required.

    Lets the closing page show what the process looks like before an offer is
    accepted, which is the whole point of reading it early (docs/14).

    COE defaults to a 30-day escrow rather than None: an unset anchor prunes its
    tasks, and a preview that silently omitted the final week and everything after
    close would teach the reader the wrong shape of the process. Contingency
    day-counts default to the pack's.
    """
    c = packs.current().closing.contingency
    accepted = closing_spec.parse_date(accepted_on) or date.today()
    coe = closing_spec.parse_date(close_of_escrow_on) or (
        accepted + timedelta(days=PREVIEW_ESCROW_DAYS))
    deal = {
        "accepted_on": accepted.isoformat(),
        "close_of_escrow_on": coe.isoformat(),
        "investigation_days": (c.investigation_days if investigation_days is None
                               else investigation_days),
        "appraisal_days": c.appraisal_days if appraisal_days is None else appraisal_days,
        "loan_days": c.loan_days if loan_days is None else loan_days,
    }
    with make_session() as session:
        facts = {}
        if listing_id:
            listing = session.get(Listing, listing_id)
            if listing is None:
                raise HTTPException(404, "listing not found")
            facts = _facts(session, listing.property_id)
        return closing_spec.spec_for(deal, facts)


@router.get("")
def list_deals(status: str | None = None) -> list[dict]:
    with make_session() as session:
        stmt = select(Deal).order_by(Deal.accepted_on.desc())
        if status:
            stmt = stmt.where(Deal.status == status)
        return [deal_out(session, row) for row in session.execute(stmt).scalars()]


@router.post("")
def create_deal(req: DealCreate) -> dict:
    with make_session() as session:
        listing = session.get(Listing, req.listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")

        existing = session.execute(
            select(Deal).where(Deal.listing_id == req.listing_id)
        ).scalar_one_or_none()
        if existing:
            return deal_out(session, existing, detail=True)  # idempotent

        c = packs.current().closing.contingency
        row = Deal(
            listing_id=listing.id,
            property_id=listing.property_id,
            accepted_on=req.accepted_on or date.today().isoformat(),
            purchase_price=req.purchase_price or listing.list_price,
            close_of_escrow_on=req.close_of_escrow_on,
            # Pack defaults, applied here rather than on the column so a deliberate
            # NULL (= waived) survives a later PATCH (docs/14 §4).
            emd_business_days=c.emd_business_days,
            investigation_days=c.investigation_days,
            appraisal_days=c.appraisal_days,
            loan_days=c.loan_days,
        )
        session.add(row)

        # The kanban hands off here; keep the tracked row in step if there is one.
        tracked = session.execute(
            select(TrackedListing).where(TrackedListing.listing_id == listing.id)
        ).scalar_one_or_none()
        if tracked is not None and tracked.stage != "closing":
            tracked.stage = "closing"
            tracked.updated_at = utcnow_iso()

        session.commit()
        return deal_out(session, row, detail=True)


@router.get("/{deal_id}")
def get_deal(deal_id: str) -> dict:
    with make_session() as session:
        row = session.get(Deal, deal_id)
        if row is None:
            raise HTTPException(404, "deal not found")
        return deal_out(session, row, detail=True)


@router.patch("/{deal_id}")
def patch_deal(deal_id: str, patch: DealPatch) -> dict:
    with make_session() as session:
        row = session.get(Deal, deal_id)
        if row is None:
            raise HTTPException(404, "deal not found")

        if patch.status is not None:
            if patch.status not in STATUSES:
                raise HTTPException(422, f"status must be one of {STATUSES}")
            row.status = patch.status

        for field in ("accepted_on", "emd_sent_on", "close_of_escrow_on"):
            value = getattr(patch, field)
            if value is not None:
                if closing_spec.parse_date(value) is None:
                    raise HTTPException(422, f"{field} must be an ISO date (YYYY-MM-DD)")
                setattr(row, field, value)

        for field in ("purchase_price", "emd_amount", "emd_business_days",
                      "investigation_days", "appraisal_days", "loan_days",
                      "loan_type", "escrow_company", "escrow_number"):
            value = getattr(patch, field)
            if value is not None:
                setattr(row, field, value)

        if patch.financed is not None:
            row.financed = 1 if patch.financed else 0
        if patch.notes is not None:
            row.notes = patch.notes or None

        if patch.waive:
            for name in patch.waive:
                if name not in WAIVABLE:
                    raise HTTPException(422, f"waive must be one of {list(WAIVABLE)}")
                setattr(row, WAIVABLE[name], None)

        if patch.checklist is not None:
            # Merge, like every other JSON column in this schema. JSON columns are
            # not mutation-tracked, so reassign rather than mutate in place.
            merged = {**(row.checklist or {})}
            for key, value in patch.checklist.items():
                if value is None:
                    merged.pop(key, None)
                    continue
                prior = merged.get(key)
                merged[key] = {**prior, **value} if isinstance(prior, dict) \
                    and isinstance(value, dict) else value
            row.checklist = merged

        row.updated_at = utcnow_iso()
        session.commit()
        return deal_out(session, row, detail=True)


@router.delete("/{deal_id}")
def delete_deal(deal_id: str) -> dict:
    with make_session() as session:
        row = session.get(Deal, deal_id)
        if row is None:
            raise HTTPException(404, "deal not found")
        for contact in session.execute(
            select(Contact).where(Contact.deal_id == deal_id)
        ).scalars():
            session.delete(contact)
        session.delete(row)
        session.commit()
        return {"deleted": deal_id}


# --- deal team ---


@router.get("/{deal_id}/contacts")
def list_contacts(deal_id: str) -> list[dict]:
    with make_session() as session:
        deal = _deal_or_404(session, deal_id)
        return [contact_out(c) for c in session.execute(_team_stmt(deal)).scalars()]


@router.post("/{deal_id}/contacts")
def add_contact(deal_id: str, req: ContactIn) -> dict:
    with make_session() as session:
        _deal_or_404(session, deal_id)
        require_kind(req.kind)
        row = Contact(deal_id=deal_id, **req.model_dump())
        session.add(row)
        session.commit()
        return contact_out(row)


@router.patch("/{deal_id}/contacts/{contact_id}")
def patch_contact(deal_id: str, contact_id: str, patch: ContactPatch) -> dict:
    with make_session() as session:
        deal = _deal_or_404(session, deal_id)
        row = _team_member(session, deal, contact_id)
        apply_patch(row, patch)
        session.commit()
        return contact_out(row)


@router.delete("/{deal_id}/contacts/{contact_id}")
def delete_contact(deal_id: str, contact_id: str) -> dict:
    with make_session() as session:
        deal = _deal_or_404(session, deal_id)
        row = _team_member(session, deal, contact_id)
        session.delete(row)
        session.commit()
        return {"deleted": contact_id}
