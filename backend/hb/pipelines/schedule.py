"""Slot-based catch-up for the scheduled jobs — docs/05-pipelines.md §2.

The OS scheduler fires every hour; `hb pipeline <job> --catch-up` asks here
whether the job's most recent slot (settings.scan_times / daily_times, local
wall-clock) already has a completed run. A missed slot (machine asleep, crash,
a run that died before `hb` started) is therefore retried within the hour,
and the health endpoint reports the job stale until it lands.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import PipelineRun

# A slot counts as served by a run of `job` started at/after it whose status is
# one of `statuses`. listing-scan retries a failed run; the daily sequence is
# served once its last job ran at all (one broken upstream must not re-run the
# whole bulk sequence every hour).
CATCH_UP = {
    "listing-scan": {"job": "listing-scan", "slots": "scan_times",
                     "statuses": ("ok", "partial", "noop")},
    "daily": {"job": "deal-deadlines", "slots": "daily_times",
              "statuses": ("ok", "partial", "noop", "failed")},
}
STALE_GRACE = timedelta(hours=2)  # a scan runs ~20-35 min; 2 h = genuinely missed
# A `running` row younger than this is a run in flight (a first scan's photo tail
# can take an hour or more); older, the process died hard and the slot is retried.
IN_PROGRESS_GRACE = timedelta(hours=3)


def latest_slot(slots: list[str], now: datetime, tz_name: str | None = None) -> datetime:
    """The most recent slot at or before `now`, as aware UTC."""
    tz = ZoneInfo(tz_name or settings.timezone)
    local_now = now.astimezone(tz)
    candidates = []
    for days_back in (0, 1):
        day = local_now.date() - timedelta(days=days_back)
        for hhmm in slots:
            hh, mm = (int(x) for x in hhmm.split(":"))
            candidates.append(datetime.combine(day, time(hh, mm), tzinfo=tz))
    return max(c for c in candidates if c <= local_now).astimezone(timezone.utc)


def _served(session: Session, job: str, statuses, since: datetime) -> bool:
    return session.execute(
        select(PipelineRun.id).where(
            PipelineRun.job == job,
            PipelineRun.status.in_(statuses),
            PipelineRun.started_at >= since.isoformat(timespec="seconds"),
        ).limit(1)
    ).first() is not None


def _in_flight(session: Session, jobs: tuple[str, ...], since: datetime) -> bool:
    return session.execute(
        select(PipelineRun.id).where(
            PipelineRun.job.in_(jobs),
            PipelineRun.status == "running",
            PipelineRun.started_at >= since.isoformat(timespec="seconds"),
        ).limit(1)
    ).first() is not None


def _jobs_of(name: str) -> tuple[str, ...]:
    """The pipeline_runs job names a run of `name` writes while it is in flight."""
    if name == "daily":
        from hb.pipelines import DAILY_SEQUENCE  # lazy: hb.pipelines imports the job modules

        return tuple(DAILY_SEQUENCE)
    return (CATCH_UP[name]["job"],)


def needs_run(session: Session, name: str, now: datetime | None = None) -> bool:
    """True when `name`'s latest slot has no completed run yet and none is in
    flight — the hourly check inside `hb serve` and an OS timer must never start
    the same job twice (a `running` row younger than IN_PROGRESS_GRACE)."""
    now = now or datetime.now(timezone.utc)
    spec = CATCH_UP[name]
    slot = latest_slot(getattr(settings, spec["slots"]), now)
    if _served(session, spec["job"], spec["statuses"], slot):
        return False
    return not _in_flight(session, _jobs_of(name), now - IN_PROGRESS_GRACE)


def overdue_since(session: Session, name: str, now: datetime | None = None) -> datetime | None:
    """The missed slot (aware UTC) when `name` is more than STALE_GRACE past
    its latest slot without a completed run, else None."""
    now = now or datetime.now(timezone.utc)
    spec = CATCH_UP[name]
    slot = latest_slot(getattr(settings, spec["slots"]), now)
    if now - slot < STALE_GRACE:
        # too early to judge this slot; the previous one must have landed
        slot = latest_slot(getattr(settings, spec["slots"]), slot - timedelta(seconds=1))
    return None if _served(session, spec["job"], spec["statuses"], slot) else slot
