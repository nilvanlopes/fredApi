"""create weekly attendance tables

Revision ID: 0002_create_weekly_attendance_and_payments
Revises: 0001_create_monthly_subscribers
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_create_weekly_attendance_and_payments"
down_revision: Union[str, None] = "0001_create_monthly_subscribers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_attendances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("capacity > 0", name="ck_weekly_attendances_capacity_positive"),
        sa.UniqueConstraint("game_date", name="uq_weekly_attendances_game_date"),
    )

    op.create_table(
        "weekly_attendance_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attendance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("weekly_attendances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_section", sa.Text(), nullable=False),
        sa.Column("source_position", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.Text(), nullable=True),
        sa.Column("normalized_invited_by", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "is_monthly_subscriber",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "owes_single_payment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("single_payment_amount_cents", sa.Integer(), nullable=True),
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
        sa.CheckConstraint("source_position > 0", name="ck_weekly_attendance_entries_position"),
        sa.CheckConstraint(
            "source_section = ANY (ARRAY['main'::text, 'guests'::text])",
            name="ck_weekly_attendance_entries_source_section",
        ),
        sa.CheckConstraint(
            "status = ANY (ARRAY['main'::text, 'waiting'::text])",
            name="ck_weekly_attendance_entries_status",
        ),
        sa.UniqueConstraint(
            "attendance_id",
            "source_section",
            "source_position",
            name="uq_weekly_attendance_entries_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("weekly_attendance_entries")
    op.drop_table("weekly_attendances")
