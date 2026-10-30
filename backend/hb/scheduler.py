"""The hourly check inside `hb serve` (docs/05 §2).

While the app is open it does what the OS schedule does every hour: run each
catch-up job whose latest slot has no run yet, then deliver pending alerts. It is
a second line, not the schedule — the OS jobs from `hb schedule install` run
whether or not the app is open — but it covers a machine whose schedule never
got installed, and costs two queries an hour when everything is current.
`needs_run` treats a run in flight as served, so this never starts a job an OS
timer began minutes earlier. HB_SERVE_SCHEDULER=false turns it off (the home
server: its systemd timers run the jobs).
"""

from __future__ import annotations

import logging
import threading

from hb.config import settings

log = logging.getLogger(__name__)

INITIAL_DELAY_S = 60.0  # let the server come up first
INTERVAL_S = 3600.0


def tick(engine=None) -> list[str]:
    """One hourly pass; returns the catch-up jobs it ran."""
    from hb.alerts.channels import deliver_pending
    from hb.db.backup import backup_db
    from hb.db.engine import make_session
    from hb.pipelines import run_daily, run_job
    from hb.pipelines.raw_cache import prune_raw
    from hb.pipelines.schedule import needs_run

    with make_session(engine) as session:
        due = {name: needs_run(session, name) for name in ("daily", "listing-scan")}
    ran: list[str] = []
    if due["daily"]:
        log.info("scheduler: the daily slot has no run yet — running the daily sequence")
        for job, status in run_daily(engine).items():
            log.info("scheduler: %s: %s", job, status)
        for tail in (backup_db, prune_raw):  # the same tail `hb pipeline daily` runs
            try:
                tail()
            except Exception:  # noqa: BLE001 — a backup or prune failure never stops the loop
                log.exception("scheduler: %s failed", tail.__name__)
        ran.append("daily")
    if due["listing-scan"]:
        log.info("scheduler: the scan slot has no run yet — running listing-scan")
        log.info("scheduler: listing-scan: %s", run_job("listing-scan", engine))
        ran.append("listing-scan")
    with make_session(engine) as session:
        delivered = deliver_pending(session)
    if delivered:
        log.info("scheduler: delivered %d alert(s)", delivered)
    return ran


class Scheduler:
    def __init__(self, engine=None) -> None:
        self.engine = engine
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="hb-scheduler", daemon=True)

    def start(self) -> Scheduler:
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(INITIAL_DELAY_S)
        while not self._stop.is_set():
            try:
                tick(self.engine)
            except Exception:  # noqa: BLE001 — the next hour gets another go
                log.exception("scheduler: hourly check failed")
            self._stop.wait(INTERVAL_S)


def start(engine=None) -> Scheduler | None:
    """Start the hourly check in a daemon thread, unless HB_SERVE_SCHEDULER is off."""
    if not settings.serve_scheduler:
        log.info("scheduler: off (HB_SERVE_SCHEDULER=false); the OS schedule runs the jobs")
        return None
    log.info("scheduler: hourly catch-up check on while the server runs "
             "(HB_SERVE_SCHEDULER=false turns it off)")
    return Scheduler(engine).start()
