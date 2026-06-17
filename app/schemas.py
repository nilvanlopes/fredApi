from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProcessMessageRequest(BaseModel):
    text: str = Field(min_length=1)
    received_at: datetime | None = None
    source: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    sender_id: str | None = None
    sender_name: str | None = None


class SubscriberChange(BaseModel):
    position: int
    name: str | None = None
    has_paid: bool | None = None


class ProcessMessageResponse(BaseModel):
    type: Literal["monthly_subscribers"]
    month: int
    year: int
    created: list[SubscriberChange]
    updated: list[SubscriberChange]
    deleted: list[SubscriberChange]
    unchanged: list[SubscriberChange]


class WeeklyAttendanceEntryResponse(BaseModel):
    section: Literal["main", "guests"]
    position: int
    display_order: int
    name: str
    invited_by: str | None = None
    status: Literal["main", "waiting"]
    is_monthly_subscriber: bool
    owes_single_payment: bool
    single_payment_amount_cents: int | None = None


class WeeklyAttendanceResponse(BaseModel):
    type: Literal["weekly_attendance"]
    game_date: date
    cutoff_at: datetime
    capacity: int
    entries: list[WeeklyAttendanceEntryResponse]


class PromotionResult(BaseModel):
    game_date: date
    promoted: list[WeeklyAttendanceEntryResponse]


class PromoteDueResponse(BaseModel):
    processed: list[PromotionResult]
