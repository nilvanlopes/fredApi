from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MonthlySubscriber, PersonAlias, WeeklyAttendanceEntry
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
    session: AsyncSession, *, alias: str, canonical_name: str
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
    monthly = await session.execute(
        update(MonthlySubscriber)
        .where(MonthlySubscriber.normalized_name == alias_normalized)
        .values(normalized_name=canonical_normalized)
    )
    weekly = await session.execute(
        update(WeeklyAttendanceEntry)
        .where(WeeklyAttendanceEntry.normalized_name == alias_normalized)
        .values(normalized_name=canonical_normalized)
    )
    inviter = await session.execute(
        update(WeeklyAttendanceEntry)
        .where(WeeklyAttendanceEntry.normalized_invited_by == alias_normalized)
        .values(normalized_invited_by=canonical_normalized)
    )
    return row, monthly.rowcount, weekly.rowcount, inviter.rowcount
