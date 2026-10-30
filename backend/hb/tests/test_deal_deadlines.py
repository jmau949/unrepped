from datetime import date

import pytest
from sqlalchemy import func, select

from hb.db.models import Alert, AppSetting, Deal, Listing, Property
from hb.pipelines import deal_deadlines


@pytest.fixture
def deal(session):
    session.add(AppSetting(key="alert_rules", value={}))
    prop = Property(address_norm="1204 OAK AVE", zip="94070", city="San Carlos",
                    beds=3, baths=2.0, sqft=1600, year_built=1955)
    session.add(prop)
    session.flush()
    listing = Listing(property_id=prop.id, source="realtor", source_listing_id="D1",
                      status="pending", list_price=2_290_000)
    session.add(listing)
    session.flush()
    row = Deal(listing_id=listing.id, property_id=prop.id, accepted_on="2026-09-14",
               close_of_escrow_on="2026-10-14", emd_business_days=3,
               investigation_days=17, appraisal_days=17, loan_days=21)
    session.add(row)
    session.commit()
    return row


def _types(session) -> dict[str, int]:
    rows = session.execute(
        select(Alert.type, func.count()).group_by(Alert.type)
    ).all()
    return dict(rows)


def test_emits_soon_and_overdue_and_is_idempotent(engine, session, deal):
    # Day 18: the EMD (day +3) is long past and blocking; day-21 loan removal is 3 out.
    assert deal_deadlines.run(engine, today=date(2026, 10, 2)) == "ok"
    first = _types(session)
    assert first.get("deal_deadline_soon", 0) > 0
    assert first.get("deal_deadline_overdue", 0) > 0

    # Re-running the same day emits nothing new — dedup_key carries date + bucket.
    deal_deadlines.run(engine, today=date(2026, 10, 2))
    assert _types(session) == first


def test_overdue_only_fires_for_blocking_tasks(engine, session, deal):
    deal_deadlines.run(engine, today=date(2026, 10, 2))
    overdue = session.execute(
        select(Alert).where(Alert.type == "deal_deadline_overdue")
    ).scalars().all()
    assert overdue
    assert all(a.payload["blocking"] for a in overdue)


def test_completed_tasks_stop_alerting(engine, session, deal):
    deal.checklist = {t: {"done_on": "2026-09-15"} for t in
                      ("executed_contract", "record_key_dates", "wire_emd",
                       "verify_wire_instructions", "insurance_quotes_started",
                       "book_general_inspection", "loan_application_complete",
                       "loan_estimate_saved", "no_new_credit", "packet_received",
                       "prelim_title_read", "title_exceptions_pulled")}
    session.commit()

    deal_deadlines.run(engine, today=date(2026, 9, 20))
    keys = {a.payload["task"] for a in session.execute(
        select(Alert).where(Alert.type == "deal_deadline_overdue")).scalars()}
    assert "wire_emd" not in keys


def test_closed_deals_and_disabled_rules_are_skipped(engine, session, deal):
    deal.status = "closed"
    session.commit()
    assert deal_deadlines.run(engine, today=date(2026, 10, 2)) == "noop"
    assert _types(session) == {}

    deal.status = "open"
    rules = session.get(AppSetting, "alert_rules")
    rules.value = {"deal_deadline_soon": {"enabled": False},
                   "deal_deadline_overdue": {"enabled": False}}
    session.commit()
    assert deal_deadlines.run(engine, today=date(2026, 10, 2)) == "noop"
    assert _types(session) == {}


def test_waived_contingency_never_alerts(engine, session, deal):
    deal.loan_days = None
    session.commit()
    deal_deadlines.run(engine, today=date(2026, 10, 6))
    keys = {a.payload["task"] for a in session.execute(select(Alert)).scalars()}
    assert "remove_loan" not in keys
    assert "clear_to_close" not in keys
