"""create processed conversation messages

Revision ID: 0004_conversation_messages
Revises: 0003_payment_verifications
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_conversation_messages"
down_revision: Union[str, None] = "0003_payment_verifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("source_ordinal", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_name", sa.Text(), nullable=True),
        sa.Column("message_type", sa.Text(), nullable=False),
        sa.Column("aggregate_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("analyzer", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "message_type = ANY (ARRAY["
            "'monthly_subscribers'::text, 'weekly_attendance'::text, "
            "'ignored'::text, 'review_required'::text])",
            name="ck_processed_conversation_messages_type",
        ),
        sa.CheckConstraint(
            "status = ANY (ARRAY["
            "'applied'::text, 'unchanged'::text, 'ignored'::text, "
            "'review_required'::text, 'stale'::text])",
            name="ck_processed_conversation_messages_status",
        ),
        sa.UniqueConstraint(
            "fingerprint",
            name="uq_processed_conversation_messages_fingerprint",
        ),
    )
    op.create_index(
        "ix_processed_conversation_messages_aggregate_time",
        "processed_conversation_messages",
        ["chat_id", "aggregate_key", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_conversation_messages_aggregate_time",
        table_name="processed_conversation_messages",
    )
    op.drop_table("processed_conversation_messages")
