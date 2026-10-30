"""Alerts endpoints — docs/07-api-spec.md §Alerts."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from hb.alerts.channels import format_alert
from hb.db.engine import make_session
from hb.db.models import Alert, AppSetting, utcnow_iso

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    undelivered_only: bool = False,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> list[dict]:
    with make_session() as session:
        stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        if undelivered_only:
            stmt = stmt.where(Alert.delivered_at.is_(None))
        rows = session.execute(stmt).scalars().all()
        return [
            {
                "id": a.id,
                "type": a.type,
                "message": format_alert(session, a),
                "listing_id": a.listing_id,
                "payload": a.payload,
                "created_at": a.created_at,
                "delivered_at": a.delivered_at,
                "channel": a.channel,
            }
            for a in rows
        ]


@router.post("/{alert_id}/ack")
def ack(alert_id: str) -> dict:
    with make_session() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(404, "alert not found")
        if alert.delivered_at is None:
            alert.delivered_at = utcnow_iso()
            alert.channel = (alert.channel + ",ui") if alert.channel else "ui"
            session.commit()
        return {"id": alert.id, "delivered_at": alert.delivered_at}


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
