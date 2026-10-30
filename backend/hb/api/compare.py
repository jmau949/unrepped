"""Side-by-side compare — docs/07-api-spec.md §Compare.

GET /api/compare?listing_ids=a,b,c returns one enriched column per listing
(2–4 of them): summary + latest CMA + blended predicted range + PITI at the
predicted point + hazard flags + sqft mismatch + tracker state. Listings
missing a CMA or overbid model degrade to nulls, never 500s.
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from hb.api.listings import _sqft_mismatch, _summary, attach_posture
from hb.db.engine import make_session
from hb.db.models import (
    BuyerProfile,
    CmaRun,
    HazardFlag,
    Listing,
    ListingGroup,
    Property,
    TrackedListing,
)
from hb.engine import affordability, valuation

router = APIRouter(prefix="/api/compare", tags=["compare"])


def _latest_cma(session, property_id: str) -> dict | None:
    run = session.execute(
        select(CmaRun)
        .where(CmaRun.property_id == property_id, CmaRun.estimate.is_not(None))
        .order_by(CmaRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    return {"estimate": run.estimate, "low": run.low, "high": run.high,
            "created_at": run.created_at}


@router.get("")
def compare(listing_ids: str = Query(...)) -> list[dict]:
    ids = [s for s in listing_ids.split(",") if s]
    if not 1 <= len(ids) <= 4:
        raise HTTPException(status_code=422, detail="compare takes 1-4 listing ids")

    with make_session() as session:
        profile = session.get(BuyerProfile, "default")
        cache: dict = {}  # shared valuation memo across the columns
        items: list[dict] = []
        for listing_id in ids:
            listing = session.get(Listing, listing_id)
            if listing is None:
                raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")
            prop = session.get(Property, listing.property_id)
            group = (session.get(ListingGroup, listing.listing_group_id)
                     if listing.listing_group_id else None)
            tracked = session.execute(
                select(TrackedListing).where(TrackedListing.listing_id == listing_id)
            ).scalar_one_or_none()

            summary = _summary(session, listing, prop, group, tracked is not None)
            summary.predicted_sale = valuation.predicted_sale(session, listing, prop, cache)
            attach_posture(session, summary, listing, prop, cache)

            piti_at_point = None
            if summary.predicted_sale and profile is not None:
                piti_at_point = affordability.calc(
                    session,
                    price=summary.predicted_sale["point"],
                    city=prop.city,
                    down_payment=profile.down_payment,
                    rate=profile.rate_assumption,
                    insurance_monthly=profile.insurance_monthly_est,
                    include_earthquake=profile.include_earthquake_ins,
                ).piti

            hazards = session.execute(
                select(HazardFlag).where(HazardFlag.property_id == prop.id)
            ).scalars().all()

            items.append({
                **summary.model_dump(),
                "cma": _latest_cma(session, prop.id),
                "piti_at_point": piti_at_point,
                "price_per_sqft": (round(listing.list_price / prop.sqft)
                                   if listing.list_price and prop.sqft else None),
                "hazard_flags": [{"hazard": h.hazard, "zone_value": h.zone_value}
                                 for h in hazards],
                "sqft_mismatch": _sqft_mismatch(prop),
                "tracked": {
                    "stage": tracked.stage,
                    "my_max_bid": tracked.my_max_bid,
                    "disclosure_checklist": tracked.disclosure_checklist or {},
                } if tracked else None,
            })
        return items
