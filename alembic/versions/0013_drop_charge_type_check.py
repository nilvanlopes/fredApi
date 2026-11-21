"""Remove the charge type check added during the weekly charge consolidation.

Revision ID: 0013_drop_charge_type_check
Revises: 0012_drop_guest_name
"""
from alembic import op


revision = "0013_drop_charge_type_check"
down_revision = "0012_drop_guest_name"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_charge_type", "charges", type_="check")


def downgrade():
    op.create_check_constraint("ck_charge_type", "charges", "type IN ('monthly', 'single')")
