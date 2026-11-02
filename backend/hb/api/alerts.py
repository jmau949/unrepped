"""Alerts endpoints — docs/07-api-spec.md §Alerts."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from hb.alerts.channels import format_alert
from hb.db.engine import make_session
from hb.db.models import Alert, AppSetting, utcnow_iso

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    unread_only: bool = False,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> list[dict]:
    with make_session() as session:
        stmt = select(Alert)
        if unread_only:
            stmt = stmt.where(Alert.read_at.is_(None))
        stmt = stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
        return [
            {
                "id": a.id,
                "type": a.type,
                "message": format_alert(session, a),
                "listing_id": a.listing_id,
                "payload": a.payload,
                "created_at": a.created_at,
                "read_at": a.read_at,
                "delivered_at": a.delivered_at,
                "channel": a.channel,
            }
            for a in rows
        ]


def _mark_read(alert: Alert, now: str) -> None:
    """Opening an alert in the inbox reads it — and counts as delivery when no
    channel has run yet, so the hourly `hb alerts send` never toasts or pushes
    something the buyer has already seen (docs/09 §4)."""
    if alert.read_at is None:
        alert.read_at = now
    if alert.delivered_at is None:
        alert.delivered_at = now
        alert.channel = "ui"


@router.post("/read-all")
def read_all() -> dict:
    with make_session() as session:
        unread = session.execute(select(Alert).where(Alert.read_at.is_(None))).scalars().all()
        now = utcnow_iso()
        for alert in unread:
            _mark_read(alert, now)
        session.commit()
        return {"marked": len(unread)}


@router.post("/{alert_id}/read")
def read(alert_id: str) -> dict:
    with make_session() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(404, "alert not found")
        if alert.read_at is None:
            _mark_read(alert, utcnow_iso())
            session.commit()
        return {"id": alert.id, "read_at": alert.read_at}


@router.get("/rules")
def get_rules() -> dict:
    with make_session() as session:
        row = session.get(AppSetting, "alert_rules")
        return row.value if row else {}


@router.put("/rules")
def put_rules(rules: dict) -> dict:
    with make_session() as session:
        row = session.get(AppSetting, "alert_rules")
        if row is None:
            raise HTTPException(500, "alert_rules settings row missing")
        row.value = {**row.value, **rules}
        row.updated_at = utcnow_iso()
        session.commit()
        return row.value
