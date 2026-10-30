"""Open-house slots are unique per (listing_id, start_at) across sources.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24

Several sources (Realtor, Redfin) report the same slot; the row is the slot,
`source` is provenance. Duplicate rows already stored for one slot are
collapsed first, keeping the one on the buyer's schedule, else the oldest.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM open_houses WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY listing_id, start_at
                    ORDER BY scheduled_at IS NULL, first_seen, id
                ) AS rn FROM open_houses
            ) WHERE rn = 1
        )
    """)
    with op.batch_alter_table("open_houses", schema=None) as batch_op:
        batch_op.drop_constraint("uq_open_houses_slot", type_="unique")
        batch_op.create_unique_constraint("uq_open_houses_slot", ["listing_id", "start_at"])


def downgrade() -> None:
    with op.batch_alter_table("open_houses", schema=None) as batch_op:
        batch_op.drop_constraint("uq_open_houses_slot", type_="unique")
        batch_op.create_unique_constraint("uq_open_houses_slot",
                                          ["listing_id", "source", "start_at"])
