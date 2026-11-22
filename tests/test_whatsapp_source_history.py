"""WhatsApp source preservation and history endpoints; isolated PostgreSQL only."""
import asyncio
from datetime import date, datetime, timezone
import os

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admin_api import router
from app.auth import current_user
from app.database import get_session
from app.main import process_monthly_message, process_weekly_message, record_sent_list_message
from app.models import (
    AuditEvent,
    MonthlySubscriber,
    ProcessedConversationMessage,
    WeeklyAttendance,
    WeeklyAttendanceEntry,
)
from app.schemas import ProcessMessageRequest, RecordSentMessageRequest

URL = os.getenv("FRED_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")


def test_realtime_messages_keep_full_text_and_provider_identity_idempotently(monkeypatch):
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        from app import management as d
        monkeypatch.setattr(d, "now", lambda: datetime(2026, 11, 18, 15, tzinfo=d.TZ))
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", "120363000000000000@g.us")
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE processed_conversation_messages,people,monthly_subscribers,weekly_attendances,weekly_attendance_entries,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        async with factory() as session:
            monthly_text = "LISTA DE ASSINANTES DO MÊS DE NOVEMBRO\n1. pyu ✅\n2. fulano"
            monthly = ProcessMessageRequest(
                text=monthly_text,
                received_at=datetime(2026, 11, 1, 15, tzinfo=timezone.utc),
                source="waha",
                chat_id="120363000000000000@g.us",
                message_id="false_120363000000000000@g.us_0123456789abcdef0123_12345@lid",
                sender_id="12345@lid",
                sender_name="Fulano",
            )
            await process_monthly_message(monthly, session)
            monthly_audit = await session.scalar(select(AuditEvent).where(
                AuditEvent.action == "list_change", AuditEvent.entity_id == "monthly:2026-11"))
            assert monthly_audit is not None
            assert monthly_audit.after["previous_message_id"] is None
            assert {change["kind"] for change in monthly_audit.after["changes"]} == {"monthly_paid"}
            assert monthly_audit.actor_name == "Fulano"
            stored = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == monthly.message_id
            ))
            assert stored is not None and stored.raw_text == monthly_text
            assert stored.sender_id == monthly.sender_id and stored.chat_id == monthly.chat_id
            entry = await session.scalar(select(MonthlySubscriber).where(MonthlySubscriber.position == 2))
            assert entry is not None and entry.source_message_id == stored.id
            await process_monthly_message(monthly, session)
            count = await session.scalar(select(ProcessedConversationMessage.id).where(
                ProcessedConversationMessage.provider_message_id == monthly.message_id
            ))
            assert count == stored.id
            monthly_count = await session.scalar(select(func.count(ProcessedConversationMessage.id)).where(
                ProcessedConversationMessage.message_type == "monthly_subscribers"
            ))
            assert monthly_count == 1

            sent = RecordSentMessageRequest(
                text=monthly_text,
                received_at=datetime(2026, 11, 1, 15, 1, tzinfo=timezone.utc),
                source="waha-send",
                chat_id=monthly.chat_id,
                message_id="true_120363000000000000@g.us_9876543210abcdef0123_12345@lid",
                sender_name="Fred",
            )
            await record_sent_list_message(sent, session)
            sent_row = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == sent.message_id
            ))
            entry = await session.scalar(select(MonthlySubscriber).where(MonthlySubscriber.position == 2))
            assert sent_row is not None and sent_row.raw_text == monthly_text
            assert entry is not None and entry.source_message_id == sent_row.id
            await record_sent_list_message(sent, session)
            assert await session.scalar(select(func.count(ProcessedConversationMessage.id)).where(
                ProcessedConversationMessage.message_type == "monthly_subscribers"
            )) == 2

            later_text = monthly_text + "\n3. newcomer ✅"
            later = monthly.model_copy(update={
                "text": later_text,
                "message_id": "false_120363000000000000@g.us_later_12345@lid",
                "received_at": datetime(2026, 11, 1, 15, 2, tzinfo=timezone.utc),
                "sender_name": "newcomer",
                "sender_contact_name": "Unregistered contact",
            })
            await process_monthly_message(later, session)
            later_row = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == later.message_id))
            later_audits = (await session.scalars(select(AuditEvent).where(
                AuditEvent.action == "list_change", AuditEvent.entity_id == "monthly:2026-11"))).all()
            later_audit = next((event for event in later_audits
                                if event.after.get("message_id") == str(later_row.id)), None)
            assert later_audit is not None
            assert later_audit.after["previous_message_id"] == str(sent_row.id)
            assert {change["kind"] for change in later_audit.after["changes"]} == {
                "subscription_added", "monthly_paid"
            }
            assert later_audit.actor_name == "Unregistered contact"
            assert any(person.get("is_actor") for change in later_audit.after["changes"]
                       for person in change["people"] if person["name"] == "newcomer")

            historical_send = sent.model_copy(update={
                "message_id": "true_120363000000000000@g.us_historical_12345@lid",
                "received_at": datetime(2027, 1, 1, 15, tzinfo=timezone.utc),
                "reference_date": date(2026, 11, 1),
            })
            await record_sent_list_message(historical_send, session)
            historical_row = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == historical_send.message_id
            ))
            assert historical_row.aggregate_key == "monthly:2026-11"
            assert historical_row.raw_text == monthly_text
            assert historical_row.occurred_at == historical_send.received_at
            await session.refresh(entry)
            assert entry.source_message_id == historical_row.id

            weekly_text = "LISTA VOLEI FREDERICO 18/11/2026\n1. pyu\n2. fulano"
            weekly = ProcessMessageRequest(
                text=weekly_text,
                received_at=datetime(2026, 11, 11, 15, tzinfo=timezone.utc),
                source="waha",
                chat_id=monthly.chat_id,
                message_id="false_120363000000000000@g.us_abcdef0123456789abcd_12345@lid",
                sender_id=monthly.sender_id,
                sender_name="Fulano",
            )
            await process_weekly_message(weekly, session)
            weekly_audit = await session.scalar(select(AuditEvent).where(
                AuditEvent.action == "list_change", AuditEvent.entity_id == "weekly:2026-11-18"))
            assert weekly_audit is not None
            assert weekly_audit.after["message_id"]
            assert weekly_audit.after["previous_message_id"] is None
            assert weekly_audit.after["changes"] == []
            stored_weekly = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == weekly.message_id
            ))
            guest_text = weekly_text + "\n\nConvidados\n1. Guest ✅"
            guest_message = weekly.model_copy(update={
                "text": guest_text,
                "message_id": "false_120363000000000000@g.us_guest_12345@lid",
                "received_at": datetime(2026, 11, 11, 15, 1, tzinfo=timezone.utc),
            })
            await process_weekly_message(guest_message, session)
            guest_row = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == guest_message.message_id))
            guest_audits = (await session.scalars(select(AuditEvent).where(
                AuditEvent.action == "list_change", AuditEvent.entity_id == "weekly:2026-11-18"))).all()
            guest_audit = next((event for event in guest_audits
                                if event.after.get("message_id") == str(guest_row.id)), None)
            assert guest_audit is not None
            assert guest_audit.after["previous_message_id"] == str(stored_weekly.id)
            assert {change["kind"] for change in guest_audit.after["changes"]} == {
                "guest_added", "guest_paid"
            }
            newcomer_text = weekly_text + "\n3. Outsider ✅\n\nConvidados\n1. Guest ✅"
            newcomer_message = weekly.model_copy(update={
                "text": newcomer_text,
                "message_id": "false_120363000000000000@g.us_moved_12345@lid",
                "received_at": datetime(2026, 11, 11, 15, 2, tzinfo=timezone.utc),
                "sender_name": "Outsider",
                "sender_contact_name": "fulano",
            })
            moved = await process_weekly_message(newcomer_message, session)
            assert moved.correction_text is not None
            newcomer_row = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == newcomer_message.message_id))
            newcomer_audit = next(event for event in (await session.scalars(select(AuditEvent).where(
                AuditEvent.action == "list_change", AuditEvent.entity_id == "weekly:2026-11-18"))).all()
                if event.after.get("message_id") == str(newcomer_row.id))
            assert {change["kind"] for change in newcomer_audit.after["changes"]} == {
                "guest_added", "guest_paid"
            }
            assert newcomer_audit.after["message_diff"]["after_text"] == newcomer_text
            assert newcomer_audit.after["message_diff"]["effective_text"] == moved.correction_text
            assert stored_weekly is not None and stored_weekly.raw_text == weekly_text
            entry = await session.scalar(select(WeeklyAttendanceEntry).where(
                WeeklyAttendanceEntry.name == "fulano",
                WeeklyAttendanceEntry.deleted_at.is_(None),
            ))
            assert entry is not None and entry.source_message_id == newcomer_row.id
        await engine.dispose()

    asyncio.run(scenario())


def test_manager_can_read_list_history_and_each_entry_source_only():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE processed_conversation_messages,people,monthly_subscribers,weekly_attendances,weekly_attendance_entries,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        admin = {"uid": "a" * 64, "username": "pyu", "name": "Gestor", "is_admin": True}
        player = {"uid": "b" * 64, "username": "player", "name": "Jogador", "is_admin": False}
        identity = admin
        app = FastAPI()
        app.include_router(router)

        async def actor():
            return identity

        async def session_dep():
            async with factory() as session:
                yield session

        app.dependency_overrides[current_user] = actor
        app.dependency_overrides[get_session] = session_dep
        async with factory() as session:
            from app import management as d
            person = await d.person_for_name(session, "Alice")
            monthly_message = ProcessedConversationMessage(
                fingerprint="monthly-source", chat_id="group@g.us", provider_message_id="monthly-id",
                sender_id="sender@lid", sender_name="Remetente", source="waha",
                raw_text="LISTA DE ASSINANTES DO MÊS DE NOVEMBRO\n1. Alice",
                source_ordinal=0, occurred_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                message_type="monthly_subscribers", aggregate_key="monthly:2026-11", status="applied",
                analyzer="rules", confidence=1, analysis={}, result={"type": "monthly_subscribers"},
            )
            session.add(monthly_message)
            await session.flush()
            monthly = await d.monthly_upsert(session, person, 11, 2026, position=1)
            monthly.source_message_id = monthly_message.id
            game = WeeklyAttendance(game_date=date(2026, 11, 18), capacity=24,
                cutoff_at=datetime(2026, 11, 18, 16, tzinfo=d.TZ),
                starts_at=datetime(2026, 11, 18, 19, 30, tzinfo=d.TZ))
            session.add(game)
            await session.flush()
            weekly_message = ProcessedConversationMessage(
                fingerprint="weekly-source", chat_id="group@g.us", provider_message_id="weekly-id",
                sender_id="sender@lid", sender_name="Remetente", source="waha",
                raw_text="LISTA VOLEI FREDERICO 18/11/2026\n1. Alice",
                source_ordinal=0, occurred_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
                message_type="weekly_attendance", aggregate_key="weekly:2026-11-18", status="applied",
                analyzer="rules", confidence=1, analysis={}, result={"type": "weekly_attendance"},
            )
            session.add(weekly_message)
            await session.flush()
            weekly = await d.add_entry(session, game, person)
            weekly.source_message_id = weekly_message.id
            await session.commit()
            monthly_id, weekly_id, game_id = str(monthly.id), str(weekly.id), str(game.id)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            monthly_history = await client.get("/api/source-history/monthly?month=11&year=2026")
            weekly_history = await client.get("/api/source-history/weekly?game_date=2026-11-18")
            assert monthly_history.status_code == weekly_history.status_code == 200
            assert monthly_history.json()["items"][0]["text"].endswith("1. Alice")
            assert weekly_history.json()["items"][0]["text"].endswith("1. Alice")
            assert (await client.get(f"/api/monthly/{monthly_id}/source")).json()["message"]["id"]
            assert (await client.get(f"/api/games/{game_id}/entries/{weekly_id}/source")).json()["message"]["id"]
            identity = player
            assert (await client.get("/api/source-history/monthly?month=11&year=2026")).status_code == 403
        await engine.dispose()

    asyncio.run(scenario())
