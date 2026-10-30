"""Watchlist membership is `watched_at` alone.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28

Logging a tour now stamps `watched_at` and Remove clears it (docs/08 §5b), so
a tour no longer implies membership and `watch_hidden_at` goes. Toured homes
still on the list get their stamp; hidden homes come off.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE properties SET watched_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') "
        "WHERE watched_at IS NULL AND watch_hidden_at IS NULL "
        "AND id IN (SELECT property_id FROM property_tours)"
    )
    op.execute("UPDATE properties SET watched_at = NULL WHERE watch_hidden_at IS NOT NULL")
    with op.batch_alter_table("properties", schema=None) as batch_op:
        batch_op.drop_column("watch_hidden_at")


def downgrade() -> None:
    op.add_column("properties", sa.Column("watch_hidden_at", sa.Text(), nullable=True))
