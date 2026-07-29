from datetime import datetime, timezone
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_conversation_import_max_bytes
from app.conversation_ai import ConversationAIError
from app.conversation_import import (
    process_conversation_import,
    record_realtime_processed_message,
)
from app.database import get_session
from app.ollama_service import OllamaServiceError
from app.parser import ParseError, parse_monthly_subscribers_message
from app.schemas import (
    ConversationImportResponse,
    ProcessMessageRequest,
    ProcessMessageResponse,
    PromoteDueResponse,
    WeeklyAttendanceResponse,
)
from app.whatsapp_export import WhatsAppExportError
from app.services import (
    process_monthly_subscribers_message,
    process_weekly_attendance_message,
    promote_due_weekly_attendances,
)

app = FastAPI(title="Volei Frederico API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
