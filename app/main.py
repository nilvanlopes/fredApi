from datetime import date, datetime, time, timezone
import os
from typing import Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import management as d
from app.config import get_conversation_import_max_bytes
from app.conversation_ai import ConversationAIError
from app.conversation_import import (
    find_realtime_message,
    process_conversation_import,
    record_realtime_processed_message,
)
from app.list_sources import link_message_to_entries
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
from app.parser import ParseError, parse_monthly_subscribers_message, parse_weekly_attendance_message
from app.payment_notifications import empty_weekly_list_message, payment_notification_lifespan
from app.schemas import (
    ConversationImportResponse,
    MonthlyMessageTemplateResponse,
    ProcessMessageRequest,
    ProcessMessageResponse,
    PromoteDueResponse,
    RecordSentMessageRequest,
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
    promote_due_weekly_attendances,
)
from app.weekly_guest_invitations import process_live_weekly_snapshot

app = FastAPI(title="Volei Frederico API", lifespan=payment_notification_lifespan)


class OllamaStopRequest(BaseModel):
    started_by_us: bool = False


async def require_internal_agent_key(
    x_fred_agent_key: str | None = Header(default=None),
) -> None:
    expected = os.getenv("FRED_AGENT_KEY", "").strip()
    if not expected or x_fred_agent_key != expected:
        raise HTTPException(status_code=401, detail="chave interna inválida")


@app.post("/internal/ollama/start", dependencies=[Depends(require_internal_agent_key)])
async def start_ephemeral_ollama() -> dict[str, bool]:
    try:
        started_by_us = await start_ollama_for_agent()
    except OllamaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"started_by_us": started_by_us}


@app.post("/internal/ollama/stop", dependencies=[Depends(require_internal_agent_key)])
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
    chat_id = payload.chat_id or "fred"
    previous = await find_realtime_message(session, chat_id=chat_id, message_id=payload.message_id)
    if previous is not None:
        return (ProcessMessageResponse.model_validate(previous.result)
                if previous.message_type == "monthly_subscribers"
                else WeeklyAttendanceResponse.model_validate(previous.result))
    try:
        parse_monthly_subscribers_message(payload.text, received_at=payload.received_at)
        result = await process_monthly_subscribers_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
            commit=False,
        )
        message_id = await record_realtime_processed_message(
            session,
            chat_id=chat_id,
            text=payload.text,
            occurred_at=payload.received_at or datetime.now(timezone.utc),
            sender_name=payload.sender_name,
            sender_id=payload.sender_id,
            message_id=payload.message_id,
            source=payload.source,
            message_type="monthly_subscribers",
            aggregate_key=f"monthly:{result.year:04d}-{result.month:02d}",
            status="applied" if result.created or result.updated or result.deleted else "unchanged",
            result=result.model_dump(mode="json"),
        )
        await link_message_to_entries(session,message_id=message_id,message_type="monthly_subscribers",
                                      text=payload.text,occurred_at=payload.received_at or datetime.now(timezone.utc))
        await session.commit()
        return result
    except ParseError as exc:
        monthly_error = exc

    try:
        return await _process_and_record_weekly_message(session, payload, chat_id)
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
    chat_id=payload.chat_id or "fred"
    previous=await find_realtime_message(session,chat_id=chat_id,message_id=payload.message_id)
    if previous is not None:
        if previous.message_type!="monthly_subscribers":
            raise HTTPException(409,"ID WhatsApp já usado por outra mensagem")
        return ProcessMessageResponse.model_validate(previous.result)
    try:
        result=await process_monthly_subscribers_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
            commit=False,
        )
        occurred_at=payload.received_at or datetime.now(timezone.utc)
        status="applied" if result.created or result.updated or result.deleted else "unchanged"
        message_id=await record_realtime_processed_message(session,chat_id=chat_id,text=payload.text,
            occurred_at=occurred_at,sender_name=payload.sender_name,sender_id=payload.sender_id,
            message_id=payload.message_id,source=payload.source,message_type="monthly_subscribers",
            aggregate_key=f"monthly:{result.year:04d}-{result.month:02d}",status=status,
            result=result.model_dump(mode="json"))
        await link_message_to_entries(session,message_id=message_id,message_type="monthly_subscribers",
                                      text=payload.text,occurred_at=occurred_at)
        from app.audit_history import record_list_history
        await record_list_history(session, message_id=message_id, message_type="monthly_subscribers",
            chat_id=chat_id, aggregate_key=f"monthly:{result.year:04d}-{result.month:02d}",
            text=payload.text, occurred_at=occurred_at, status=status,
            sender_contact_name=payload.sender_contact_name, sender_name=payload.sender_name)
        await session.commit()
        return result
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
    chat_id=payload.chat_id or "fred"
    previous=await find_realtime_message(session,chat_id=chat_id,message_id=payload.message_id)
    if previous is not None:
        if previous.message_type!="weekly_attendance":
            raise HTTPException(409,"ID WhatsApp já usado por outra mensagem")
        return WeeklyAttendanceResponse.model_validate(previous.result)
    try:
        return await _process_and_record_weekly_message(session, payload, chat_id)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _process_and_record_weekly_message(session, payload, chat_id) -> WeeklyAttendanceResponse:
    occurred_at = payload.received_at or datetime.now(timezone.utc)
    result, status = await process_live_weekly_snapshot(session, payload, occurred_at)
    message_id = await record_realtime_processed_message(
        session, chat_id=chat_id, text=payload.text, occurred_at=occurred_at,
        sender_name=payload.sender_name, sender_id=payload.sender_id,
        message_id=payload.message_id, source=payload.source, message_type="weekly_attendance",
        aggregate_key=f"weekly:{result.game_date.isoformat()}", status=status,
        result=result.model_dump(mode="json", exclude={"correction_text", "correction_notice"}),
    )
    if status == "applied":
        await link_message_to_entries(session, message_id=message_id, message_type="weekly_attendance",
                                      text=payload.text, occurred_at=d.aware(occurred_at).astimezone(d.TZ))
    from app.audit_history import record_list_history
    await record_list_history(session, message_id=message_id, message_type="weekly_attendance",
        chat_id=chat_id, aggregate_key=f"weekly:{result.game_date.isoformat()}", text=payload.text,
        occurred_at=occurred_at, status=status, sender_contact_name=payload.sender_contact_name,
        sender_name=payload.sender_name,
        semantic_text=(result.correction_text or payload.text) if status == "applied" else payload.text)
    await session.commit()
    return result


@app.post("/messages/record-sent")
async def record_sent_list_message(
    payload: RecordSentMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Record a successful WAHA list send without reapplying its contents."""
    if not payload.chat_id or not payload.message_id:
        raise HTTPException(status_code=422, detail="chat_id e message_id são obrigatórios")
    previous = await find_realtime_message(
        session, chat_id=payload.chat_id, message_id=payload.message_id
    )
    if previous is not None:
        return {"id": str(previous.id), "status": "duplicate"}
    reference_date = payload.reference_date
    parsed_monthly = None
    try:
        parsed_monthly = parse_monthly_subscribers_message(
            payload.text,
            received_at=datetime.combine(reference_date, time.min) if reference_date else payload.received_at,
        )
        if reference_date and (parsed_monthly.year, parsed_monthly.month) != (reference_date.year, reference_date.month):
            raise HTTPException(status_code=422, detail="mês ou ano da lista difere da referência do envio")
        message_type = "monthly_subscribers"
        aggregate_key = f"monthly:{parsed_monthly.year:04d}-{parsed_monthly.month:02d}"
        result = {"type": message_type, "month": parsed_monthly.month, "year": parsed_monthly.year}
    except ParseError:
        if (
            payload.list_type == "weekly_attendance"
            and reference_date is not None
            and reference_date.weekday() == 2
            and payload.text == empty_weekly_list_message(reference_date)
        ):
            game_date = reference_date
        else:
            try:
                parsed_weekly = parse_weekly_attendance_message(
                    payload.text, received_at=payload.received_at,
                )
            except ParseError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            game_date = parsed_weekly.game_date
        message_type = "weekly_attendance"
        aggregate_key = f"weekly:{game_date.isoformat()}"
        result = {"type": message_type, "game_date": game_date.isoformat()}

    occurred_at = payload.received_at or datetime.now(timezone.utc)
    identifier = await record_realtime_processed_message(
        session,
        chat_id=payload.chat_id,
        text=payload.text,
        occurred_at=occurred_at,
        sender_name=payload.sender_name or "Fred",
        sender_id=payload.sender_id,
        message_id=payload.message_id,
        source=payload.source or "waha-send",
        message_type=message_type,
        aggregate_key=aggregate_key,
        status="unchanged",
        result=result,
    )
    await link_message_to_entries(
        session,
        message_id=identifier,
        message_type=message_type,
        text=payload.text,
        occurred_at=occurred_at,
        parsed_monthly=parsed_monthly,
    )
    await session.commit()
    return {"id": str(identifier), "status": "recorded"}


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


from app.admin_api import router as management_router
app.include_router(management_router)

from app.player_profiles import router as player_profiles_router
app.include_router(player_profiles_router)

from app.auth import router as auth_router
app.include_router(auth_router)

from app.profile_photos import router as profile_photos_router
app.include_router(profile_photos_router)
