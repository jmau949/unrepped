"""Watchlist membership on the property.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

A home is on the Watchlist (docs/08 §5b) when `watched_at` is set or it has a
tour, and `watch_hidden_at` is NULL.
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("watched_at", sa.Text(), nullable=True))
    op.add_column("properties", sa.Column("watch_hidden_at", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("properties", schema=None) as batch_op:
        batch_op.drop_column("watch_hidden_at")
        batch_op.drop_column("watched_at")
