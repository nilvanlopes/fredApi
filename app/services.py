from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_single_game_price_cents, get_weekly_attendance_capacity
from app.aliases import resolve_normalized_name
from app.message_templates import render_weekly_attendance_message
from app.models import (
    Charge,
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
        received_at=received_at,
    )


async def apply_monthly_subscribers(
    session: AsyncSession, *, parsed: ParsedMonthlySubscribers, commit: bool = True,
    received_at: datetime | None = None,
) -> ProcessMessageResponse:
    from app import management as d
    from app.models import Person
    parsed = await _resolve_monthly_aliases(session, parsed)
    created, updated, deleted, unchanged = [], [], [], []
    timestamp=d.aware(received_at)
    await d.lock(session,f"monthly:{parsed.year:04d}-{parsed.month:02d}")
    for line in parsed.subscribers:
        existing = await _get_by_position(session, month=parsed.month, year=parsed.year, position=line.position)
        if line.name is None:
            if existing:
                await d.monthly_remove(session,existing,at=timestamp,source="whatsapp")
                deleted.append(SubscriberChange(position=line.position,name=existing.name))
            continue
        person=await d.person_for_name(session,line.name)
        if existing is not None and existing.person_id!=person.id:
            await d.monthly_remove(session,existing,at=timestamp,source="whatsapp")
            await session.flush()
            if existing.deleted_at is None:
                unchanged.append(_change_from_line(line))
                continue
        category=created if existing is None else (updated if _has_changes(existing,line) else unchanged)
        await d.monthly_upsert(session,person,parsed.month,parsed.year,has_paid=line.has_paid,position=line.position,at=timestamp,source="whatsapp",source_name=line.name)
        category.append(_change_from_line(line))
    if commit: await session.commit()
    else: await session.flush()
    return ProcessMessageResponse(type="monthly_subscribers",month=parsed.month,year=parsed.year,created=created,updated=updated,deleted=deleted,unchanged=unchanged)


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
    session: AsyncSession, *, parsed: ParsedWeeklyAttendance,
    received_at: datetime | None = None, commit: bool = True,
) -> WeeklyAttendanceResponse:
    from app import management as d
    parsed=await _resolve_weekly_aliases(session,parsed)
    timestamp=d.aware(received_at)
    await d.lock(session,f"weekly-date:{parsed.game_date}")
    attendance=await _get_weekly_attendance(session,game_date=parsed.game_date)
    if attendance is None:
        attendance=WeeklyAttendance(game_date=parsed.game_date,capacity=get_weekly_attendance_capacity(),cutoff_at=_build_cutoff_at(parsed.game_date),starts_at=datetime.combine(parsed.game_date,time(19,30),LOCAL_TZ))
        session.add(attendance)
        await session.flush()
    await d.lock(session,f"game:{attendance.id}")
    persons=[await d.person_for_name(session,line.name) for line in parsed.entries]
    incoming={p.id for p in persons}
    for entry in await d.active_entries(session,attendance.id):
        if entry.person_id not in incoming:
            await d.remove_entry(session,attendance,entry,at=timestamp,source="whatsapp")
    applied_entries=[]
    for line,person in zip(parsed.entries,persons):
        entry=await d.add_entry(session,attendance,person,at=timestamp,source="whatsapp",invited_by=line.invited_by,section=line.section,team=line.prebuilt_team_number,source_name=line.name)
        if entry is not None:
            applied_entries.append((line,entry))
    current_entries=await d.active_entries(session,attendance.id)
    max_position=max((entry.source_position or 0 for entry in current_entries),default=0)
    for index,entry in enumerate(current_entries,1):
        entry.source_position=max_position+len(current_entries)+index
    await session.flush()
    for display_order, (line, entry) in enumerate(applied_entries, 1):
        entry.display_order=display_order
        entry.source_position=line.position
        entry.source_section=line.section
    await d.recalculate(
        session, attendance, timestamp, source="whatsapp",
        defer_snapshot_charges=True,
    )
    paid_person_ids = {
        entry.person_id for line, entry in applied_entries
        if line.has_paid and entry.person_id is not None
    }
    await d.reconcile_weekly_snapshot_charges(
        session, attendance, occurred_at=timestamp, source="whatsapp", paid_person_ids=paid_person_ids,
    )
    entries=await d.active_entries(session,attendance.id)
    if commit: await session.commit()
    else: await session.flush()
    return WeeklyAttendanceResponse(type="weekly_attendance",game_date=attendance.game_date,cutoff_at=attendance.cutoff_at,capacity=attendance.capacity,entries=[_weekly_entry_to_response(e) for e in entries])


async def promote_due_weekly_attendances(session: AsyncSession, *, now: datetime | None = None) -> PromoteDueResponse:
    from app import management as d
    reference=d.aware(now)
    attendances=(await session.scalars(select(WeeklyAttendance).where(WeeklyAttendance.cutoff_at<=reference))).all()
    processed=[]
    for attendance in attendances:
        if reference >= d.starts(attendance):
            continue
        await d.lock(session,f"game:{attendance.id}")
        before={e.id:e.status for e in await d.active_entries(session,attendance.id)}
        await d.recalculate(session,attendance,reference,source="promotion")
        entries=await d.active_entries(session,attendance.id)
        promoted=[_weekly_entry_to_response(e) for e in entries if before.get(e.id)=="waiting" and e.status=="main"]
        if promoted:
            processed.append(PromotionResult(game_date=attendance.game_date,promoted=promoted,text=render_weekly_attendance_message(attendance.game_date,entries)))
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
            sorted([e for e in attendance.entries if getattr(e,"deleted_at",None) is None], key=lambda item: item.display_order),
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
            MonthlySubscriber.deleted_at.is_(None),
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
        select(MonthlySubscriber.normalized_name)
        .join(
            Charge,
            (Charge.person_id == MonthlySubscriber.person_id)
            & (Charge.type == "monthly")
            & (Charge.reference_date == date(year, month, 1))
            & (Charge.status == "paid"),
        )
        .where(
            MonthlySubscriber.month == month,
            MonthlySubscriber.year == year,
            MonthlySubscriber.deleted_at.is_(None),
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
        lines.append(replace(
            line,
            normalized_name=await resolve_normalized_name(session, line.normalized_name),
            normalized_invited_by=await resolve_normalized_name(session, line.normalized_invited_by),
        ))
    return ParsedWeeklyAttendance(
        parsed.game_date, parsed.title, lines,
        numbering_corrected=parsed.numbering_corrected,
    )


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
        is_main = (after_cutoff or has_priority) and main_slots < capacity
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
