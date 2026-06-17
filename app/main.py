from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.parser import ParseError, parse_monthly_subscribers_message
from app.schemas import (
    ProcessMessageRequest,
    ProcessMessageResponse,
    PromoteDueResponse,
    WeeklyAttendanceResponse,
)
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
    "/messages/process",
    response_model=ProcessMessageResponse | WeeklyAttendanceResponse,
)
async def process_message(
    payload: ProcessMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> ProcessMessageResponse | WeeklyAttendanceResponse:
    try:
        parse_monthly_subscribers_message(payload.text, received_at=payload.received_at)
        return await process_monthly_subscribers_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
        )
    except ParseError as exc:
        monthly_error = exc

    try:
        return await process_weekly_attendance_message(
            session,
            text=payload.text,
            received_at=payload.received_at,
        )
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
