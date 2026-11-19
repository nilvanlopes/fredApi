"""Persist WhatsApp source messages and list entry provenance.

Revision ID: 0009_whatsapp_list_history
Revises: 0008_management
"""
from alembic import op

revision = "0009_whatsapp_list_history"
down_revision = "0008_management"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE processed_conversation_messages ADD COLUMN provider_message_id text")
    op.execute("ALTER TABLE processed_conversation_messages ADD COLUMN sender_id text")
    op.execute("ALTER TABLE processed_conversation_messages ADD COLUMN source text")
    op.execute("ALTER TABLE processed_conversation_messages ADD COLUMN raw_text text")
    op.execute(
        "ALTER TABLE processed_conversation_messages ADD CONSTRAINT "
        "uq_processed_conversation_messages_provider_id UNIQUE(chat_id, provider_message_id)"
    )
    op.execute(
        "ALTER TABLE monthly_subscribers ADD COLUMN source_message_id uuid "
        "REFERENCES processed_conversation_messages(id)"
    )
    op.execute(
        "ALTER TABLE weekly_attendance_entries ADD COLUMN source_message_id uuid "
        "REFERENCES processed_conversation_messages(id)"
    )
    op.execute(
        "CREATE INDEX ix_processed_messages_aggregate_time "
        "ON processed_conversation_messages(aggregate_key, occurred_at, created_at)"
    )


def downgrade():
    op.execute("DROP INDEX ix_processed_messages_aggregate_time")
    op.execute("ALTER TABLE weekly_attendance_entries DROP COLUMN source_message_id")
    op.execute("ALTER TABLE monthly_subscribers DROP COLUMN source_message_id")
    op.execute(
        "ALTER TABLE processed_conversation_messages DROP CONSTRAINT "
        "uq_processed_conversation_messages_provider_id"
    )
    op.execute(
        "ALTER TABLE processed_conversation_messages DROP COLUMN raw_text, "
        "DROP COLUMN source, DROP COLUMN sender_id, DROP COLUMN provider_message_id"
    )
