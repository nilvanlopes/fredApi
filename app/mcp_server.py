from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import MonthlySubscriber, WeeklyAttendance, WeeklyAttendanceEntry


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
    normalized_name = name.strip().casefold()
    matches: list[PersonMatch] = []
    async with SessionLocal() as session:
        monthly_query = select(MonthlySubscriber).where(
            func.lower(MonthlySubscriber.name).contains(normalized_name)
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
            .where(func.lower(WeeklyAttendanceEntry.name).contains(normalized_name))
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


def main() -> None:
    import asyncio

    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
