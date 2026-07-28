"""create weekly prebuilt team members

Revision ID: 0005_prebuilt_team_members
Revises: 0004_conversation_messages
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_prebuilt_team_members"
down_revision: Union[str, None] = "0004_conversation_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_attendance_prebuilt_team_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attendance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "team_number > 0",
            name="ck_weekly_attendance_prebuilt_team_members_team_positive",
        ),
        sa.ForeignKeyConstraint(
            ["attendance_id"],
            ["weekly_attendances.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["weekly_attendance_entries.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entry_id",
            name="uq_weekly_attendance_prebuilt_team_members_entry",
        ),
    )
    op.create_index(
        "ix_weekly_attendance_prebuilt_team_members_attendance_team",
        "weekly_attendance_prebuilt_team_members",
        ["attendance_id", "team_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weekly_attendance_prebuilt_team_members_attendance_team",
        table_name="weekly_attendance_prebuilt_team_members",
    )
    op.drop_table("weekly_attendance_prebuilt_team_members")
