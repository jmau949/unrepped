"""deal-deadlines pipeline — docs/05-pipelines.md §15.

Walks every open deal, recomputes its schedule with `hb.closing_spec`, and emits
`deal_deadline_soon` / `deal_deadline_overdue` alerts (docs/09).

Daily-safe by construction: pure DB read, no network, and every alert carries a
dedup_key including the due date and the bucket, so re-running the same day emits
nothing new. Runs in DAILY_SEQUENCE because a missed contingency date is the one
failure mode in this product that costs real money (docs/14 §4) — it must not
depend on the user opening the page.

Only unfinished, un-waived tasks alert, and only `blocking` tasks alert once
overdue: the point is to shout about the deposit, not to nag about registering
appliance warranties.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from hb import closing_spec
from hb.db.models import Alert, AppSetting, Deal, Property, TrackedListing
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

# Same shape as OFFER_BUCKETS in hb/alerts/rules.py — smallest matching bucket wins,
# else the 3-day key dedups the 1-day alert away.
DEADLINE_BUCKETS = [3, 1]


def _enabled(session, name: str) -> bool:
    row = session.get(AppSetting, "alert_rules")
    rules = row.value if row else {}
    return rules.get(name, {}).get("enabled", True)


def _insert(session, **values) -> bool:
    stmt = sqlite_insert(Alert).values(**values).on_conflict_do_nothing(
        index_elements=["dedup_key"]
    )
    return session.execute(stmt).rowcount > 0


def run(engine: Engine | None = None, today: date | None = None) -> str:
    today = today or date.today()
    with JobRunner("deal-deadlines", engine) as runner:
        session = runner.session
        soon_on = _enabled(session, "deal_deadline_soon")
        overdue_on = _enabled(session, "deal_deadline_overdue")

        deals = [] if not (soon_on or overdue_on) else session.execute(
            select(Deal).where(Deal.status == "open")
        ).scalars().all()

        for deal in deals:
            with runner.item(deal.id):
                prop = session.get(Property, deal.property_id)
                facts = {"year_built": prop.year_built, "city": prop.city} if prop else {}
                payload_base = {"deal_id": deal.id,
                                "address": prop.address_norm if prop else None}
                tracked = session.execute(
                    select(TrackedListing.id).where(
                        TrackedListing.listing_id == deal.listing_id)
                ).scalar_one_or_none()

                rollup = closing_spec.evaluate(
                    _as_dict(deal), deal.checklist or {}, facts, today=today,
                    soon_days=max(DEADLINE_BUCKETS),
                )

                if soon_on:
                    for task in rollup["due_soon"]:
                        days_left = (date.fromisoformat(task["due_on"]) - today).days
                        bucket = next(
                            (b for b in sorted(DEADLINE_BUCKETS) if 0 <= days_left <= b),
                            None,
                        )
                        if bucket is None:
                            continue
                        runner.events_emitted += _insert(
                            session, type="deal_deadline_soon",
                            listing_id=deal.listing_id, tracked_listing_id=tracked,
                            dedup_key=(f"deal_deadline_soon:{deal.id}:{task['key']}"
                                       f":{task['due_on']}:{bucket}"),
                            payload={**payload_base, "task": task["key"],
                                     "label": task["label"], "due": task["due_on"],
                                     "days_left": days_left,
                                     "blocking": task["blocking"]},
                        )

                if overdue_on:
                    for task in rollup["overdue"]:
                        # Only blocking tasks are worth an overdue alert.
                        if not task["blocking"]:
                            continue
                        runner.events_emitted += _insert(
                            session, type="deal_deadline_overdue",
                            listing_id=deal.listing_id, tracked_listing_id=tracked,
                            dedup_key=(f"deal_deadline_overdue:{deal.id}:{task['key']}"
                                       f":{task['due_on']}"),
                            payload={**payload_base, "task": task["key"],
                                     "label": task["label"], "due": task["due_on"],
                                     "blocking": True},
                        )

        session.commit()
        # Nothing open (or both rules off) is a genuine no-op, not a silent success.
        if not deals:
            runner.mark_noop()
    return runner.status


def _as_dict(deal: Deal) -> dict:
    """The contract numbers closing_spec needs. Mirrors hb/api/deals.py::_deal_dict."""
    return {
        "accepted_on": deal.accepted_on,
        "close_of_escrow_on": deal.close_of_escrow_on,
        "emd_business_days": deal.emd_business_days,
        "investigation_days": deal.investigation_days,
        "appraisal_days": deal.appraisal_days,
        "loan_days": deal.loan_days,
        "financed": bool(deal.financed),
    }
