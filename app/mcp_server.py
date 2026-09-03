from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import get_monthly_subscription_price_cents
from app.aliases import resolve_normalized_name
from app.database import SessionLocal
from app.models import MonthlySubscriber, PersonAlias, WeeklyAttendance, WeeklyAttendanceEntry
from app.parser import normalize_name


LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

mcp = MCPServer(
    "Fred",
    instructions=(
        "Consulte os dados do Vôlei Frederico usando as ferramentas de domínio. "
        "As ferramentas são somente leitura. Não invente dados quando found=false "
        "ou quando uma busca não retornar resultados."
    ),
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


class WeeklyEntry(BaseModel):
    position: int
    source_section: Literal["main", "guests"]
    name: str
    invited_by: str | None = None
    is_monthly_subscriber: bool
    owes_single_payment: bool
    single_payment_amount_cents: int | None = None
    prebuilt_team_number: int | None = None


class WeeklyAttendanceResult(BaseModel):
    found: bool
    game_date: date
    capacity: int | None = None
    cutoff_at: datetime | None = None
    main: list[WeeklyEntry] = Field(default_factory=list)
    waiting: list[WeeklyEntry] = Field(default_factory=list)


class MonthlySubscriberResult(BaseModel):
    month: int
    year: int
    subscribers: list["Subscriber"] = Field(default_factory=list)


class Subscriber(BaseModel):
    position: int
    name: str
    has_paid: bool


class PersonMatch(BaseModel):
    list_type: Literal["monthly_subscriber", "weekly_attendance"]
    game_date: date | None = None
    month: int | None = None
    year: int | None = None
    position: int
    name: str
    status: Literal["main", "waiting"] | None = None
    is_monthly_subscriber: bool | None = None
    has_paid: bool | None = None
    owes_single_payment: bool | None = None
    single_payment_amount_cents: int | None = None


class PersonSearchResult(BaseModel):
    query: str
    matches: list[PersonMatch] = Field(default_factory=list)


class PersonAliasesResult(BaseModel):
    query: str
    canonical_name: str
    canonical_normalized: str
    aliases: list[str] = Field(default_factory=list)


class MonthlyUnpaidEntry(BaseModel):
    month: int
    year: int
    position: int
    name: str
    amount_cents: int


class SinglePaymentUnpaidEntry(BaseModel):
    game_date: date
    position: int
    name: str
    source_section: Literal["main", "guests"]
    status: Literal["main", "waiting"]
    is_monthly_subscriber: bool
    amount_cents: int


class PersonPaymentSummary(BaseModel):
    query: str
    start_date: date
    end_date: date
    monthly_unpaid: list[MonthlyUnpaidEntry] = Field(default_factory=list)
    single_payment_unpaid: list[SinglePaymentUnpaidEntry] = Field(default_factory=list)
    monthly_unpaid_total_cents: int
    single_payment_unpaid_total_cents: int
    total_unpaid_cents: int


def _reference_date(value: date | None) -> date:
    return value or datetime.now(LOCAL_TZ).date()


def _resolve_wednesday(reference_date: date | None) -> date:
    current = _reference_date(reference_date)
    return current + timedelta(days=(2 - current.weekday()) % 7)


def _entry_response(entry: WeeklyAttendanceEntry, position: int) -> WeeklyEntry:
    return WeeklyEntry(
        position=position,
        source_section=entry.source_section,
        name=entry.name,
        invited_by=entry.invited_by,
        is_monthly_subscriber=entry.is_monthly_subscriber,
        owes_single_payment=entry.owes_single_payment,
        single_payment_amount_cents=entry.single_payment_amount_cents,
        prebuilt_team_number=entry.prebuilt_team_number,
    )


@mcp.tool(annotations=READ_ONLY)
async def get_weekly_attendance(
    game_date: Annotated[
        date | None,
        Field(description="Quarta-feira da lista. Se omitida, usa a quarta atual ou próxima."),
    ] = None,
) -> WeeklyAttendanceResult:
    """Consulta a lista semanal, separando lista principal e convidados aguardando."""
    resolved_date = _resolve_wednesday(game_date)
    async with SessionLocal() as session:
        result = await session.execute(
            select(WeeklyAttendance)
            .options(selectinload(WeeklyAttendance.entries))
            .where(WeeklyAttendance.game_date == resolved_date)
        )
        attendance = result.scalar_one_or_none()

    if attendance is None:
        return WeeklyAttendanceResult(found=False, game_date=resolved_date)

    entries = sorted(attendance.entries, key=lambda entry: entry.display_order)
    main = [entry for entry in entries if entry.status == "main"]
    waiting = [entry for entry in entries if entry.status == "waiting"]
    return WeeklyAttendanceResult(
        found=True,
        game_date=attendance.game_date,
        capacity=attendance.capacity,
        cutoff_at=attendance.cutoff_at,
        main=[_entry_response(entry, position) for position, entry in enumerate(main, 1)],
        waiting=[
            _entry_response(entry, position) for position, entry in enumerate(waiting, 1)
        ],
    )


@mcp.tool(annotations=READ_ONLY)
async def get_monthly_subscribers(
    month: Annotated[int, Field(ge=1, le=12, description="Mês da lista, de 1 a 12.")],
    year: Annotated[int, Field(ge=2000, le=2200, description="Ano da lista.")],
) -> MonthlySubscriberResult:
    """Consulta os assinantes mensais de um mês e ano específicos."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(MonthlySubscriber)
            .where(
                MonthlySubscriber.month == month,
                MonthlySubscriber.year == year,
            )
            .order_by(MonthlySubscriber.position)
        )
        subscribers = result.scalars().all()

    return MonthlySubscriberResult(
        month=month,
        year=year,
        subscribers=[
            Subscriber(
                position=subscriber.position,
                name=subscriber.name,
                has_paid=subscriber.has_paid,
            )
            for subscriber in subscribers
        ],
    )


@mcp.tool(annotations=READ_ONLY)
async def list_waiting_guests(
    game_date: Annotated[
        date | None,
        Field(description="Quarta-feira da lista. Se omitida, usa a quarta atual ou próxima."),
    ] = None,
) -> WeeklyAttendanceResult:
    """Lista somente os participantes que ainda estão aguardando vaga."""
    attendance = await get_weekly_attendance(game_date)
    return WeeklyAttendanceResult(
        found=attendance.found,
        game_date=attendance.game_date,
        capacity=attendance.capacity,
        cutoff_at=attendance.cutoff_at,
        waiting=attendance.waiting,
    )


@mcp.tool(annotations=READ_ONLY)
async def search_person(
    name: Annotated[str, Field(min_length=1, max_length=100, description="Nome ou parte do nome.")],
    game_date: Annotated[date | None, Field(description="Limita a busca semanal a uma data.")] = None,
    unpaid_only: Annotated[
        bool,
        Field(description="Retorna somente entradas com pagamento pendente."),
    ] = False,
) -> PersonSearchResult:
    """Busca uma pessoa nas listas mensais e semanais, opcionalmente só pendentes."""
    normalized_name = normalize_name(name)
    matches: list[PersonMatch] = []
    async with SessionLocal() as session:
        normalized_name = await resolve_normalized_name(session, normalized_name) or normalized_name
        monthly_query = select(MonthlySubscriber).where(
            MonthlySubscriber.normalized_name.contains(normalized_name)
        )
        if unpaid_only:
            monthly_query = monthly_query.where(MonthlySubscriber.has_paid.is_(False))
        monthly_query = monthly_query.order_by(
            MonthlySubscriber.year, MonthlySubscriber.month, MonthlySubscriber.position
        )
        monthly_result = await session.execute(monthly_query)
        for subscriber in monthly_result.scalars():
            matches.append(
                PersonMatch(
                    list_type="monthly_subscriber",
                    month=subscriber.month,
                    year=subscriber.year,
                    position=subscriber.position,
                    name=subscriber.name,
                    has_paid=subscriber.has_paid,
                )
            )

        weekly_query = (
            select(WeeklyAttendanceEntry)
            .options(selectinload(WeeklyAttendanceEntry.attendance))
            .join(WeeklyAttendance)
            .where(WeeklyAttendanceEntry.normalized_name.contains(normalized_name))
            .order_by(WeeklyAttendance.game_date, WeeklyAttendanceEntry.display_order)
        )
        if unpaid_only:
            weekly_query = weekly_query.where(WeeklyAttendanceEntry.owes_single_payment.is_(True))
        if game_date is not None:
            weekly_query = weekly_query.where(WeeklyAttendance.game_date == game_date)
        weekly_result = await session.execute(weekly_query)
        for entry in weekly_result.scalars():
            matches.append(
                PersonMatch(
                    list_type="weekly_attendance",
                    game_date=entry.attendance.game_date,
                    position=entry.source_position,
                    name=entry.name,
                    status=entry.status,
                    is_monthly_subscriber=entry.is_monthly_subscriber,
                    owes_single_payment=entry.owes_single_payment,
                    single_payment_amount_cents=entry.single_payment_amount_cents,
                )
            )

    return PersonSearchResult(query=name, matches=matches)


@mcp.tool(annotations=READ_ONLY)
async def get_person_aliases(
    name: Annotated[str, Field(min_length=1, max_length=100, description="Nome padrão ou apelido.")],
) -> PersonAliasesResult:
    """Retorna o nome padrão e todos os aliases cadastrados para uma pessoa."""
    normalized_name = normalize_name(name)
    async with SessionLocal() as session:
        canonical_normalized = await resolve_normalized_name(session, normalized_name)
        alias_result = await session.execute(
            select(PersonAlias)
            .where(PersonAlias.canonical_normalized == canonical_normalized)
            .order_by(PersonAlias.alias_normalized)
        )
        aliases = alias_result.scalars().all()

    canonical_name = aliases[0].canonical_name if aliases else name.strip()
    return PersonAliasesResult(
        query=name,
        canonical_name=canonical_name,
        canonical_normalized=canonical_normalized,
        aliases=[alias.alias for alias in aliases],
    )


@mcp.tool(annotations=READ_ONLY)
async def get_person_payment_summary(
    name: Annotated[str, Field(min_length=1, max_length=100, description="Nome ou parte do nome.")],
    start_date: Annotated[date, Field(description="Início inclusivo do período da consulta.")],
    end_date: Annotated[date, Field(description="Fim inclusivo do período da consulta.")],
) -> PersonPaymentSummary:
    """Resume mensalidades e partidas avulsas pendentes de uma pessoa no período."""
    if end_date < start_date:
        raise ValueError("end_date deve ser maior ou igual a start_date")

    normalized_name = normalize_name(name)
    monthly_unpaid: list[MonthlyUnpaidEntry] = []
    single_payment_unpaid: list[SinglePaymentUnpaidEntry] = []
    monthly_amount_cents = get_monthly_subscription_price_cents()

    async with SessionLocal() as session:
        normalized_name = await resolve_normalized_name(session, normalized_name) or normalized_name
        monthly_result = await session.execute(
            select(MonthlySubscriber)
            .where(
                MonthlySubscriber.normalized_name.contains(normalized_name),
                MonthlySubscriber.has_paid.is_(False),
            )
            .order_by(MonthlySubscriber.year, MonthlySubscriber.month, MonthlySubscriber.position)
        )
        for subscriber in monthly_result.scalars():
            reference = date(subscriber.year, subscriber.month, 1)
            if start_date <= reference <= end_date:
                monthly_unpaid.append(
                    MonthlyUnpaidEntry(
                        month=subscriber.month,
                        year=subscriber.year,
                        position=subscriber.position,
                        name=subscriber.name,
                        amount_cents=monthly_amount_cents,
                    )
                )

        weekly_result = await session.execute(
            select(WeeklyAttendanceEntry)
            .options(selectinload(WeeklyAttendanceEntry.attendance))
            .join(WeeklyAttendance)
            .where(
                WeeklyAttendanceEntry.normalized_name.contains(normalized_name),
                WeeklyAttendanceEntry.owes_single_payment.is_(True),
                WeeklyAttendance.game_date >= start_date,
                WeeklyAttendance.game_date <= end_date,
            )
            .order_by(WeeklyAttendance.game_date, WeeklyAttendanceEntry.display_order)
        )
        for entry in weekly_result.scalars():
            single_payment_unpaid.append(
                SinglePaymentUnpaidEntry(
                    game_date=entry.attendance.game_date,
                    position=entry.source_position,
                    name=entry.name,
                    source_section=entry.source_section,
                    status=entry.status,
                    is_monthly_subscriber=entry.is_monthly_subscriber,
                    amount_cents=entry.single_payment_amount_cents or 0,
                )
            )

    monthly_total = sum(entry.amount_cents for entry in monthly_unpaid)
    single_payment_total = sum(entry.amount_cents for entry in single_payment_unpaid)
    return PersonPaymentSummary(
        query=name,
        start_date=start_date,
        end_date=end_date,
        monthly_unpaid=monthly_unpaid,
        single_payment_unpaid=single_payment_unpaid,
        monthly_unpaid_total_cents=monthly_total,
        single_payment_unpaid_total_cents=single_payment_total,
        total_unpaid_cents=monthly_total + single_payment_total,
    )


def main() -> None:
    import asyncio

    asyncio.run(mcp.run_stdio_async())


def main_http() -> None:
    import asyncio

    asyncio.run(
        mcp.run_streamable_http_async(
            host="0.0.0.0",
            port=8000,
            streamable_http_path="/mcp",
        )
    )


if __name__ == "__main__":
    main()
