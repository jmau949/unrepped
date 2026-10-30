from datetime import date, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from hb.cli import app
from hb.db.models import PipelineRun

runner = CliRunner()


def test_pipeline_daily_writes_one_run_per_job(engine, session, monkeypatch, tmp_path):
    import hb.db.engine as engine_module
    import hb.pipelines as pipelines
    import hb.pipelines.base as base
    from hb import config

    monkeypatch.setattr(base, "get_engine", lambda: engine)
    monkeypatch.setattr(engine_module, "_engine", engine)
    # the command's tail backs up and prunes under data_dir — keep it off the live data/
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    # replace implemented jobs with stubs — no network in tests
    for job in pipelines.DAILY_SEQUENCE:
        monkeypatch.setitem(pipelines.JOBS, job, pipelines._stub(job))

    result = runner.invoke(app, ["pipeline", "daily"])
    assert result.exit_code == 0

    rows = session.execute(select(PipelineRun)).scalars().all()
    assert len(rows) == len(pipelines.DAILY_SEQUENCE)
    assert {r.job for r in rows} == set(pipelines.DAILY_SEQUENCE)
    assert all(r.status == "failed" for r in rows)  # stubbed for the test


def test_pipelines_create_the_schema_on_a_fresh_database(monkeypatch, tmp_path):
    """`make load` runs before the app has ever served on a fresh clone: the
    first pipeline command must build the schema itself instead of failing with
    'no such table: pipeline_runs'."""
    import hb.db.engine as engine_module
    import hb.pipelines as pipelines
    from hb import config
    from hb.db.engine import make_engine

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(engine_module, "_engine", None)  # a brand-new process
    for job in pipelines.DAILY_SEQUENCE:
        monkeypatch.setitem(pipelines.JOBS, job, pipelines._stub(job))
    assert not (tmp_path / "hb.sqlite3").exists()

    result = runner.invoke(app, ["pipeline", "daily"])
    assert result.exit_code == 0, result.output

    fresh = make_engine(tmp_path / "hb.sqlite3")
    with sessionmaker(bind=fresh)() as s:
        assert s.execute(select(func.count()).select_from(PipelineRun)).scalar_one() == \
            len(pipelines.DAILY_SEQUENCE)
        assert s.execute(text("SELECT COUNT(*) FROM buyer_profile")).scalar_one() == 1  # seeded
    fresh.dispose()


def test_unknown_job_rejected():
    result = runner.invoke(app, ["pipeline", "no-such-job"])
    assert result.exit_code != 0


def test_alerts_send_exits_cleanly(engine, monkeypatch):
    """Against the test engine, never the developer's live DB — on a runner with
    no data/ the default engine is an empty file with no tables."""
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    result = runner.invoke(app, ["alerts", "send"])
    assert result.exit_code == 0
    assert "delivered: 0" in result.output


def test_backtest_reports_and_gates(engine, monkeypatch, tmp_path):
    import hb.db.engine as engine_module
    from hb import config

    monkeypatch.setattr(engine_module, "_engine", engine)
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    result = runner.invoke(app, ["backtest", "--n", "20"])
    # empty test DB -> insufficient prior data -> gate unmet -> exit 1
    assert result.exit_code == 1
    assert "backtest:" in result.output


def test_prune_raw_reports_what_it_removed(monkeypatch, tmp_path):
    from hb import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "raw_keep_days", 30)
    old = tmp_path / "raw" / "redfin" / (date.today() - timedelta(days=31)).isoformat()
    old.mkdir(parents=True)
    kept = tmp_path / "raw" / "redfin" / (date.today() - timedelta(days=29)).isoformat()
    kept.mkdir(parents=True)

    result = runner.invoke(app, ["prune-raw"])
    assert result.exit_code == 0
    assert "pruned 1 dated folder(s) older than 30 days" in result.output
    assert not old.exists() and kept.exists()
