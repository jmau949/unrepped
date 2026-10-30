import pytest
from fastapi.testclient import TestClient

from hb import packs, prep_spec


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.prep as prep_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    monkeypatch.setattr(prep_module, "make_session",
                        lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


def test_spec_is_complete_and_self_explaining():
    rows = [t for p in prep_spec.spec_for()["phases"] for t in p["tasks"]]
    assert len(rows) == len(prep_spec.tasks_for())
    # Same contract as the closing spec: a bare label is useless to a first-timer.
    assert all(t["why"] and t["how"] for t in rows)
    assert all(t["needed_by"] in packs.current().prep.needed_by for t in rows)
    assert all(t["owner"] in packs.current().prep.owners for t in rows)
    # Keys are the storage contract — they must be unique.
    keys = [t["key"] for t in rows]
    assert len(keys) == len(set(keys))


def test_long_lead_items_are_flagged():
    """The whole ordering value of this page: what cannot be hurried later."""
    roll = prep_spec.evaluate({})
    flagged = {t["key"] for t in roll["long_lead_open"]}
    assert {"pull_credit_reports", "dispute_credit_errors", "gift_funds_sorted"} <= flagged
    assert roll["done"] == 0
    assert roll["total"] == len(prep_spec.tasks_for())


def test_get_returns_empty_checklist_before_anything_is_saved(client):
    body = client.get("/api/prep").json()
    assert body["rollup"]["done"] == 0
    assert body["phases"]
    assert all(not t["done"] for p in body["phases"] for t in p["tasks"])


def test_patch_persists_and_rollup_recomputes(client):
    body = client.patch("/api/prep", json={
        "checklist": {"pull_credit_reports": {"done_on": "2026-08-14"}},
    }).json()
    assert body["rollup"]["done"] == 1

    rows = {t["key"]: t for p in body["phases"] for t in p["tasks"]}
    assert rows["pull_credit_reports"]["done"] is True
    # and it is no longer nagging you about the lead time
    assert "pull_credit_reports" not in {t["key"] for t in body["rollup"]["long_lead_open"]}

    # survives a re-read — this is the settings row, not request state
    again = client.get("/api/prep").json()
    assert again["rollup"]["done"] == 1


def test_patch_merges_rather_than_replaces(client):
    client.patch("/api/prep", json={"checklist": {"find_inspector": {"note": "called 2"}}})
    body = client.patch("/api/prep", json={
        "checklist": {"find_inspector": {"done_on": "2026-08-14"}},
    }).json()
    rows = {t["key"]: t for p in body["phases"] for t in p["tasks"]}
    assert rows["find_inspector"]["note"] == "called 2"
    assert rows["find_inspector"]["done"] is True

    # a second task does not disturb the first
    body = client.patch("/api/prep", json={
        "checklist": {"find_specialists": {"done_on": "2026-08-15"}},
    }).json()
    assert body["rollup"]["done"] == 2


def test_unticking_clears_it(client):
    client.patch("/api/prep", json={"checklist": {"count_your_cash": {"done_on": "2026-08-14"}}})
    body = client.patch("/api/prep",
                        json={"checklist": {"count_your_cash": {"done_on": None}}}).json()
    assert body["rollup"]["done"] == 0


def test_unknown_task_key_is_rejected(client):
    resp = client.patch("/api/prep", json={"checklist": {"buy_a_boat": {"done_on": "x"}}})
    assert resp.status_code == 422
