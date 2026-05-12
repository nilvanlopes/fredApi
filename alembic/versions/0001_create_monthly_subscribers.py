"""create monthly subscribers

Revision ID: 0001_create_monthly_subscribers
Revises:
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_create_monthly_subscribers"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_subscribers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("has_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("position > 0", name="ck_monthly_subscribers_position_positive"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_subscribers_month"),
        sa.CheckConstraint("year >= 2000", name="ck_monthly_subscribers_year"),
        sa.UniqueConstraint(
            "month",
            "year",
            "position",
            name="uq_monthly_subscribers_month_year_position",
        ),
    )


def downgrade() -> None:
    op.drop_table("monthly_subscribers")

