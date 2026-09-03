from datetime import date, datetime, timezone
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_conversation_import_max_bytes
from app.conversation_ai import ConversationAIError
from app.conversation_import import (
    process_conversation_import,
    record_realtime_processed_message,
)
from app.database import get_session
from app.aliases import create_alias
from app.message_templates import (
    local_reference_date,
    render_monthly_subscribers_template,
    render_weekly_attendance_template,
)
from app.ollama_service import (
    OllamaServiceError,
    start_ollama_for_agent,
    stop_ollama_after_agent,
)
from app.parser import ParseError, parse_monthly_subscribers_message
from app.schemas import (
    ConversationImportResponse,
    MonthlyMessageTemplateResponse,
    ProcessMessageRequest,
    ProcessMessageResponse,
    PromoteDueResponse,
    WeeklyAttendanceMessageResponse,
    WeeklyAttendanceResponse,
    WeeklyMessageTemplateResponse,
    PersonAliasRequest,
    PersonAliasResponse,
)
from app.whatsapp_export import WhatsAppExportError
from app.services import (
    get_weekly_attendance_message,
    process_monthly_subscribers_message,
    process_weekly_attendance_message,
    promote_due_weekly_attendances,
)

app = FastAPI(title="Volei Frederico API")


class OllamaStopRequest(BaseModel):
    started_by_us: bool = False


@app.post("/internal/ollama/start")
async def start_ephemeral_ollama() -> dict[str, bool]:
    try:
        started_by_us = await start_ollama_for_agent()
    except OllamaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"started_by_us": started_by_us}


@app.post("/internal/ollama/stop")
async def stop_ephemeral_ollama(payload: OllamaStopRequest) -> dict[str, bool]:
    try:
        await stop_ollama_after_agent(payload.started_by_us)
    except OllamaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"stopped": payload.started_by_us}


@app.post("/person-aliases", response_model=PersonAliasResponse, status_code=201)
async def add_person_alias(
    payload: PersonAliasRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonAliasResponse:
    try:
        row, monthly, weekly, inviter = await create_alias(
            session, alias=payload.alias, canonical_name=payload.canonical_name
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PersonAliasResponse(
        alias=row.alias, alias_normalized=row.alias_normalized,
        canonical_name=row.canonical_name, canonical_normalized=row.canonical_normalized,
        updated_monthly=monthly, updated_weekly=weekly, updated_inviter=inviter,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/messages/templates/monthly-subscribers",
    response_model=MonthlyMessageTemplateResponse,
)
async def monthly_subscribers_template(
    reference_date: date | None = Query(default=None),
) -> MonthlyMessageTemplateResponse:
    resolved_date = local_reference_date(reference_date)
    return MonthlyMessageTemplateResponse(
        type="monthly_subscribers",
        reference_date=resolved_date,
        month=resolved_date.month,
        year=resolved_date.year,
        text=render_monthly_subscribers_template(resolved_date),
    )


@app.get(
    "/messages/templates/weekly-attendance",
    response_model=WeeklyMessageTemplateResponse,
)
async def weekly_attendance_template(
    reference_date: date | None = Query(default=None),
) -> WeeklyMessageTemplateResponse:
    resolved_date = local_reference_date(reference_date)
    game_date, text = render_weekly_attendance_template(resolved_date)
    return WeeklyMessageTemplateResponse(
        type="weekly_attendance",
        reference_date=resolved_date,
        game_date=game_date,
        text=text,
    )


@app.post(
    "/conversation-imports",
    response_model=ConversationImportResponse,
    status_code=200,
)
async def import_conversation(
    body: bytes = Body(media_type="text/plain"),
    mode: Literal["preview", "apply"] = Query(default="preview"),
    analysis_mode: Literal["rules", "hybrid", "ai"] = Query(default="hybrid"),
    chat_id: str = Query(default="fred", min_length=1, max_length=200),
    timezone_name: str = Query(default="America/Sao_Paulo", alias="timezone"),
    session: AsyncSession = Depends(get_session),
) -> ConversationImportResponse:
    if len(body) > get_conversation_import_max_bytes():
        raise HTTPException(status_code=413, detail="export excede o limite configurado")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="export deve estar em UTF-8") from exc

    try:
        return await process_conversation_import(
            session,
            text=text,
            mode=mode,
            analysis_mode=analysis_mode,
            chat_id=chat_id,
            timezone_name=timezone_name,
        )
    except WhatsAppExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConversationAIError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/messages/process",
    response_model=ProcessMessageResponse | WeeklyAttendanceResponse,
)
async def process_message(
    payload: ProcessMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> ProcessMessageResponse | WeeklyAttendanceResponse:
    try:
        parse_monthly_subscribers_message(payload.text, received_at=payload.received_at)
        result = await process_monthly_subscribers_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
            commit=False,
        )
        await record_realtime_processed_message(
            session,
            chat_id=payload.chat_id or "fred",
            text=payload.text,
            occurred_at=payload.received_at or datetime.now(timezone.utc),
            sender_name=payload.sender_name,
            message_id=payload.message_id,
            source=payload.source,
            message_type="monthly_subscribers",
            aggregate_key=f"monthly:{result.year:04d}-{result.month:02d}",
            status="applied" if result.created or result.updated or result.deleted else "unchanged",
            result=result.model_dump(mode="json"),
        )
        await session.commit()
        return result
    except ParseError as exc:
        monthly_error = exc

    try:
        result = await process_weekly_attendance_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
            commit=False,
        )
        await record_realtime_processed_message(
            session,
            chat_id=payload.chat_id or "fred",
            text=payload.text,
            occurred_at=payload.received_at or datetime.now(timezone.utc),
            sender_name=payload.sender_name,
            message_id=payload.message_id,
            source=payload.source,
            message_type="weekly_attendance",
            aggregate_key=f"weekly:{result.game_date.isoformat()}",
            status="applied",
            result=result.model_dump(mode="json"),
        )
        await session.commit()
        return result
    except ParseError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "monthly_error": str(monthly_error),
                "weekly_error": str(exc),
            },
        ) from exc


@app.post(
    "/messages/monthly-subscribers/process",
    response_model=ProcessMessageResponse,
)
async def process_monthly_message(
    payload: ProcessMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> ProcessMessageResponse:
    try:
        return await process_monthly_subscribers_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
        )
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/messages/weekly-attendance/process",
    response_model=WeeklyAttendanceResponse,
)
async def process_weekly_message(
    payload: ProcessMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> WeeklyAttendanceResponse:
    try:
        return await process_weekly_attendance_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
        )
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/weekly-attendance/promote-due",
    response_model=PromoteDueResponse,
)
async def promote_due_attendances(
    session: AsyncSession = Depends(get_session),
) -> PromoteDueResponse:
    return await promote_due_weekly_attendances(session)


@app.get(
    "/weekly-attendance/message",
    response_model=WeeklyAttendanceMessageResponse,
)
async def weekly_attendance_message(
    game_date: date | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> WeeklyAttendanceMessageResponse:
    resolved_date = game_date or local_reference_date()
    result = await get_weekly_attendance_message(
        session,
        game_date=resolved_date,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"lista semanal de {resolved_date.isoformat()} não encontrada",
        )
    return result
