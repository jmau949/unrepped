"""Blended predicted sale value — the single "what will this sell for?" number.

The transparent comp CMA (docs/06 §4) and the overbid point (§5, list price ×
predicted sale-to-list ratio) are two independent, leakage-free estimates of the
same thing. The pure comp CMA alone lands ~11.6% median error on Bay Area
single-family data (heterogeneous comps); the list-anchored overbid alone is
~8.1%. A backtest-tuned blend (≈20% CMA + 80% overbid) reaches ~7.6% — the whole
0.1–0.3 weight range passes the ≤8% gate, so this sits in a stable basin, not on
a knife edge. The CMA stays fully transparent in the workbench; this is just the
headline number a buyer anchors an offer on.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

CMA_WEIGHT = 0.2  # weight on the comp CMA; (1 - CMA_WEIGHT) on the overbid point


def blended_value(cma_estimate: int | None, overbid_point: int | None) -> int | None:
    """Ensemble of the CMA estimate and the overbid point. Falls back to
    whichever exists; ``None`` if neither does."""
    if cma_estimate is not None and overbid_point is not None:
        return round(CMA_WEIGHT * cma_estimate + (1 - CMA_WEIGHT) * overbid_point)
    return cma_estimate if cma_estimate is not None else overbid_point


def latest_cma_estimate(session: Session, property_id: str) -> int | None:
    from hb.db.models import CmaRun

    return session.execute(
        select(CmaRun.estimate)
        .where(CmaRun.property_id == property_id, CmaRun.estimate.is_not(None))
        .order_by(CmaRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def predicted_sale(session: Session, listing, prop, cache: dict | None = None,
                   as_of: str | None = None) -> dict | None:
    """The one `predicted_sale` payload every router serves (listings, tracker,
    detail): overbid range with the POINT blended with the latest CMA, then
    pulled toward list price when prolonged market exposure says the price was
    rejected (docs/06 §5.6 — `unadjusted_point`/`rejection_weight` expose the
    pre-adjustment value; weight 0 means untouched). None on any valuation
    failure (a broken model must never 500 a page). `cache` memoizes overbid
    sample loads and per-property CMA lookups across a page of listings."""
    from hb.engine import exposure, overbid, posture

    cache = cache if cache is not None else {}
    try:
        cma_key = ("cma_estimate", prop.id)
        if cma_key not in cache:
            cache[cma_key] = latest_cma_estimate(session, prop.id)
        cma_estimate = cache[cma_key]

        result = overbid.predict(session, listing, prop,
                                 cma_estimate=cma_estimate, as_of=as_of, cache=cache)
        if not result.predicted:
            return None
        point = blended_value(cma_estimate, result.predicted["point"])
        # a strongly divergent CMA can pull the blend outside the overbid band —
        # the served range must always contain its own point
        blended = {"low": min(result.predicted["low"], point), "point": point,
                   "high": max(result.predicted["high"], point)}

        ex = exposure.inputs(session, listing, prop, as_of, cache)
        w = posture.rejection_weight(ex.ratio, ex.offer_passed)
        list_price = posture.list_price_as_of(session, listing, as_of)
        adjusted = (posture.market_adjusted(blended, list_price, w)
                    if w > 0 and list_price else blended)
        return {**adjusted, "basis": result.basis,
                "unadjusted_point": point, "rejection_weight": round(w, 3)}
    except Exception as exc:  # noqa: BLE001
        log.warning("predicted_sale failed for listing %s: %s", listing.id, exc)
        return None
