from datetime import date

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Charge, MonthlySubscriber, Person, PersonAlias, WeeklyAttendance, WeeklyAttendanceEntry
from app.parser import normalize_name


async def resolve_normalized_name(session: AsyncSession, value: str | None) -> str | None:
    if value is None:
        return None
    current = value
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        result = await session.execute(
            select(PersonAlias.canonical_normalized).where(
                PersonAlias.alias_normalized == current
            )
        )
        resolved = result.scalar_one_or_none()
        if resolved is None:
            return current
        current = resolved
    raise ValueError("ciclo de aliases detectado")


async def create_alias(
    session: AsyncSession, *, alias: str, canonical_name: str, user: dict | None = None,
) -> tuple[PersonAlias, int, int, int]:
    alias_normalized = normalize_name(alias)
    canonical_normalized = normalize_name(canonical_name)
    if not alias_normalized or not canonical_normalized:
        raise ValueError("alias e nome canônico devem conter letras ou números")
    if alias_normalized == canonical_normalized:
        raise ValueError("alias e nome canônico não podem ser iguais")
    existing = await session.execute(
        select(PersonAlias).where(PersonAlias.alias_normalized == alias_normalized)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"alias já cadastrado: {alias}")
    canonical_normalized = await resolve_normalized_name(session, canonical_normalized)
    conflict = await session.execute(
        select(PersonAlias).where(PersonAlias.alias_normalized == canonical_normalized)
    )
    if conflict.scalar_one_or_none() is not None:
        raise ValueError("o nome canônico informado também é alias; use o nome canônico final")
    row = PersonAlias(
        alias=alias.strip(),
        alias_normalized=alias_normalized,
        canonical_name=canonical_name.strip(),
        canonical_normalized=canonical_normalized,
    )
    session.add(row)
    await session.flush()
    monthly, weekly, inviter = await reconcile_alias_history(session, row, user=user)
    return row, monthly, weekly, inviter


async def reconcile_alias_history(
    session: AsyncSession, alias: PersonAlias, *, user: dict | None = None,
) -> tuple[int, int, int]:
    from app import management

    canonical = await session.scalar(
        select(Person).where(Person.normalized_name == alias.canonical_normalized)
    )

    async def matching_rows(model):
        candidates = await session.scalars(select(model).where(or_(
            model.normalized_name == alias.alias_normalized,
            model.person_id == canonical.id if canonical is not None else model.person_id.is_(None),
        )))
        return [row for row in candidates if row.normalized_name == alias.alias_normalized
                or normalize_name(row.name) == alias.alias_normalized]

    monthly = await matching_rows(MonthlySubscriber)
    weekly = await matching_rows(WeeklyAttendanceEntry)
    inviter = await session.execute(update(WeeklyAttendanceEntry).where(
        WeeklyAttendanceEntry.normalized_invited_by == alias.alias_normalized,
    ).values(normalized_invited_by=alias.canonical_normalized))
    if not (monthly or weekly):
        return 0, 0, inviter.rowcount or 0

    canonical_id = canonical.id if canonical is not None else None
    if any(row.person_id not in (None, canonical_id) for row in [*monthly, *weekly]):
        raise ValueError("O apelido já identifica outra pessoa cadastrada. Una os cadastros para transferir os registros.")
    if canonical is None:
        canonical = Person(name=alias.canonical_name, normalized_name=alias.canonical_normalized)
        session.add(canonical)
        await session.flush()

    for rows in (monthly, weekly):
        for row in rows:
            row.person_id = canonical.id
            row.normalized_name = canonical.normalized_name

    # Unlinked legacy subscriptions may not yet have a durable charge.
    for row in monthly:
        if row.deleted_at is not None:
            continue
        reference = date(row.year, row.month, 1)
        charge = await session.scalar(select(Charge).where(
            Charge.person_id == canonical.id,
            Charge.type == "monthly",
            Charge.reference_date == reference,
        ))
        if charge is None:
            await management.set_charge(
                session, canonical.id, "monthly", reference,
                status="paid" if row.has_paid else "pending", user=user, source="alias_reconcile",
            )
        else:
            row.has_paid = charge.status == "paid"

    await management.refresh_identity_games(
        session, {canonical.id},
        game_ids={row.attendance_id for row in weekly if row.deleted_at is None},
        months={(row.year, row.month) for row in monthly if row.deleted_at is None},
        user=user,
    )
    return len(monthly), len(weekly), inviter.rowcount or 0


async def detach_alias_history(
    session: AsyncSession, *, alias: str, canonical: Person, user: dict | None = None,
) -> dict[str, int]:
    """Move legacy rows still carrying an alias spelling to its own person.

    Alias creation historically rewrote normalized_name to the canonical name,
    while keeping the imported display spelling. That lets removal recover
    these rows without guessing from names that have already been overwritten.
    """
    normalized = normalize_name(alias)
    if not normalized or normalized == canonical.normalized_name:
        return {"weekly": 0, "monthly": 0, "inviter": 0}
    weekly_rows = [row for row in await session.scalars(select(WeeklyAttendanceEntry).where(
        WeeklyAttendanceEntry.person_id == canonical.id,
    )) if normalize_name(row.name) == normalized]
    monthly_rows = [row for row in await session.scalars(select(MonthlySubscriber).where(
        MonthlySubscriber.person_id == canonical.id,
    )) if normalize_name(row.name) == normalized]
    inviter_rows = [row for row in await session.scalars(select(WeeklyAttendanceEntry).where(
        WeeklyAttendanceEntry.normalized_invited_by == canonical.normalized_name,
        WeeklyAttendanceEntry.invited_by.is_not(None),
    )) if normalize_name(row.invited_by) == normalized]
    for entry in inviter_rows:
        entry.normalized_invited_by = normalized
    if not (weekly_rows or monthly_rows):
        return {"weekly": 0, "monthly": 0, "inviter": len(inviter_rows), "single_charges": 0}

    detached = await session.scalar(select(Person).where(Person.normalized_name == normalized))
    if detached is None:
        detached = Person(name=alias.strip(), normalized_name=normalized, active=True)
        session.add(detached)
        await session.flush()

    alias_game_ids = {entry.attendance_id for entry in weekly_rows if entry.deleted_at is None}
    for entry in weekly_rows:
        entry.person_id = detached.id
        entry.normalized_name = normalized

    moved_monthly = []
    for row in monthly_rows:
        collision = await session.scalar(select(MonthlySubscriber.id).where(
            MonthlySubscriber.person_id == detached.id,
            MonthlySubscriber.month == row.month,
            MonthlySubscriber.year == row.year,
            MonthlySubscriber.deleted_at.is_(None),
            MonthlySubscriber.id != row.id,
        ).limit(1))
        if collision is None:
            row.person_id = detached.id
            row.normalized_name = normalized
            moved_monthly.append(row)

    # Transfer monthly charges only when the recovered person has no charge
    # for that month. A game charge moves only when the source identity has
    # exactly one active row in that game and it is this alias spelling.
    moved_months = {(row.year, row.month) for row in moved_monthly if row.deleted_at is None}
    for year, month in sorted(moved_months):
        remaining = await session.scalar(select(MonthlySubscriber.id).where(
            MonthlySubscriber.person_id == canonical.id,
            MonthlySubscriber.year == year,
            MonthlySubscriber.month == month,
            MonthlySubscriber.deleted_at.is_(None),
        ).limit(1))
        if remaining is None:
            await transfer_charge(session, canonical.id, detached.id, "monthly", date(year, month, 1))

    moved_single_charges = 0
    for game_id in sorted(alias_game_ids):
        active = (await session.scalars(select(WeeklyAttendanceEntry).where(
            WeeklyAttendanceEntry.attendance_id == game_id,
            WeeklyAttendanceEntry.person_id.in_((canonical.id, detached.id)),
            WeeklyAttendanceEntry.deleted_at.is_(None),
        ).limit(2))).all()
        if len(active) != 1:
            continue
        game = await session.get(WeeklyAttendance, game_id)
        if await transfer_charge(session, canonical.id, detached.id, "single", game.game_date):
            moved_single_charges += 1

    from app import management
    await management.refresh_identity_games(session, {canonical.id, detached.id}, game_ids=alias_game_ids,
                                            months=moved_months, user=user)
    return {"weekly": len(weekly_rows), "monthly": len(moved_monthly),
            "inviter": len(inviter_rows), "single_charges": moved_single_charges}


async def transfer_charge(session, source_id, target_id, kind, reference_date) -> bool:
    charges = (await session.scalars(select(Charge).where(
        Charge.person_id.in_((source_id, target_id)),
        Charge.type == kind,
        Charge.reference_date == reference_date,
    ))).all()
    if len(charges) == 1 and charges[0].person_id == source_id:
        charges[0].person_id = target_id
        return True
    return False
