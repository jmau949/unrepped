"""Offer solver endpoint — docs/07-api-spec.md.

POST /api/offer/solve with a listing_id gives the full back-solve (max
defensible bid, binding constraint, verdict). Without one it runs profile-only
(no appraisal gap) — the Affordability page's inverse readout, optionally with
a `city` hint for the tax rate.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hb.db.engine import make_session
from hb.db.models import BuyerProfile, Listing, Property
from hb.engine import offer

router = APIRouter(prefix="/api/offer", tags=["offer"])


class Overrides(BaseModel):
    cash_available: int | None = None
    down_payment: int | None = None  # dollars
    rate_assumption: float | None = None
    appraisal_gap_tolerance_pct: float | None = None
    insurance_monthly_est: int | None = None
    include_earthquake_ins: bool | None = None
    hoa_monthly: int | None = None


class SolveRequest(BaseModel):
    listing_id: str | None = None  # None => profile-only inverse readout
    city: str | None = None        # tax-rate hint when listing_id is None
    overrides: Overrides | None = None


@router.post("/solve")
def solve(req: SolveRequest) -> dict:
    with make_session() as session:
        listing = prop = None
        if req.listing_id is not None:
            listing = session.get(Listing, req.listing_id)
            if listing is None:
                raise HTTPException(status_code=404, detail="listing not found")
            prop = session.get(Property, listing.property_id)
        profile = session.get(BuyerProfile, "default")
        overrides = (req.overrides.model_dump(exclude_none=True)
                     if req.overrides else None)
        sol = offer.solve(session, listing, prop, profile,
                          overrides=overrides, city=req.city)
    return {
        "max_defensible_bid": sol.max_defensible_bid,
        "cma_estimate": sol.cma_estimate,
        "predicted": sol.predicted,
        "verdict": sol.verdict,
        "verdict_template": sol.verdict_template,
        "escalation_cap": sol.escalation_cap,
        "gap_capped": sol.gap_capped,
        "ltv_capped": sol.ltv_capped,
        "payment_capped": sol.payment_capped,
        "limits": sol.limits,
        "e_basis": sol.e_basis,
        "recommendation": sol.recommendation,
        "opening_range": sol.opening_range,
        "ceiling": sol.ceiling,
        "posture": sol.posture,
        "confidence": sol.confidence,
    }
