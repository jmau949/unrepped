"""Scheduled open houses remember whether the buyer went.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07

`visited_at` marks a scheduled slot the buyer actually attended. Scheduled
slots that have ended are the schedule's history; this column separates the
ones visited from the ones skipped. Nothing existing was marked, so every row
starts unvisited.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("open_houses", sa.Column("visited_at", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("open_houses", schema=None) as batch_op:
        batch_op.drop_column("visited_at")
