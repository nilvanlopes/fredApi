"""move prebuilt team to weekly attendance entries

Revision ID: 0006_prebuilt_team_column
Revises: 0005_prebuilt_team_members
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_prebuilt_team_column"
down_revision: Union[str, None] = "0005_prebuilt_team_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "weekly_attendance_entries",
        sa.Column("prebuilt_team_number", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_weekly_attendance_entries_prebuilt_team_positive",
        "weekly_attendance_entries",
        "prebuilt_team_number IS NULL OR prebuilt_team_number > 0",
    )
    op.execute(
        """
        UPDATE weekly_attendance_entries AS entry
        SET prebuilt_team_number = team.team_number
        FROM weekly_attendance_prebuilt_team_members AS team
        WHERE team.entry_id = entry.id
        """
    )
    op.drop_index(
        "ix_weekly_attendance_prebuilt_team_members_attendance_team",
        table_name="weekly_attendance_prebuilt_team_members",
    )
    op.drop_table("weekly_attendance_prebuilt_team_members")


def downgrade() -> None:
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
    op.execute(
        """
        INSERT INTO weekly_attendance_prebuilt_team_members (
            id,
            attendance_id,
            entry_id,
            team_number
        )
        SELECT gen_random_uuid(), attendance_id, id, prebuilt_team_number
        FROM weekly_attendance_entries
        WHERE prebuilt_team_number IS NOT NULL
        """
    )
    op.drop_constraint(
        "ck_weekly_attendance_entries_prebuilt_team_positive",
        "weekly_attendance_entries",
        type_="check",
    )
    op.drop_column("weekly_attendance_entries", "prebuilt_team_number")
