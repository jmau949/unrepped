"""The buyer's own visiting order for scheduled open houses.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24

`schedule_position` orders the schedule; the buyer rearranges it. Slots
already scheduled are numbered soonest first.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("open_houses", sa.Column("schedule_position", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE open_houses SET schedule_position = (
            SELECT COUNT(*) FROM open_houses AS o
            WHERE o.scheduled_at IS NOT NULL
              AND (o.start_at < open_houses.start_at
                   OR (o.start_at = open_houses.start_at AND o.id <= open_houses.id))
        ) WHERE scheduled_at IS NOT NULL
    """)


def downgrade() -> None:
    with op.batch_alter_table("open_houses", schema=None) as batch_op:
        batch_op.drop_column("schedule_position")
