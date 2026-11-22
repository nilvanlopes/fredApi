"""Add a transactional outbox for payment list notifications.

Revision ID: 0014_payment_list_outbox
Revises: 0013_drop_charge_type_check
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_payment_list_outbox"
down_revision = "0013_drop_charge_type_check"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_list_notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_key", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_payment_list_notifications_pending", "payment_list_notifications", ["aggregate_key", "id"],
        postgresql_where=sa.text("delivered_at IS NULL"),
    )


def downgrade():
    op.drop_table("payment_list_notifications")
