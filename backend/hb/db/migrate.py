"""Programmatic alembic upgrade — used by `hb db upgrade`, `hb serve`, every
pipeline command (`cli._ready_db`) and tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _config(db_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if db_url:
        cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def upgrade_db(db_url: str | None = None) -> None:
    command.upgrade(_config(db_url), "head")


def current_heads(engine: Engine) -> set[str]:
    """The migration(s) the database is stamped at; empty for a fresh file. Read
    with plain SQL so the at-head check (every scheduled run) logs nothing."""
    if not inspect(engine).has_table("alembic_version"):
        return set()
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version"))}


def ensure_schema(engine: Engine) -> bool:
    """Bring the engine's database up to the newest migration; True when any
    ran. A fresh file gets the whole schema plus the seeds, so a pipeline can
    run before the app has ever served. At head this costs one query. A database
    that has tables but no alembic stamp was built another way (the tests'
    `Base.metadata.create_all`) and is left alone."""
    heads = current_heads(engine)
    if heads == set(ScriptDirectory.from_config(_config()).get_heads()):
        return False
    if not heads and inspect(engine).has_table("pipeline_runs"):
        return False
    upgrade_db(engine.url.render_as_string(hide_password=False))
    return True
