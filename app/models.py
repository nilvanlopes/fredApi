from datetime import datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
