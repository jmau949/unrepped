"""Contacts — the shared vocabulary and the listing-scoped routes (docs/07 §Listings).

One `contacts` table serves two pages. The closing page adds the deal team under
`/api/deals/{id}/contacts` (hb/api/deals.py); the listing detail page saves the
people behind a listing here, under `/api/listings/{id}/contacts`, before any
offer exists — the listing agent reached in week one, the owner of record found
on the assessor roll. Both routers share the kind list, the request schemas and
the serializer defined in this module, and a deal's team includes the contacts
saved on its listing (docs/04 §contacts).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from hb.db.engine import make_session
from hb.db.models import Contact, Listing

router = APIRouter(prefix="/api/listings/{listing_id}/contacts", tags=["contacts"])

CONTACT_KINDS = [
    "escrow", "title", "lender", "inspector", "insurance", "attorney", "tc",
    "listing_agent", "owner", "contractor", "other",
]

TEXT_FIELDS = ("name", "company", "role", "phone", "email", "notes")


class ContactIn(BaseModel):
    kind: str
    name: str
    company: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


class ContactPatch(BaseModel):
    kind: str | None = None
    name: str | None = None
    company: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


def require_kind(kind: str) -> None:
    if kind not in CONTACT_KINDS:
        raise HTTPException(422, f"kind must be one of {CONTACT_KINDS}")


def apply_patch(row: Contact, patch: ContactPatch) -> None:
    """PATCH semantics shared by both routers: None = not supplied, "" = clear."""
    if patch.kind is not None:
        require_kind(patch.kind)
        row.kind = patch.kind
    for field in TEXT_FIELDS:
        value = getattr(patch, field)
        if value is not None:
            setattr(row, field, value or None)


def contact_out(row: Contact) -> dict:
    return {
        "id": row.id, "kind": row.kind, "name": row.name, "company": row.company,
        "role": row.role, "phone": row.phone, "email": row.email, "notes": row.notes,
        "deal_id": row.deal_id, "listing_id": row.listing_id,
    }


def _listing_or_404(session, listing_id: str) -> Listing:
    listing = session.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(404, "listing not found")
    return listing


def _own_contact_or_404(session, listing_id: str, contact_id: str) -> Contact:
    row = session.get(Contact, contact_id)
    if row is None or row.listing_id != listing_id:
        raise HTTPException(404, "contact not found")
    return row


@router.get("")
def list_contacts(listing_id: str) -> list[dict]:
    with make_session() as session:
        _listing_or_404(session, listing_id)
        return [contact_out(c) for c in session.execute(
            select(Contact).where(Contact.listing_id == listing_id).order_by(Contact.kind)
        ).scalars()]


@router.post("")
def add_contact(listing_id: str, req: ContactIn) -> dict:
    with make_session() as session:
        _listing_or_404(session, listing_id)
        require_kind(req.kind)
        row = Contact(listing_id=listing_id, **req.model_dump())
        session.add(row)
        session.commit()
        return contact_out(row)


@router.patch("/{contact_id}")
def patch_contact(listing_id: str, contact_id: str, patch: ContactPatch) -> dict:
    with make_session() as session:
        row = _own_contact_or_404(session, listing_id, contact_id)
        apply_patch(row, patch)
        session.commit()
        return contact_out(row)


@router.delete("/{contact_id}")
def delete_contact(listing_id: str, contact_id: str) -> dict:
    with make_session() as session:
        row = _own_contact_or_404(session, listing_id, contact_id)
        session.delete(row)
        session.commit()
        return {"deleted": contact_id}
