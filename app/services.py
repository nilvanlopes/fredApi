from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MonthlySubscriber
from app.parser import ParsedSubscriberLine, parse_monthly_subscribers_message
from app.schemas import ProcessMessageResponse, SubscriberChange


async def process_monthly_subscribers_message(
    session: AsyncSession,
    *,
    text: str,
    received_at=None,
) -> ProcessMessageResponse:
    parsed = parse_monthly_subscribers_message(text, received_at=received_at)

    created: list[SubscriberChange] = []
    updated: list[SubscriberChange] = []
    deleted: list[SubscriberChange] = []
    unchanged: list[SubscriberChange] = []

    for line in parsed.subscribers:
        existing = await _get_by_position(
            session,
            month=parsed.month,
            year=parsed.year,
            position=line.position,
        )

        if line.name is None:
            if existing is not None:
                await session.delete(existing)
                deleted.append(
                    SubscriberChange(position=line.position, name=existing.name)
                )
            continue

        if existing is None:
            session.add(
                MonthlySubscriber(
                    position=line.position,
                    name=line.name,
                    normalized_name=line.normalized_name,
                    month=parsed.month,
                    year=parsed.year,
                    has_paid=line.has_paid,
                )
            )
            created.append(_change_from_line(line))
            continue

        if _has_changes(existing, line):
            existing.name = line.name
            existing.normalized_name = line.normalized_name
            existing.has_paid = line.has_paid
            updated.append(_change_from_line(line))
        else:
            unchanged.append(_change_from_line(line))

    await session.commit()

    return ProcessMessageResponse(
        type="monthly_subscribers",
        month=parsed.month,
        year=parsed.year,
        created=created,
        updated=updated,
        deleted=deleted,
        unchanged=unchanged,
    )


async def _get_by_position(
    session: AsyncSession,
    *,
    month: int,
    year: int,
    position: int,
) -> MonthlySubscriber | None:
    result = await session.execute(
        select(MonthlySubscriber).where(
            MonthlySubscriber.month == month,
            MonthlySubscriber.year == year,
            MonthlySubscriber.position == position,
        )
    )
    return result.scalar_one_or_none()


def _has_changes(existing: MonthlySubscriber, line: ParsedSubscriberLine) -> bool:
    return (
        existing.name != line.name
        or existing.normalized_name != line.normalized_name
        or existing.has_paid != line.has_paid
    )


def _change_from_line(line: ParsedSubscriberLine) -> SubscriberChange:
    return SubscriberChange(
        position=line.position,
        name=line.name,
        has_paid=line.has_paid,
    )

