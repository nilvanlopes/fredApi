from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.parser import ParseError
from app.schemas import ProcessMessageRequest, ProcessMessageResponse
from app.services import process_monthly_subscribers_message

app = FastAPI(title="Volei Frederico API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/messages/process", response_model=ProcessMessageResponse)
async def process_message(
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

