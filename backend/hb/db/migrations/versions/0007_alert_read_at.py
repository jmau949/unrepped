"""Alerts remember when the buyer opened them.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01

`read_at` is the inbox's unread state (docs/08 §8). `delivered_at` only says a
channel reached the buyer, and with `log` enabled that is every alert within
the hour, so it never said whether anyone looked. Alerts delivered before this
column existed cannot say either, so they start read: the inbox opens with
nothing bold that is not new.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("read_at", sa.Text(), nullable=True))
    op.execute("UPDATE alerts SET read_at = delivered_at WHERE delivered_at IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_column("read_at")
