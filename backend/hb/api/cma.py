"""CMA endpoints — docs/07-api-spec.md §CMA.

`run` produces a transparent, line-item CMA; the two PATCH routes (comp toggle
and adjustment override) recompute over the curated comp set and persist a
**new** run so history is never lost.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from hb.db.engine import make_session
from hb.db.models import CmaComp, CmaRun, Property, Sale
from hb.engine import cma
from hb.geo import haversine_miles

router = APIRouter(prefix="/api/cma", tags=["cma"])


class RunRequest(BaseModel):
    property_id: str
    params: dict | None = None


class CompToggle(BaseModel):
    sale_id: str
    included: bool


class AdjustmentOverride(BaseModel):
    sale_id: str
    overrides: dict


def _subject_block(session, property_id: str) -> dict | None:
    p = session.get(Property, property_id)
    if p is None:
        return None
    return {"property_id": p.id, "address": p.address_norm.title(), "lat": p.lat,
            "lon": p.lon, "sqft": p.sqft, "beds": p.beds, "baths": p.baths}


def _serialize(session, result: cma.CmaResult) -> dict:
    return {
        "id": result.params.get("cma_run_id"),
        "property_id": result.property_id,
        "subject": _subject_block(session, result.property_id),
        "estimate": result.estimate,
        "low": result.low,
        "high": result.high,
        "confidence": result.confidence,
        "confidence_reasons": result.confidence_reasons,
        "index_source": result.index_source,
        "as_of": result.as_of,
        "comps": [
            {
                "sale_id": c.sale_id, "address": c.address, "sale_date": c.sale_date,
                "sale_price": c.sale_price, "distance_mi": c.distance_mi, "lat": c.lat,
                "lon": c.lon, "beds": c.beds, "baths": c.baths, "sqft": c.sqft,
                "condition_tag": c.condition_tag, "similarity_score": c.similarity_score,
                "auto_selected": c.auto_selected, "included": c.included,
                "time_adj_factor": c.time_adj_factor, "adjustments": c.adjustments,
                "adjusted_price": c.adjusted_price,
            }
            for c in result.comps
        ],
    }


def _specs_for_run(session, run_id: str) -> tuple[list[dict], str]:
    run = session.get(CmaRun, run_id)
    if run is None:
        raise HTTPException(404, "cma run not found")
    comps = session.execute(
        select(CmaComp).where(CmaComp.cma_run_id == run_id)
    ).scalars().all()
    specs = [
        {"sale_id": c.sale_id, "included": c.included, "auto_selected": c.auto_selected,
         "overrides": (c.adjustments or {}).get("_overrides", {})}
        for c in comps
    ]
    return specs, run.property_id


@router.post("/run")
def run_cma(req: RunRequest) -> dict:
    with make_session() as session:
        if session.get(Property, req.property_id) is None:
            raise HTTPException(404, "property not found")
        return _serialize(session, cma.run(session, req.property_id, req.params))


@router.patch("/runs/{run_id}/comps")
def toggle_comp(run_id: str, body: CompToggle) -> dict:
    with make_session() as session:
        specs, property_id = _specs_for_run(session, run_id)
        if not any(s["sale_id"] == body.sale_id for s in specs):
            raise HTTPException(404, "sale not in run")
        for s in specs:
            if s["sale_id"] == body.sale_id:
                s["included"] = body.included
        return _serialize(session, cma.recompute(session, property_id, specs))


@router.patch("/runs/{run_id}/adjustments")
def override_adjustment(run_id: str, body: AdjustmentOverride) -> dict:
    with make_session() as session:
        specs, property_id = _specs_for_run(session, run_id)
        if not any(s["sale_id"] == body.sale_id for s in specs):
            raise HTTPException(404, "sale not in run")
        for s in specs:
            if s["sale_id"] == body.sale_id:
                s["overrides"] = {**s["overrides"], **body.overrides}
        return _serialize(session, cma.recompute(session, property_id, specs))


def _serialize_stored(session, run: CmaRun) -> dict:
    """Reconstruct a `CmaRun` response from persisted rows (history selection)."""
    subject = session.get(Property, run.property_id)
    rows = session.execute(
        select(CmaComp, Sale, Property)
        .join(Sale, CmaComp.sale_id == Sale.id)
        .join(Property, Sale.property_id == Property.id)
        .where(CmaComp.cma_run_id == run.id)
    ).all()
    comps = []
    for cc, sale, prop in rows:
        dist = (round(haversine_miles(subject.lat, subject.lon, prop.lat, prop.lon), 3)
                if subject and subject.lat and prop.lat else None)
        adj = {k: (cc.adjustments or {}).get(k, 0)
               for k in ("time", "sqft", "baths", "lot", "condition")}
        comps.append({
            "sale_id": cc.sale_id,
            "address": f"{prop.address_norm.title()}{' #' + prop.unit if prop.unit else ''}",
            "sale_date": sale.sale_date, "sale_price": sale.sale_price, "distance_mi": dist,
            "lat": prop.lat, "lon": prop.lon, "beds": prop.beds, "baths": prop.baths,
            "sqft": prop.sqft, "condition_tag": prop.condition_tag,
            "similarity_score": cc.similarity_score, "auto_selected": cc.auto_selected,
            "included": cc.included, "time_adj_factor": cc.time_adj_factor,
            "adjustments": adj, "adjusted_price": cc.adjusted_price,
        })
    comps.sort(key=lambda c: (not c["included"], -c["similarity_score"]))
    return {
        "id": run.id, "property_id": run.property_id,
        "subject": _subject_block(session, run.property_id),
        "estimate": run.estimate, "low": run.low, "high": run.high,
        "confidence": run.confidence,
        "confidence_reasons": (run.params or {}).get("confidence_reasons", []),
        "index_source": run.index_source, "as_of": run.created_at[:10], "comps": comps,
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    with make_session() as session:
        run = session.get(CmaRun, run_id)
        if run is None:
            raise HTTPException(404, "cma run not found")
        return _serialize_stored(session, run)


@router.get("/runs")
def run_history(property_id: str = Query(...)) -> list[dict]:
    with make_session() as session:
        runs = session.execute(
            select(CmaRun).where(CmaRun.property_id == property_id)
            .order_by(CmaRun.created_at.desc())
        ).scalars().all()
        # one grouped count (runs grow with every workbench edit — N+1 compounds)
        counts = dict(session.execute(
            select(CmaComp.cma_run_id, func.count())
            .where(CmaComp.cma_run_id.in_([r.id for r in runs]))
            .group_by(CmaComp.cma_run_id)
        ).all()) if runs else {}
        return [{"id": r.id, "created_at": r.created_at, "estimate": r.estimate,
                 "low": r.low, "high": r.high, "confidence": r.confidence,
                 "index_source": r.index_source, "n_comps": counts.get(r.id, 0)}
                for r in runs]
