"""Income on the buyer profile, for the lender's payment limit.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27

`annual_income` (gross, dollars per year) and `monthly_debts` (other monthly
debt payments) let the Affordability page and the offer solver apply the
debt-to-income ceiling (docs/06 §8). Both default to 0, which means "not
entered" and leaves the payment limit off.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("buyer_profile", sa.Column("annual_income", sa.Integer(), nullable=False,
                                             server_default="0"))
    op.add_column("buyer_profile", sa.Column("monthly_debts", sa.Integer(), nullable=False,
                                             server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("buyer_profile", schema=None) as batch_op:
        batch_op.drop_column("monthly_debts")
        batch_op.drop_column("annual_income")
