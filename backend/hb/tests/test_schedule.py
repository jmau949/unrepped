from datetime import datetime, timezone

import pytest

from hb.config import settings
from hb.db.models import PipelineRun
from hb.pipelines import schedule

LA = "America/Los_Angeles"


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def slots(monkeypatch):
    monkeypatch.setattr(settings, "scan_times", ["05:00", "15:00"])
    monkeypatch.setattr(settings, "daily_times", ["04:00"])


def _run(session, job, started, status="ok"):
    stamp = started.isoformat(timespec="seconds")
    session.add(PipelineRun(job=job, started_at=stamp, finished_at=stamp, status=status))
    session.commit()


def test_latest_slot_same_day_previous_day_and_dst():
    # 10:00 PDT -> today's 05:00 PDT (12:00Z)
    assert schedule.latest_slot(["05:00", "15:00"], _utc(2026, 10, 24, 17), LA) == \
        _utc(2026, 10, 24, 12)
    # 02:00 PDT -> yesterday's 15:00 PDT
    assert schedule.latest_slot(["05:00", "15:00"], _utc(2026, 10, 24, 9), LA) == \
        _utc(2026, 10, 23, 22)
    # after the fall-back: 05:00 PST is 13:00Z
    assert schedule.latest_slot(["05:00"], _utc(2026, 11, 2, 18), LA) == _utc(2026, 11, 2, 13)


def test_a_run_in_flight_counts_as_served_until_it_is_stale(session):
    """The hourly check inside `hb serve` and an OS timer must never start the
    same job twice: a `running` row younger than IN_PROGRESS_GRACE means wait;
    older, the process died hard and the slot is retried."""
    now = _utc(2026, 10, 24, 13)  # 06:00 PDT, slot 05:00 PDT (12:00Z)
    assert schedule.needs_run(session, "listing-scan", now)
    _run(session, "listing-scan", _utc(2026, 10, 24, 12, 30), status="running")
    assert not schedule.needs_run(session, "listing-scan", now)
    assert schedule.needs_run(session, "listing-scan", _utc(2026, 10, 24, 16))  # 3.5 h: stale

    # the daily sequence shows as `running` rows of its member jobs, not of deal-deadlines
    _run(session, "redfin-market", _utc(2026, 10, 24, 11, 10), status="running")  # 04:10 PDT
    assert not schedule.needs_run(session, "daily", _utc(2026, 10, 24, 11, 30))


def test_needs_run_until_a_completed_run_lands(session):
    now = _utc(2026, 10, 24, 13)  # 06:00 PDT, slot 05:00 PDT
    assert schedule.needs_run(session, "listing-scan", now)
    _run(session, "listing-scan", _utc(2026, 10, 24, 12, 30), status="failed")
    assert schedule.needs_run(session, "listing-scan", now)  # a failed scan is retried
    _run(session, "listing-scan", _utc(2026, 10, 24, 11, 59))  # before the slot
    assert schedule.needs_run(session, "listing-scan", now)
    _run(session, "listing-scan", _utc(2026, 10, 24, 12, 45), status="partial")
    assert not schedule.needs_run(session, "listing-scan", now)


def test_daily_is_served_by_its_last_job_even_when_failed(session):
    now = _utc(2026, 10, 24, 12)  # 05:00 PDT, slot 04:00 PDT
    assert schedule.needs_run(session, "daily", now)
    _run(session, "deal-deadlines", _utc(2026, 10, 24, 11, 20), status="failed")
    assert not schedule.needs_run(session, "daily", now)


def test_overdue_waits_out_the_grace_then_flags_the_missed_slot(session):
    _run(session, "listing-scan", _utc(2026, 10, 23, 22, 1))  # yesterday 15:00 PDT served
    # 05:30 PDT: inside the grace for the 05:00 slot, and yesterday's landed -> fine
    assert schedule.overdue_since(session, "listing-scan", _utc(2026, 10, 24, 12, 30)) is None
    # 08:00 PDT and still nothing for 05:00 -> overdue since that slot
    assert schedule.overdue_since(session, "listing-scan", _utc(2026, 10, 24, 15)) == \
        _utc(2026, 10, 24, 12)
    _run(session, "listing-scan", _utc(2026, 10, 24, 15, 5))
    assert schedule.overdue_since(session, "listing-scan", _utc(2026, 10, 24, 16)) is None
