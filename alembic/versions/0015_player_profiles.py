"""Add player profiles and private player ratings.

Revision ID: 0015_player_profiles
Revises: 0014_payment_list_outbox
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_player_profiles"
down_revision = "0014_payment_list_outbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "person_profiles",
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("nicknames", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("bio", sa.Text()),
        sa.Column("positions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("primary_position", sa.Text()),
        sa.Column("sex", sa.Text()),
        sa.Column("handedness", sa.Text()),
        sa.Column("skills", sa.JSON()),
        sa.Column("photo_source_key", sa.Text()),
        sa.Column("photo_avatar_key", sa.Text()),
        sa.Column("photo_content_type", sa.Text()),
        sa.Column("photo_crop", sa.JSON()),
        sa.Column("photo_version", sa.Text()),
    )
    op.create_table(
        "player_ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evaluator_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("publish_identity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("evaluator_person_id <> target_person_id", name="ck_player_ratings_not_self"),
        sa.CheckConstraint("stars >= 1 AND stars <= 5", name="ck_player_ratings_stars_range"),
        sa.UniqueConstraint("evaluator_person_id", "target_person_id", name="uq_player_ratings_evaluator_target"),
    )
    op.create_index("ix_player_ratings_target", "player_ratings", ["target_person_id"])


def downgrade():
    op.drop_index("ix_player_ratings_target", table_name="player_ratings")
    op.drop_table("player_ratings")
    op.drop_table("person_profiles")
