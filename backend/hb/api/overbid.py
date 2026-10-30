"""Overbid endpoint — docs/07-api-spec.md §Overbid."""

from fastapi import APIRouter, HTTPException

from hb.db.engine import make_session
from hb.db.models import Listing, Property
from hb.engine import overbid
from hb.engine.valuation import latest_cma_estimate

router = APIRouter(prefix="/api/overbid", tags=["overbid"])


@router.get("/{listing_id}")
def get_overbid(listing_id: str) -> dict:
    with make_session() as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        prop = session.get(Property, listing.property_id)
        result = overbid.predict(
            session, listing, prop, cma_estimate=latest_cma_estimate(session, prop.id)
        )
        return {
            "list_price": result.list_price, "basis": result.basis,
            "basis_reason": result.basis_reason, "n_comps": result.n_comps,
            "n_eff": result.n_eff, "window_days": result.window_days,
            "p25": result.p25, "p50": result.p50, "p75": result.p75,
            "predicted": result.predicted, "atypical_pricing": result.atypical_pricing,
            "histogram": result.histogram, "comps": result.comps,
        }
