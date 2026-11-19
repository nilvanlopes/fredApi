from datetime import date, datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    Index,
    text,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PersonAlias(Base):
    __tablename__ = "person_aliases"
    __table_args__ = (
        UniqueConstraint("alias_normalized", name="uq_person_aliases_alias_normalized"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MonthlySubscriber(Base):
    __tablename__ = "monthly_subscribers"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_monthly_subscribers_position_positive"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_subscribers_month"),
        CheckConstraint("year >= 2000", name="ck_monthly_subscribers_year"),
        Index("uq_monthly_active_position", "month", "year", "position", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    has_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    person_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("people.id"), nullable=True)
    source_message_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processed_conversation_messages.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WeeklyAttendance(Base):
    __tablename__ = "weekly_attendances"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_weekly_attendances_capacity_positive"),
        UniqueConstraint("game_date", name="uq_weekly_attendances_game_date"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    game_date: Mapped[date] = mapped_column(Date(), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    entries: Mapped[list["WeeklyAttendanceEntry"]] = relationship(
        back_populates="attendance",
        cascade="all, delete-orphan",
    )


class WeeklyAttendanceEntry(Base):
    __tablename__ = "weekly_attendance_entries"
    __table_args__ = (
        CheckConstraint("source_position > 0", name="ck_weekly_attendance_entries_position"),
        CheckConstraint(
            "source_section IN ('main', 'guests')",
            name="ck_weekly_attendance_entries_source_section",
        ),
        CheckConstraint(
            "status IN ('main', 'waiting')",
            name="ck_weekly_attendance_entries_status",
        ),
        CheckConstraint(
            "prebuilt_team_number IS NULL OR prebuilt_team_number > 0",
            name="ck_weekly_attendance_entries_prebuilt_team_positive",
        ),
        Index("uq_weekly_active_source", "attendance_id", "source_section", "source_position", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    attendance_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_attendances.id", ondelete="CASCADE"),
        nullable=False,
    )
    person_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("people.id"), nullable=True)
    source_message_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processed_conversation_messages.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_section: Mapped[str] = mapped_column(Text, nullable=False)
    source_position: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_invited_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_monthly_subscriber: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    owes_single_payment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    single_payment_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prebuilt_team_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    attendance: Mapped[WeeklyAttendance] = relationship(back_populates="entries")


class ProcessedConversationMessage(Base):
    __tablename__ = "processed_conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "message_type IN "
            "('monthly_subscribers', 'weekly_attendance', 'ignored', 'review_required')",
            name="ck_processed_conversation_messages_type",
        ),
        CheckConstraint(
            "status IN ('applied', 'unchanged', 'ignored', 'review_required', 'stale')",
            name="ck_processed_conversation_messages_status",
        ),
        UniqueConstraint(
            "fingerprint",
            name="uq_processed_conversation_messages_fingerprint",
        ),
        UniqueConstraint(
            "chat_id",
            "provider_message_id",
            name="uq_processed_conversation_messages_provider_id",
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    chat_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    analyzer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Person(Base):
    __tablename__ = "people"
    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PersonProfile(Base):
    __tablename__ = "person_profiles"

    person_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    nicknames: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    positions: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    primary_position: Mapped[str | None] = mapped_column(Text, nullable=True)
    sex: Mapped[str | None] = mapped_column(Text, nullable=True)
    handedness: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    photo_source_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_avatar_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_crop: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    photo_version: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlayerRating(Base):
    __tablename__ = "player_ratings"
    __table_args__ = (
        Index("ix_player_ratings_target", "target_person_id"),
        UniqueConstraint("evaluator_person_id", "target_person_id", name="uq_player_ratings_evaluator_target"),
        CheckConstraint("evaluator_person_id <> target_person_id", name="ck_player_ratings_not_self"),
        CheckConstraint("stars >= 1 AND stars <= 5", name="ck_player_ratings_stars_range"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    evaluator_person_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    target_person_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    publish_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class FredAccount(Base):
    __tablename__ = "fred_accounts"
    uid: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    person_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("people.id"), nullable=True, unique=True)


class Charge(Base):
    __tablename__ = "charges"
    __table_args__ = (
        UniqueConstraint("person_id", "type", "reference_date", name="uq_charge_person_period"),
        CheckConstraint("amount_cents >= 0", name="ck_charge_amount"),
    )
    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("people.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentListNotification(Base):
    __tablename__ = "payment_list_notifications"
    __table_args__ = (
        Index("ix_payment_list_notifications_pending", "aggregate_key", "id",
              postgresql_where=text("delivered_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid4)
    aggregate_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_uid: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    person_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("people.id"), nullable=True)
    before: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    after: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="applied")


class EntityRevision(Base):
    __tablename__ = "entity_revisions"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
