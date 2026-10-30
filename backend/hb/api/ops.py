"""Ops endpoints (docs/07-api-spec.md §Ops): health + pipeline-run history."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, text

from hb.db.engine import make_session
from hb.db.models import PipelineRun

router = APIRouter(prefix="/api/ops", tags=["ops"])


class Health(BaseModel):
    db: str
    last_scan: str | None  # finished_at of the last completed (ok/partial/noop) listing-scan
    # the scheduled scan slot (UTC ISO) that is >2 h past with no completed
    # scan — set means the listings are stale; null = on schedule
    scan_overdue_since: str | None
    rentcast_quota_remaining: int | None


class PipelineRunOut(BaseModel):
    id: str
    job: str
    started_at: str
    finished_at: str | None
    status: str
    items_seen: int
    items_upserted: int
    events_emitted: int
    error_summary: str | None


@router.get("/health", response_model=Health)
def health() -> Health:
    with make_session() as session:
        migrated = session.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_runs'"
        )).scalar_one_or_none()
        if not migrated:
            # a fresh clone before `hb serve` / `hb db upgrade`: say so instead of
            # erroring on the first missing table
            return Health(db="unmigrated", last_scan=None, scan_overdue_since=None,
                          rentcast_quota_remaining=None)

        from hb.pipelines.schedule import CATCH_UP, overdue_since

        last_scan = session.execute(
            select(PipelineRun.finished_at)
            .where(PipelineRun.job == "listing-scan", PipelineRun.finished_at.is_not(None),
                   PipelineRun.status.in_(CATCH_UP["listing-scan"]["statuses"]))
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        overdue = overdue_since(session, "listing-scan")

        from hb.pipelines.enrich import rentcast_quota
        quota = rentcast_quota(session)  # month-aware; None when RentCast is not configured

    return Health(db="ok", last_scan=last_scan,
                  scan_overdue_since=overdue.isoformat(timespec="seconds") if overdue else None,
                  rentcast_quota_remaining=quota)


@router.get("/pipeline-runs", response_model=list[PipelineRunOut])
def pipeline_runs(
    job: str | None = Query(default=None),
    limit: int = Query(default=20, le=200),
) -> list[PipelineRunOut]:
    with make_session() as session:
        stmt = select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
        if job:
            stmt = stmt.where(PipelineRun.job == job)
        rows = session.execute(stmt).scalars().all()
    return [PipelineRunOut.model_validate(r, from_attributes=True) for r in rows]
