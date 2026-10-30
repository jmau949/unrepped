import pytest
from sqlalchemy import func, select

from hb.db.models import PipelineRun, RateSnapshot
from hb.pipelines import fred


def _patch(monkeypatch, observations):
    monkeypatch.setattr(fred, "fetch_observations", lambda sid, since: observations[sid])
    monkeypatch.setattr(fred.settings, "fred_api_key", "test-key")


OBS = {
    "MORTGAGE30US": [
        {"date": "2026-07-02", "value": "6.72"},
        {"date": "2026-07-09", "value": "6.68"},
        {"date": "2026-07-16", "value": "."},  # placeholder — skipped
    ],
    "MORTGAGE15US": [{"date": "2026-07-09", "value": "5.91"}],
    "SFXRSA": [{"date": "2026-04-01", "value": "412.3"}],
}


def test_upserts_and_series_mapping(engine, session, monkeypatch):
    _patch(monkeypatch, OBS)
    assert fred.run(engine) == "ok"

    rows = session.execute(select(RateSnapshot)).scalars().all()
    assert len(rows) == 4  # placeholder skipped
    assert {r.series for r in rows} == {"MORTGAGE30US", "MORTGAGE15US", "CASESHILLER"}


def test_rerun_is_idempotent(engine, session, monkeypatch):
    _patch(monkeypatch, OBS)
    fred.run(engine)
    fred.run(engine)
    n = session.execute(select(func.count()).select_from(RateSnapshot)).scalar_one()
    assert n == 4


def test_missing_key_skips_without_failing(engine, session, monkeypatch):
    """The key is optional (affordability falls back to a 6.5% rate), so a run
    without one is a noop, not a daily failure — and never touches the network."""
    monkeypatch.setattr(fred.settings, "fred_api_key", "")
    monkeypatch.setattr(fred, "fetch_observations", lambda *a: pytest.fail("fetched"))
    assert fred.run(engine) == "noop"
    run_row = session.execute(select(PipelineRun)).scalar_one()
    assert run_row.status == "noop" and run_row.error_summary is None
    assert session.execute(select(func.count()).select_from(RateSnapshot)).scalar_one() == 0
