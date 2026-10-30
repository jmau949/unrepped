from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from hb.config import settings
from hb.db import models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{settings.db_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url())
    # WAL is a persistent database-file setting; set it at creation time so the
    # DB is in WAL mode from birth. Must run on its own AUTOCOMMIT connection —
    # touching the migration connection first opens an implicit transaction that
    # would swallow alembic's version stamp and any data-migration DML.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as pragma_conn:
        pragma_conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER support for future migrations
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
