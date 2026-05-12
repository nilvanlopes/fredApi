from datetime import datetime

from pydantic import BaseModel, Field


class ProcessMessageRequest(BaseModel):
    text: str = Field(min_length=1)
    received_at: datetime | None = None


class SubscriberChange(BaseModel):
    position: int
    name: str | None = None
    has_paid: bool | None = None


class ProcessMessageResponse(BaseModel):
    type: str
    month: int
    year: int
    created: list[SubscriberChange]
    updated: list[SubscriberChange]
    deleted: list[SubscriberChange]
    unchanged: list[SubscriberChange]

