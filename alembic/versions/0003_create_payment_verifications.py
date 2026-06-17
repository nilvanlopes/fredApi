"""create payment verifications table

Revision ID: 0003_payment_verifications
Revises: 0002_create_weekly_attendance_and_payments
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_payment_verifications"
down_revision: Union[str, None] = "0002_create_weekly_attendance_and_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscriber_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monthly_subscribers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("end_to_end_id", sa.Text(), nullable=True),
        sa.Column("payer_name", sa.Text(), nullable=True),
        sa.Column("normalized_payer_name", sa.Text(), nullable=True),
        sa.Column("receiver_name", sa.Text(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision_source", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("extraction", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_payment_verifications_month"),
        sa.CheckConstraint("year >= 2000", name="ck_payment_verifications_year"),
        sa.CheckConstraint(
            "status = ANY (ARRAY['eligible'::text, 'requires_review'::text, 'rejected'::text, 'confirmed'::text, 'duplicate'::text])",
            name="ck_payment_verifications_status",
        ),
        sa.UniqueConstraint("file_sha256", name="uq_payment_verifications_file_sha256"),
        sa.UniqueConstraint("end_to_end_id", name="uq_payment_verifications_end_to_end_id"),
    )


def downgrade() -> None:
    op.drop_table("payment_verifications")
