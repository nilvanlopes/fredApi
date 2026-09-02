from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_single_game_price_cents, get_weekly_attendance_capacity
from app.aliases import resolve_normalized_name
from app.message_templates import render_weekly_attendance_message
from app.models import (
    MonthlySubscriber,
    WeeklyAttendance,
    WeeklyAttendanceEntry,
)
from app.parser import (
    ParsedMonthlySubscribers,
    ParsedSubscriberLine,
    ParsedWeeklyAttendance,
    ParsedWeeklyAttendanceLine,
    parse_monthly_subscribers_message,
    parse_weekly_attendance_message,
)
from app.schemas import (
    ProcessMessageResponse,
    PromoteDueResponse,
    PromotionResult,
    SubscriberChange,
    WeeklyAttendanceEntryResponse,
    WeeklyAttendanceMessageResponse,
    WeeklyAttendanceResponse,
)

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class _AttendanceEntryState:
    section: str
    position: int
    display_order: int
    name: str
    normalized_name: str
    invited_by: str | None
    normalized_invited_by: str | None
    status: str
    is_monthly_subscriber: bool
    owes_single_payment: bool
    single_payment_amount_cents: int | None
    prebuilt_team_number: int | None


async def process_monthly_subscribers_message(
    session: AsyncSession,
    *,
    text: str,
    received_at=None,
    commit: bool = True,
) -> ProcessMessageResponse:
    parsed = parse_monthly_subscribers_message(text, received_at=received_at)
    return await apply_monthly_subscribers(
        session,
        parsed=parsed,
        commit=commit,
    )


async def apply_monthly_subscribers(
    session: AsyncSession,
    *,
    parsed: ParsedMonthlySubscribers,
    commit: bool = True,
) -> ProcessMessageResponse:

    parsed = await _resolve_monthly_aliases(session, parsed)
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

    if commit:
        await session.commit()
    else:
        await session.flush()

    return ProcessMessageResponse(
        type="monthly_subscribers",
        month=parsed.month,
        year=parsed.year,
        created=created,
        updated=updated,
        deleted=deleted,
        unchanged=unchanged,
    )


async def process_weekly_attendance_message(
    session: AsyncSession,
    *,
    text: str,
    received_at: datetime | None = None,
    commit: bool = True,
) -> WeeklyAttendanceResponse:
    parsed = parse_weekly_attendance_message(text, received_at=received_at)
    return await apply_weekly_attendance(
        session,
        parsed=parsed,
        received_at=received_at,
        commit=commit,
    )


async def apply_weekly_attendance(
    session: AsyncSession,
    *,
    parsed: ParsedWeeklyAttendance,
    received_at: datetime | None = None,
    commit: bool = True,
) -> WeeklyAttendanceResponse:
    parsed = await _resolve_weekly_aliases(session, parsed)
    attendance = await _get_weekly_attendance(session, game_date=parsed.game_date)
    capacity = attendance.capacity if attendance is not None else get_weekly_attendance_capacity()
    cutoff_at = _build_cutoff_at(parsed.game_date)
    reference_time = _normalize_reference_time(received_at)
    monthly_names = await _get_monthly_subscriber_names(
        session,
        month=parsed.game_date.month,
        year=parsed.game_date.year,
    )
    states = _build_entry_states(
        parsed.entries,
        monthly_names=monthly_names,
        capacity=capacity,
        after_cutoff=reference_time >= cutoff_at,
    )

    if attendance is None:
        attendance = WeeklyAttendance(
            game_date=parsed.game_date,
            capacity=capacity,
            cutoff_at=cutoff_at,
        )
        session.add(attendance)
        await session.flush()
    else:
        attendance.capacity = capacity
        attendance.cutoff_at = cutoff_at
        await session.execute(
            delete(WeeklyAttendanceEntry).where(
                WeeklyAttendanceEntry.attendance_id == attendance.id
            )
        )

    for state in states:
        session.add(
            WeeklyAttendanceEntry(
                attendance_id=attendance.id,
                source_section=state.section,
                source_position=state.position,
                display_order=state.display_order,
                name=state.name,
                normalized_name=state.normalized_name,
                invited_by=state.invited_by,
                normalized_invited_by=state.normalized_invited_by,
                status=state.status,
                is_monthly_subscriber=state.is_monthly_subscriber,
                owes_single_payment=state.owes_single_payment,
                single_payment_amount_cents=state.single_payment_amount_cents,
                prebuilt_team_number=state.prebuilt_team_number,
            )
        )
    if commit:
        await session.commit()
    else:
        await session.flush()

    return WeeklyAttendanceResponse(
        type="weekly_attendance",
        game_date=attendance.game_date,
        cutoff_at=attendance.cutoff_at,
        capacity=attendance.capacity,
        entries=[_weekly_entry_to_response(state) for state in states],
    )


async def promote_due_weekly_attendances(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> PromoteDueResponse:
    reference_time = _normalize_reference_time(now)
    result = await session.execute(
        select(WeeklyAttendance)
        .options(selectinload(WeeklyAttendance.entries))
        .where(WeeklyAttendance.cutoff_at <= reference_time)
    )
    attendances = result.scalars().unique().all()
    processed: list[PromotionResult] = []

    for attendance in attendances:
        monthly_names = await _get_monthly_subscriber_names(
            session,
            month=attendance.game_date.month,
            year=attendance.game_date.year,
        )
        lines = [
            ParsedWeeklyAttendanceLine(
                section=entry.source_section,
                position=entry.source_position,
                name=entry.name,
                normalized_name=entry.normalized_name,
                invited_by=entry.invited_by,
                normalized_invited_by=entry.normalized_invited_by,
                prebuilt_team_number=entry.prebuilt_team_number,
            )
            for entry in sorted(attendance.entries, key=lambda item: item.display_order)
        ]
        states = _build_entry_states(
            lines,
            monthly_names=monthly_names,
            capacity=attendance.capacity,
            after_cutoff=True,
        )
        promoted: list[WeeklyAttendanceEntryResponse] = []
        entries_by_key = {
            (entry.source_section, entry.source_position): entry for entry in attendance.entries
        }
        for state in states:
            entry = entries_by_key[(state.section, state.position)]
            was_waiting = entry.status == "waiting"
            entry.status = state.status
            entry.is_monthly_subscriber = state.is_monthly_subscriber
            entry.owes_single_payment = state.owes_single_payment
            entry.single_payment_amount_cents = state.single_payment_amount_cents
            if was_waiting and state.status == "main":
                promoted.append(_weekly_entry_to_response(state))

        if promoted:
            processed.append(
                PromotionResult(
                    game_date=attendance.game_date,
                    promoted=promoted,
                    text=render_weekly_attendance_message(
                        attendance.game_date,
                        sorted(attendance.entries, key=lambda item: item.display_order),
                    ),
                )
            )

    await session.commit()
    return PromoteDueResponse(processed=processed)


async def get_weekly_attendance_message(
    session: AsyncSession,
    *,
    game_date: date,
) -> WeeklyAttendanceMessageResponse | None:
    result = await session.execute(
        select(WeeklyAttendance)
        .options(selectinload(WeeklyAttendance.entries))
        .where(WeeklyAttendance.game_date == game_date)
    )
    attendance = result.scalar_one_or_none()
    if attendance is None:
        return None

    return WeeklyAttendanceMessageResponse(
        game_date=attendance.game_date,
        text=render_weekly_attendance_message(
            attendance.game_date,
            sorted(attendance.entries, key=lambda item: item.display_order),
        ),
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


async def _get_weekly_attendance(
    session: AsyncSession,
    *,
    game_date,
) -> WeeklyAttendance | None:
    result = await session.execute(
        select(WeeklyAttendance)
        .options(selectinload(WeeklyAttendance.entries))
        .where(WeeklyAttendance.game_date == game_date)
    )
    return result.scalar_one_or_none()


async def _get_monthly_subscriber_names(
    session: AsyncSession,
    *,
    month: int,
    year: int,
) -> Counter[str]:
    result = await session.execute(
        select(MonthlySubscriber.normalized_name).where(
            MonthlySubscriber.month == month,
            MonthlySubscriber.year == year,
        )
    )
    return Counter(result.scalars().all())


def _has_changes(existing: MonthlySubscriber, line: ParsedSubscriberLine) -> bool:
    return (
        existing.name != line.name
        or existing.normalized_name != line.normalized_name
        or existing.has_paid != line.has_paid
    )


async def _resolve_monthly_aliases(session: AsyncSession, parsed: ParsedMonthlySubscribers):
    lines = [
        ParsedSubscriberLine(
            position=line.position, name=line.name,
            normalized_name=await resolve_normalized_name(session, line.normalized_name)
            if line.normalized_name else None,
            has_paid=line.has_paid,
        )
        for line in parsed.subscribers
    ]
    return ParsedMonthlySubscribers(parsed.month, parsed.year, parsed.title, lines)


async def _resolve_weekly_aliases(session: AsyncSession, parsed: ParsedWeeklyAttendance):
    lines = []
    for line in parsed.entries:
        lines.append(ParsedWeeklyAttendanceLine(
            section=line.section, position=line.position, name=line.name,
            normalized_name=await resolve_normalized_name(session, line.normalized_name),
            invited_by=line.invited_by,
            normalized_invited_by=await resolve_normalized_name(session, line.normalized_invited_by),
            prebuilt_team_number=line.prebuilt_team_number, is_guest=line.is_guest,
        ))
    return ParsedWeeklyAttendance(parsed.game_date, parsed.title, lines)


def _change_from_line(line: ParsedSubscriberLine) -> SubscriberChange:
    return SubscriberChange(
        position=line.position,
        name=line.name,
        has_paid=line.has_paid,
    )


def _build_cutoff_at(game_date) -> datetime:
    return datetime.combine(game_date, time(hour=16), tzinfo=LOCAL_TZ)


def _normalize_reference_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(LOCAL_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _build_entry_states(
    lines: list[ParsedWeeklyAttendanceLine],
    *,
    monthly_names: Counter[str],
    capacity: int,
    after_cutoff: bool,
) -> list[_AttendanceEntryState]:
    states: list[_AttendanceEntryState] = []
    main_slots = 0
    waiting_indexes: list[int] = []
    single_game_price_cents = get_single_game_price_cents()
    remaining_monthly_names = monthly_names.copy()

    for display_order, line in enumerate(lines, start=1):
        is_monthly_subscriber = (
            not line.is_guest and remaining_monthly_names[line.normalized_name] > 0
        )
        if is_monthly_subscriber:
            remaining_monthly_names[line.normalized_name] -= 1
        has_priority = line.section == "main" and is_monthly_subscriber
        is_main = has_priority and main_slots < capacity
        if is_main:
            main_slots += 1
        else:
            waiting_indexes.append(len(states))

        states.append(
            _AttendanceEntryState(
                section=line.section,
                position=line.position,
                display_order=display_order,
                name=line.name,
                normalized_name=line.normalized_name,
                invited_by=line.invited_by,
                normalized_invited_by=line.normalized_invited_by,
                status="main" if is_main else "waiting",
                is_monthly_subscriber=is_monthly_subscriber,
                owes_single_payment=(not is_monthly_subscriber) and is_main,
                single_payment_amount_cents=(
                    single_game_price_cents if (not is_monthly_subscriber and is_main) else None
                ),
                prebuilt_team_number=line.prebuilt_team_number,
            )
        )

    if after_cutoff:
        remaining_slots = max(capacity - main_slots, 0)
        for index in waiting_indexes[:remaining_slots]:
            current = states[index]
            states[index] = _AttendanceEntryState(
                section=current.section,
                position=current.position,
                display_order=current.display_order,
                name=current.name,
                normalized_name=current.normalized_name,
                invited_by=current.invited_by,
                normalized_invited_by=current.normalized_invited_by,
                status="main",
                is_monthly_subscriber=current.is_monthly_subscriber,
                owes_single_payment=not current.is_monthly_subscriber,
                single_payment_amount_cents=(
                    single_game_price_cents if not current.is_monthly_subscriber else None
                ),
                prebuilt_team_number=current.prebuilt_team_number,
            )

    return states


def _weekly_entry_to_response(
    entry: _AttendanceEntryState | WeeklyAttendanceEntry,
) -> WeeklyAttendanceEntryResponse:
    return WeeklyAttendanceEntryResponse(
        section=entry.section if isinstance(entry, _AttendanceEntryState) else entry.source_section,
        position=entry.position if isinstance(entry, _AttendanceEntryState) else entry.source_position,
        display_order=entry.display_order,
        name=entry.name,
        invited_by=entry.invited_by,
        status=entry.status,
        is_monthly_subscriber=entry.is_monthly_subscriber,
        owes_single_payment=entry.owes_single_payment,
        single_payment_amount_cents=entry.single_payment_amount_cents,
        prebuilt_team_number=(
            entry.prebuilt_team_number
            if isinstance(entry, _AttendanceEntryState)
            else entry.prebuilt_team_number
        ),
    )
