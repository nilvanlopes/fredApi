from datetime import date, datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MonthlySubscriber(Base):
    __tablename__ = "monthly_subscribers"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_monthly_subscribers_position_positive"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_subscribers_month"),
        CheckConstraint("year >= 2000", name="ck_monthly_subscribers_year"),
        UniqueConstraint(
            "month",
            "year",
            "position",
            name="uq_monthly_subscribers_month_year_position",
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    has_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
        UniqueConstraint(
            "attendance_id",
            "source_section",
            "source_position",
            name="uq_weekly_attendance_entries_source",
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    attendance_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_attendances.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    chat_id: Mapped[str] = mapped_column(Text, nullable=False)
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
