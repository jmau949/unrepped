"""Watchlist endpoints — docs/07-api-spec.md §Watchlist."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hb import watchlist
from hb.db.engine import make_session
from hb.db.models import AppSetting, Property, utcnow_iso

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

SEEN_KEY = "watchlist_seen"


class WatchPatch(BaseModel):
    watching: bool


@router.get("")
def list_watched() -> dict:
    with make_session() as session:
        seen = session.get(AppSetting, SEEN_KEY)
        return {
            "last_seen_at": (seen.value or {}).get("at") if seen else None,
            "items": watchlist.rows(session),
        }


@router.post("/seen")
def mark_seen() -> dict:
    """Stamp the buyer's visit; the next GET compares changes against it."""
    with make_session() as session:
        now = utcnow_iso()
        row = session.get(AppSetting, SEEN_KEY)
        previous = (row.value or {}).get("at") if row else None
        if row is None:
            session.add(AppSetting(key=SEEN_KEY, value={"at": now}))
        else:
            row.value = {"at": now}
            row.updated_at = now
        session.commit()
        return {"previous": previous, "at": now}


@router.patch("/{property_id}")
def patch_watched(property_id: str, patch: WatchPatch) -> dict:
    with make_session() as session:
        prop = session.get(Property, property_id)
        if prop is None:
            raise HTTPException(404, "property not found")
        watchlist.set_watching(prop, patch.watching)
        session.commit()
        return {"property_id": prop.id, "watching": watchlist.is_watching(prop)}
