"""Remove the unused guest name column after weekly charge consolidation.

Revision ID: 0012_drop_guest_name
Revises: 0011_unify_weekly_charges
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_drop_guest_name"
down_revision = "0011_unify_weekly_charges"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("charges", "guest_name")


def downgrade():
    op.add_column("charges", sa.Column("guest_name", sa.Text(), nullable=True))
