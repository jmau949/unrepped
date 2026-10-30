import pytest
from fastapi.testclient import TestClient

from hb.pipelines.base import JobRunner


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.ops as ops_module
    import hb.db.engine as engine_module

    # Route the app's sessions at the test DB
    monkeypatch.setattr(engine_module, "_engine", engine)
    monkeypatch.setattr(ops_module, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


def test_health_shape(client):
    resp = client.get("/api/ops/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert body["last_scan"] is None  # no scans yet — must be null-safe
    assert body["rentcast_quota_remaining"] is None  # no RENTCAST_API_KEY: not shown


def test_health_reports_rentcast_quota_once_configured(client, monkeypatch):
    from hb.config import settings
    monkeypatch.setattr(settings, "rentcast_api_key", "test-key")
    body = client.get("/api/ops/health").json()
    assert body["rentcast_quota_remaining"] == settings.rentcast_monthly_limit


def test_health_reports_an_unmigrated_database(tmp_path, monkeypatch):
    """A fresh clone before `hb serve` / `hb db upgrade`: the gate says so rather
    than erroring on the first missing table (docs/07 §Ops)."""
    import hb.api.ops as ops_module
    import hb.db.engine as engine_module
    from hb.db.engine import make_engine

    empty = make_engine(tmp_path / "empty.sqlite3")  # no create_all, no migration
    monkeypatch.setattr(engine_module, "_engine", empty)
    monkeypatch.setattr(ops_module, "make_session", lambda: engine_module.make_session(empty))
    from hb.main import app

    body = TestClient(app).get("/api/ops/health").json()
    assert body == {"db": "unmigrated", "last_scan": None, "scan_overdue_since": None,
                    "rentcast_quota_remaining": None}
    empty.dispose()


def test_pipeline_runs_list_and_filter(client, engine):
    with JobRunner("fred", engine):
        pass
    with JobRunner("redfin-market", engine):
        pass

    all_runs = client.get("/api/ops/pipeline-runs").json()
    assert len(all_runs) == 2
    assert {"job", "status", "started_at", "items_seen"} <= set(all_runs[0])

    only_fred = client.get("/api/ops/pipeline-runs", params={"job": "fred"}).json()
    assert len(only_fred) == 1
    assert only_fred[0]["job"] == "fred"
    assert only_fred[0]["status"] == "ok"
