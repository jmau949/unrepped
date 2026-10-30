import json

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from hb.db.migrate import upgrade_db
from hb.db.models import Base


def test_ensure_schema_builds_a_fresh_db_once_and_leaves_other_dbs_alone(tmp_path):
    from hb.db.engine import make_engine
    from hb.db.migrate import ensure_schema

    fresh = make_engine(tmp_path / "fresh.sqlite3")
    assert ensure_schema(fresh) is True  # built the schema + seeds
    assert ensure_schema(fresh) is False  # already at head: nothing to do
    with fresh.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM buyer_profile")).scalar_one() == 1

    # the tests' create_all databases carry no alembic stamp: not ours to migrate
    plain = make_engine(tmp_path / "plain.sqlite3")
    Base.metadata.create_all(plain)
    assert ensure_schema(plain) is False
    fresh.dispose()
    plain.dispose()


def test_upgrade_head_twice_and_seeds(tmp_path):
    db = tmp_path / "mig.sqlite3"
    url = f"sqlite:///{db}"

    upgrade_db(url)
    upgrade_db(url)  # must be a no-op

    eng = create_engine(url)
    with eng.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        expected = {
            "properties", "listings", "listing_events", "listing_groups", "sales",
            "market_metrics", "price_index", "avm_snapshots", "cma_runs", "cma_comps",
            "tracked_listings", "alerts", "rate_snapshots", "buyer_profile",
            "settings", "pipeline_runs", "contacts", "preapprovals", "hazard_flags",
            "schools", "school_districts", "school_rating_snapshots", "property_tours",
            "deals", "open_houses",
        }
        assert expected <= tables
        assert "county_tax_rates" not in tables  # rates live in the geography file

        # seeds: exactly one default profile and the alert rules; nothing geographic
        assert conn.execute(
            text("SELECT COUNT(*) FROM buyer_profile WHERE id='default'")
        ).scalar_one() == 1
        rules = conn.execute(
            text("SELECT value FROM settings WHERE key='alert_rules'")
        ).scalar_one()
        assert json.loads(rules)["rate_move"]["bps_threshold"] == 25
        assert json.loads(rules)["watched_status"] == {"enabled": True}
        # schools is populated by the schools pipeline, not seeded
        assert conn.execute(text("SELECT COUNT(*) FROM schools")).scalar_one() == 0
        contact_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(contacts)"))}
        assert {"deal_id", "listing_id"} <= contact_cols
    eng.dispose()


def test_migration_matches_models(tmp_path):
    """The migrations ARE the schema: a DB they build must show no diff against
    `models.py`, so a model change without a new migration fails here."""
    url = f"sqlite:///{tmp_path / 'parity.sqlite3'}"
    upgrade_db(url)
    eng = create_engine(url)
    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    eng.dispose()
    assert diffs == [], diffs


def test_wal_mode_active(tmp_path):
    from hb.db.engine import make_engine

    eng = make_engine(tmp_path / "wal.sqlite3")
    with eng.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
    eng.dispose()
