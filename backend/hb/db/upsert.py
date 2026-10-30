"""The single write-path helper enforcing the platform idempotency invariant.

Every ingest write goes through upsert() keyed on the table's natural unique
key (docs/04-data-model.md). This is the only module allowed to use
SQLite-dialect SQL (docs/02-architecture.md §5.2) — swap the insert for the
postgresql dialect here if the DB ever moves.
"""

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from hb.db.models import Base, utcnow_iso


def upsert(
    session: Session,
    model: type[Base],
    values: dict,
    key_cols: list[str],
) -> tuple[Base, bool]:
    """Insert or update one row identified by its natural key.

    Returns (row, changed). changed is True on insert or when any non-key
    field actually differed — re-running identical input yields changed=False
    and touches nothing (not even updated_at).
    """
    key_filter = {k: values[k] for k in key_cols}
    row = session.execute(select(model).filter_by(**key_filter)).scalar_one_or_none()

    if row is None:
        stmt = sqlite_insert(model).values(**values).on_conflict_do_nothing(
            index_elements=key_cols
        )
        session.execute(stmt)
        row = session.execute(select(model).filter_by(**key_filter)).scalar_one()
        return row, True

    changed = False
    for field, incoming in values.items():
        if field in key_cols or field == "id":
            continue
        if getattr(row, field) != incoming:
            setattr(row, field, incoming)
            changed = True
    if changed and hasattr(row, "updated_at"):
        row.updated_at = utcnow_iso()
    return row, changed


def bulk_upsert(
    session: Session,
    model: type[Base],
    rows: list[dict],
    key_cols: list[str],
    chunk_size: int = 500,
) -> int:
    """High-volume upsert for pipeline loads (100k+ tidy rows). Conflict-target
    semantics keep it idempotent; per-row changed-detection is skipped — a
    re-run rewrites identical values, which is behaviorally a no-op.
    """
    if not rows:
        return 0
    update_cols = [c for c in rows[0] if c not in key_cols and c != "id"]
    total = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        stmt = sqlite_insert(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=key_cols,
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
        session.execute(stmt)
        total += len(chunk)
    return total
