"""Preparation checklist endpoints — docs/07-api-spec.md §Prep.

State lives in the `settings` KV row `prep_checklist` rather than a new table: you get
pre-approved once, not once per house, so there is nothing to key a table on. Same
recompute-on-read contract as tours and deals — the roll-up is never stored, so a spec
edit immediately re-scores an existing checklist.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from hb import prep_spec
from hb.db.engine import make_session
from hb.db.models import AppSetting, utcnow_iso

router = APIRouter(prefix="/api/prep", tags=["prep"])

SETTING_KEY = "prep_checklist"


class PrepPatch(BaseModel):
    checklist: dict


def _load(session) -> dict:
    row = session.get(AppSetting, SETTING_KEY)
    return (row.value if row else {}) or {}


def _out(checklist: dict) -> dict:
    return {**prep_spec.spec_for(checklist), "rollup": prep_spec.evaluate(checklist)}


@router.get("")
def get_prep() -> dict:
    with make_session() as session:
        return _out(_load(session))


@router.patch("")
def patch_prep(patch: PrepPatch) -> dict:
    """Merge, at both levels — same semantics as the deal and tour checklists."""
    with make_session() as session:
        row = session.execute(
            select(AppSetting).where(AppSetting.key == SETTING_KEY)
        ).scalar_one_or_none()
        if row is None:
            row = AppSetting(key=SETTING_KEY, value={})
            session.add(row)

        known = {t.key for t in prep_spec.tasks_for()}
        merged = {**(row.value or {})}
        for key, value in patch.checklist.items():
            if key not in known:
                raise HTTPException(422, f"unknown task key: {key}")
            if value is None:
                merged.pop(key, None)
                continue
            prior = merged.get(key)
            merged[key] = {**prior, **value} if isinstance(prior, dict) \
                and isinstance(value, dict) else value

        # JSON columns are not mutation-tracked — reassign rather than mutate.
        row.value = merged
        row.updated_at = utcnow_iso()
        session.commit()
        return _out(merged)
