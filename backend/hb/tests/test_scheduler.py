"""hb/scheduler — the hourly catch-up check inside `hb serve` (docs/05 §2)."""

import time

from hb import scheduler
from hb.config import settings


def test_tick_runs_only_the_jobs_whose_slot_is_unserved(engine, monkeypatch):
    import hb.pipelines as pipelines
    from hb.pipelines import schedule

    monkeypatch.setattr(schedule, "needs_run", lambda session, name, now=None: name == "listing-scan")
    ran: list[str] = []
    monkeypatch.setattr(pipelines, "run_job", lambda name, engine=None: ran.append(name) or "ok")
    monkeypatch.setattr(pipelines, "run_daily", lambda engine=None: ran.append("daily") or {})
    monkeypatch.setattr("hb.alerts.channels.deliver_pending", lambda session: 0)

    assert scheduler.tick(engine) == ["listing-scan"]
    assert ran == ["listing-scan"]


def test_tick_runs_the_daily_sequence_with_its_tail(engine, monkeypatch):
    import hb.db.backup as backup
    import hb.pipelines as pipelines
    import hb.pipelines.raw_cache as raw_cache
    from hb.pipelines import schedule

    monkeypatch.setattr(schedule, "needs_run", lambda session, name, now=None: name == "daily")
    seen: list[str] = []
    monkeypatch.setattr(pipelines, "run_daily",
                        lambda engine=None: seen.append("daily") or {"fred": "ok"})
    monkeypatch.setattr(pipelines, "run_job", lambda name, engine=None: seen.append(name) or "ok")
    monkeypatch.setattr(backup, "backup_db", lambda: seen.append("backup"))
    monkeypatch.setattr(raw_cache, "prune_raw", lambda: seen.append("prune"))
    monkeypatch.setattr("hb.alerts.channels.deliver_pending", lambda session: 0)

    assert scheduler.tick(engine) == ["daily"]
    assert seen == ["daily", "backup", "prune"]  # no listing-scan: its slot was served


def test_switched_off_by_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "serve_scheduler", False)
    assert scheduler.start() is None


def test_thread_ticks_on_its_interval_and_stops(monkeypatch):
    ticks: list[int] = []
    monkeypatch.setattr(scheduler, "INITIAL_DELAY_S", 0.0)
    monkeypatch.setattr(scheduler, "INTERVAL_S", 0.01)
    monkeypatch.setattr(scheduler, "tick", lambda engine=None: ticks.append(1))
    monkeypatch.setattr(settings, "serve_scheduler", True)

    running = scheduler.start()
    deadline = time.monotonic() + 2
    while len(ticks) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    running.stop()
    running.thread.join(timeout=1)
    assert len(ticks) >= 2 and not running.thread.is_alive()


def test_a_failing_tick_does_not_kill_the_loop(monkeypatch):
    calls: list[int] = []

    def flaky(engine=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("upstream down")

    monkeypatch.setattr(scheduler, "INITIAL_DELAY_S", 0.0)
    monkeypatch.setattr(scheduler, "INTERVAL_S", 0.01)
    monkeypatch.setattr(scheduler, "tick", flaky)
    monkeypatch.setattr(settings, "serve_scheduler", True)

    running = scheduler.start()
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    running.stop()
    running.thread.join(timeout=1)
    assert len(calls) >= 2
