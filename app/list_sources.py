"""Source-message linking for the active entries in WhatsApp-managed lists."""
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aliases import resolve_normalized_name
from app.models import (
    EntityRevision,
    MonthlySubscriber,
    ProcessedConversationMessage,
    WeeklyAttendance,
    WeeklyAttendanceEntry,
)
from app.parser import (
    ParseError,
    ParsedMonthlySubscribers,
    parse_monthly_subscribers_message,
    parse_weekly_attendance_message,
)

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=LOCAL_TZ)


async def link_message_to_entries(
    session: AsyncSession,
    *,
    message_id: UUID,
    message_type: str,
    text: str,
    occurred_at: datetime,
    parsed_monthly: ParsedMonthlySubscribers | None = None,
) -> None:
    """Set the latest accepted WhatsApp source on active rows represented in text.

    An older/replayed snapshot cannot take provenance away from a newer manual
    or WhatsApp event because the same per-entry revision cursor gates writes.
    """
    timestamp = _aware(occurred_at)
    message = await session.get(ProcessedConversationMessage, message_id)
    if message is None:
        return

    if message_type == "monthly_subscribers":
        try:
            parsed = parsed_monthly or parse_monthly_subscribers_message(text, received_at=timestamp)
        except ParseError:
            return
        for line in parsed.subscribers:
            if not line.name:
                continue
            canonical = await resolve_normalized_name(session, line.normalized_name)
            row = await session.scalar(
                select(MonthlySubscriber).where(
                    MonthlySubscriber.month == parsed.month,
                    MonthlySubscriber.year == parsed.year,
                    MonthlySubscriber.position == line.position,
                    MonthlySubscriber.deleted_at.is_(None),
                )
            )
            if row is None or row.normalized_name != canonical:
                continue
            key = f"monthly:{row.person_id}:{date(parsed.year, parsed.month, 1)}"
            revision = await session.get(EntityRevision, key)
            if revision is not None and revision.occurred_at > timestamp:
                continue
            row.source_message_id = message_id
        return

    if message_type != "weekly_attendance":
        return
    try:
        parsed = parse_weekly_attendance_message(text, received_at=timestamp)
    except ParseError:
        return
    attendance = await session.scalar(
        select(WeeklyAttendance).where(WeeklyAttendance.game_date == parsed.game_date)
    )
    if attendance is None:
        return
    for line in parsed.entries:
        canonical = await resolve_normalized_name(session, line.normalized_name)
        row = await session.scalar(
            select(WeeklyAttendanceEntry).where(
                WeeklyAttendanceEntry.attendance_id == attendance.id,
                WeeklyAttendanceEntry.source_section == line.section,
                WeeklyAttendanceEntry.source_position == line.position,
                WeeklyAttendanceEntry.deleted_at.is_(None),
            )
        )
        if row is None or row.normalized_name != canonical:
            continue
        key = f"weekly:{row.person_id}:{parsed.game_date}"
        revision = await session.get(EntityRevision, key)
        if revision is not None and revision.occurred_at > timestamp:
            continue
        row.source_message_id = message_id
