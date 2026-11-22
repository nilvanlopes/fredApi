import asyncio
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import payment_notifications as notifications
import app.main as main
from app.admin_api import router
from app.auth import current_user
from app.database import get_session
from app import management
from app.message_templates import MONTH_NAMES, render_monthly_subscribers_message
from app.models import (
    Charge,
    MonthlySubscriber,
    PaymentListNotification,
    Person,
    ProcessedConversationMessage,
    WeeklyAttendance,
    WeeklyAttendanceEntry,
)
from app.schemas import ProcessMessageRequest, RecordSentMessageRequest


def test_rewrite_preserves_crlf_blank_lines_and_whatsapp_annotations():
    original = "Título\r\n\r\n2) Ana (conv. Bia)  <Mensagem editada>\r\n - Bia✅\r\n3. ✅Caio"
    assert notifications._rewrite_lines(original, {2: True, 3: False, 4: False}) == (
        "Título\r\n\r\n2) Ana (conv. Bia) ✅  <Mensagem editada>\r\n - Bia\r\n3. Caio"
    )


def test_monthly_payment_titles_drop_year_and_disambiguate_month():
    october = date(2025, 10, 1)
    assert notifications._monthly_title_without_year(
        "*LISTA DE ASSINANTES DO MÊS DE OUTUBRO DE 2025*", 10, october,
    ) == "*LISTA DE ASSINANTES DO MÊS DE OUTUBRO*"
    assert notifications._monthly_title_without_year(
        "Lista pagamento mensal Frederico", 11, october,
    ) == "LISTA DE ASSINANTES DO MÊS DE OUTUBRO"
    assert render_monthly_subscribers_message(october, [(SimpleNamespace(position=1, name="Ana"), True)]) == (
        "LISTA DE ASSINANTES DO MÊS DE OUTUBRO\n1. Ana ✅"
    )


def test_weekly_title_helper_removes_year_and_empty_list_uses_day_month():
    game_date = date(2026, 11, 18)
    assert notifications._weekly_title_without_year(
        "*LISTA VÔLEI FREDERICO 18/11/2026*", game_date,
    ) == "*LISTA VÔLEI FREDERICO 18/11*"
    assert notifications._weekly_title_without_year("Vôlei Frederico", game_date) == (
        "LISTA VÔLEI FREDERICO 18/11"
    )
    assert notifications.empty_weekly_list_message(game_date) == (
        "LISTA VÔLEI FREDERICO 18/11\nLista sem participantes."
    )


def test_source_position_compaction_preserves_source_order():
    async def scenario():
        later = SimpleNamespace(source_section="main", source_position=3, display_order=1)
        earlier = SimpleNamespace(source_section="main", source_position=2, display_order=2)
        session = SimpleNamespace(flush=AsyncMock())

        changed = await management.compact_source_positions(session, [later, earlier])

        assert changed
        assert earlier.source_position == 1
        assert later.source_position == 2
        assert session.flush.await_count == 2

    asyncio.run(scenario())


def test_weekly_payment_fallback_omits_year(monkeypatch):
    async def scenario():
        game_date = date(2026, 11, 18)
        person_id = uuid4()
        game = SimpleNamespace(id=uuid4())
        entry = SimpleNamespace(
            person_id=person_id, name="Ana", status="main", invited_by=None,
            prebuilt_team_number=None,
        )
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=game),
            execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(person_id, "paid")])),
        )
        monkeypatch.setattr(notifications, "active_entries", AsyncMock(return_value=[entry]))

        message = await notifications._weekly_message(
            session, game_date, person_id, True, None,
        )

        assert message == "LISTA VÔLEI FREDERICO 18/11\n1. Ana ✅"

    asyncio.run(scenario())


def test_weekly_membership_rewrite_preserves_paid_marker_after_compaction(monkeypatch):
    async def scenario():
        game_date = date(2026, 11, 25)
        entry = SimpleNamespace(
            person_id=uuid4(), name="Bia", normalized_name="bia", invited_by=None,
            prebuilt_team_number=None, source_section="main", source_position=1,
        )
        source = SimpleNamespace(
            raw_text=f"LISTA VÔLEI FREDERICO {game_date:%d/%m}\n2. Bia ✅",
            occurred_at=datetime.combine(game_date, time(14), notifications.LOCAL_TZ),
        )
        monkeypatch.setattr(
            notifications, "resolve_normalized_name", AsyncMock(side_effect=lambda session, name: name),
        )

        message = await notifications._render_updated_weekly(
            SimpleNamespace(), game_date, [entry], {}, source,
        )

        assert message == f"LISTA VÔLEI FREDERICO {game_date:%d/%m}\n1. Bia ✅"

    asyncio.run(scenario())


def test_only_a_confirmed_empty_weekly_send_is_recorded(monkeypatch):
    async def scenario():
        game_date = date(2026, 11, 18)
        text = notifications.empty_weekly_list_message(game_date)
        session = SimpleNamespace(commit=AsyncMock())
        record = AsyncMock(return_value=uuid4())
        monkeypatch.setattr(main, "find_realtime_message", AsyncMock(return_value=None))
        monkeypatch.setattr(main, "record_realtime_processed_message", record)
        monkeypatch.setattr(main, "link_message_to_entries", AsyncMock())
        fields = {"text": text, "chat_id": "123@g.us", "message_id": "sent-1"}
        payload = RecordSentMessageRequest(
            **fields, list_type="weekly_attendance", reference_date=game_date,
        )

        result = await main.record_sent_list_message(payload, session)
        assert result["status"] == "recorded"
        assert record.await_args.kwargs["aggregate_key"] == "weekly:2026-11-18"
        assert record.await_args.kwargs["status"] == "unchanged"
        assert record.await_args.kwargs["text"] == text
        session.commit.assert_awaited_once()

        thursday = game_date + timedelta(days=1)
        for changes in (
            {"list_type": None}, {"list_type": "monthly_subscribers"}, {"reference_date": None},
            {"reference_date": game_date - timedelta(days=7)},
            {"reference_date": thursday, "text": notifications.empty_weekly_list_message(thursday)},
            {"text": text + "\n"},
        ):
            with pytest.raises(HTTPException) as error:
                await main.record_sent_list_message(payload.model_copy(update=changes), session)
            assert error.value.status_code == 422

        with pytest.raises(HTTPException) as error:
            await main.process_weekly_message(ProcessMessageRequest(**fields), session)
        assert error.value.status_code == 422
        record.assert_awaited_once()

    asyncio.run(scenario())


TEST_DATABASE = os.getenv("FRED_TEST_DATABASE_URL")


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_panel_payment_changes_publish_ordered_lists_with_persistent_retries(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setenv("FRED_PAYMENT_WEBHOOK_URL", "http://n8n.test/webhook/fred-payment-list")
        monkeypatch.setenv("FRED_PAYMENT_WEBHOOK_TOKEN", "test-token")
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", "123@g.us")
        monkeypatch.setattr(notifications, "SessionLocal", factory)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE people, fred_accounts, monthly_subscribers, weekly_attendances, charges, "
                "audit_events, entity_revisions, processed_conversation_messages, payment_list_notifications "
                "RESTART IDENTITY CASCADE"
            ))

        today = datetime.now(notifications.LOCAL_TZ).date()
        month = today.replace(day=1)
        game_date = month - timedelta(days=1)
        game_date -= timedelta(days=(game_date.weekday() - 2) % 7)
        title = f"LISTA VÔLEI FREDERICO {game_date:%d/%m}"
        weekly_source_title = f"LISTA VÔLEI FREDERICO {game_date:%d/%m/%Y}"
        weekly_source = f"{weekly_source_title}\n1) Bia\n\nConvidados:\n- Ana (conv. Bia) 1️⃣"
        month_name = MONTH_NAMES[month.month - 1]
        monthly_title = f"LISTA DE ASSINANTES DO MÊS DE {month_name}"
        monthly_source = f"{monthly_title}\n\n1 - \u2060Ana\n2) Bia ✅\n3. Tiago✅\n4-"
        corrected_monthly_source = monthly_source.replace("Tiago✅", "Tiago Almeida✅")

        def source_message(aggregate, kind, content, group="123@g.us", source=None, age=0, status="applied"):
            return ProcessedConversationMessage(
                fingerprint=f"{aggregate}:{group}",
                chat_id=group,
                provider_message_id=aggregate,
                message_type=kind,
                aggregate_key=aggregate,
                source_ordinal=0,
                occurred_at=datetime.now(timezone.utc) - timedelta(seconds=age),
                raw_text=content,
                status=status,
                source=source,
                analyzer="rules",
                confidence=1,
                analysis={},
                result={},
            )

        async with factory.begin() as session:
            ana = Person(name="Ana", normalized_name="ana")
            bia = Person(name="Bia", normalized_name="bia")
            tiago = Person(name="Tiago Almeida", normalized_name="tiago almeida")
            game = WeeklyAttendance(game_date=game_date, capacity=24,
                                    cutoff_at=datetime.combine(game_date, time(16), notifications.LOCAL_TZ),
                                    starts_at=datetime.combine(game_date, time(19, 30), notifications.LOCAL_TZ))
            session.add_all([ana, bia, tiago, game])
            await session.flush()
            subscriber = MonthlySubscriber(name="Ana", normalized_name="ana", person_id=ana.id,
                                           month=month.month, year=month.year, position=1, has_paid=False)
            weekly_charge = Charge(person_id=ana.id, type="single", reference_date=game_date,
                                   status="pending", amount_cents=750)
            session.add_all([
                subscriber,
                MonthlySubscriber(name="Bia", normalized_name="bia", person_id=bia.id,
                                  month=month.month, year=month.year, position=2, has_paid=True),
                MonthlySubscriber(name="Tiago Almeida", normalized_name="tiago almeida", person_id=tiago.id,
                                  month=month.month, year=month.year, position=3, has_paid=True),
                Charge(person_id=ana.id, type="monthly", reference_date=month, status="pending", amount_cents=1250),
                weekly_charge,
                WeeklyAttendanceEntry(attendance_id=game.id, person_id=ana.id, name="Ana", normalized_name="ana",
                                      invited_by="Bia", normalized_invited_by="bia", prebuilt_team_number=1,
                                      source_section="guests", source_position=1, display_order=2, status="main"),
                WeeklyAttendanceEntry(attendance_id=game.id, person_id=bia.id, name="Bia", normalized_name="bia",
                                      source_section="main", source_position=1, display_order=1, status="main"),
                source_message(f"monthly:{month:%Y-%m}", "monthly_subscribers", monthly_source,
                               "fred-export-history", "whatsapp-export", age=1),
                source_message(f"monthly:{month:%Y-%m}", "monthly_subscribers",
                               f"{monthly_title} DE {month.year}\n1. Ana✅\n2. Bia✅\n3. Tiago Almeida✅",
                               source="waha-send", status="unchanged"),
                source_message(f"weekly:{game_date}", "weekly_attendance", weekly_source),
                source_message(f"weekly:{game_date}", "weekly_attendance", f"{weekly_source_title}\n1. Alguém", "999@g.us"),
            ])

        async def actor():
            return {"uid": "payment-test", "username": "tester", "name": "Admin", "email": "", "is_admin": True}

        async def session_dependency():
            async with factory() as session:
                yield session

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update({current_user: actor, get_session: session_dependency})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            monthly_path = f"/api/monthly/{subscriber.id}"
            weekly_path = f"/api/charges/{weekly_charge.id}"
            for path, body in [
                (weekly_path, {"status": "paid"}),
                (weekly_path, {"status": "paid"}),
                (weekly_path, {"status": "cancelled"}),
                (monthly_path, {"has_paid": True}),
                (monthly_path, {"has_paid": False}),
                (weekly_path, {"amount_cents": 800}),
            ]:
                response = await client.patch(path, json=body)
                assert response.status_code == 200, response.text

        async with factory() as session:
            items = (await session.scalars(select(PaymentListNotification).order_by(PaymentListNotification.id))).all()
            assert [item.payload["is_paid"] for item in items] == [True, False, True, False]

        calls = []

        def receive(request):
            payload = json.loads(request.content)
            calls.append(payload)
            if len(calls) == 1:
                return httpx.Response(200, json={"message": "workflow did not acknowledge send"})
            return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
            url = os.environ["FRED_PAYMENT_WEBHOOK_URL"]
            assert await notifications._deliver_next(client, url)
            assert await notifications._deliver_next(client, url)
            assert await notifications._deliver_next(client, url)
            assert not await notifications._deliver_next(client, url)
            assert [item["text"] for item in calls] == [
                f"{weekly_source.replace(weekly_source_title, title, 1)} ✅",
                corrected_monthly_source.replace("1 - \u2060Ana", "1 - \u2060Ana ✅"),
                corrected_monthly_source,
            ]
            assert [item["chat_id"] for item in calls] == ["123@g.us", None, None]

            async with factory.begin() as session:
                first = await session.get(PaymentListNotification, items[0].id)
                assert first.attempts == 1 and first.delivered_at is None
                first.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                guest = await session.scalar(select(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.person_id == ana.id))
                guest.prebuilt_team_number = 2

            assert await notifications._deliver_next(client, url)
            assert await notifications._deliver_next(client, url)
            assert not await notifications._deliver_next(client, url)
            assert calls[0]["event_id"] == calls[3]["event_id"]
            assert calls[3]["text"] == f"{title}\n1. Bia\n2. Ana (conv. Bia) 2️⃣ ✅"
            assert calls[4]["text"] == f"{title}\n1. Bia\n2. Ana (conv. Bia) 2️⃣"

        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_panel_list_edits_publish_complete_weekly_and_monthly_lists(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        url = "http://n8n.test/webhook/fred-payment-list"
        group = "123@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WEBHOOK_URL", url)
        monkeypatch.setenv("FRED_PAYMENT_WEBHOOK_TOKEN", "test-token")
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)
        monkeypatch.setattr(notifications, "SessionLocal", factory)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people, payment_list_notifications RESTART IDENTITY CASCADE"))
            await connection.execute(text(
                "TRUNCATE weekly_attendances, entity_revisions, processed_conversation_messages CASCADE"
            ))

        game_date = date(2025, 10, 22)
        month = date(2025, 11, 1)
        title = f"LISTA VÔLEI FREDERICO {game_date:%d/%m}"
        source_title = f"LISTA VÔLEI FREDERICO {game_date:%d/%m/%Y}"
        monthly_title = "LISTA DE ASSINANTES DO MÊS DE NOVEMBRO"
        game_time = datetime.combine(game_date, time(19, 30), notifications.LOCAL_TZ)
        async with factory.begin() as session:
            ana, bia, caio, duda = [Person(name=name, normalized_name=name.lower()) for name in (
                "Ana", "Bia", "Caio", "Duda",
            )]
            game = WeeklyAttendance(game_date=game_date, capacity=24,
                                    cutoff_at=game_time.replace(hour=16, minute=0), starts_at=game_time)
            source = ProcessedConversationMessage(
                fingerprint="manual-weekly-source", chat_id=group, provider_message_id="weekly-received",
                message_type="weekly_attendance", aggregate_key=f"weekly:{game_date}", source_ordinal=0,
                occurred_at=game_time - timedelta(days=1), status="applied", source="waha",
                raw_text=f"{source_title}\n2) Bia\n\nConvidados:\n7. Ana 1️⃣ ✅",
                analyzer="rules", confidence=1, analysis={}, result={},
            )
            session.add_all([ana, bia, caio, duda, game, source])
            await session.flush()
            main_entry = WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=bia.id, name=bia.name, normalized_name=bia.normalized_name,
                source_section="main", source_position=2, display_order=1, status="main",
            )
            guest_entry = WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=ana.id, name=ana.name, normalized_name=ana.normalized_name,
                source_section="guests", source_position=7, display_order=2, status="main", prebuilt_team_number=1,
            )
            session.add_all([main_entry, guest_entry, Charge(
                person_id=ana.id, type="single", reference_date=game_date, status="paid", amount_cents=750,
            )])

        async def actor():
            return {"uid": "list-edits", "username": "tester", "name": "Admin", "email": "", "is_admin": True}

        async def session_dependency():
            async with factory() as session:
                yield session

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update({current_user: actor, get_session: session_dependency})
        calls = []

        def receive(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})

        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as panel,
            httpx.AsyncClient(transport=httpx.MockTransport(receive)) as n8n,
        ):
            async def request(method, path, body=None, *, status=200):
                response = await panel.request(method, path, json=body)
                assert response.status_code == status, response.text
                return response.json()

            async def published(expected, reference=game_date, chat_id=group):
                assert await notifications._deliver_next(n8n, url)
                assert not await notifications._deliver_next(n8n, url)
                assert calls[-1]["text"] == expected
                assert calls[-1]["chat_id"] == chat_id
                assert calls[-1]["reference_date"] == str(reference)

            entries_path = f"/api/games/{game.id}/entries"
            guest_path = f"{entries_path}/{guest_entry.id}"
            await request("PATCH", guest_path, {"invited_by": "Bia", "prebuilt_team_number": 2})
            await published(f"{title}\n2. Bia\n\nConvidados\n7. Ana (conv. Bia) 2️⃣ ✅")
            await request("PATCH", guest_path, {"invited_by": " Bia ", "prebuilt_team_number": 2})
            await request("PATCH", f"{guest_path}/player", {"person_id": str(ana.id)})
            await request("PATCH", f"{guest_path}/player", {"person_id": str(bia.id)}, status=409)
            assert not await notifications._deliver_next(n8n, url)

            await request("PATCH", f"{guest_path}/player", {"person_id": str(caio.id)})
            await published(f"{title}\n2. Bia\n\nConvidados\n7. Caio (conv. Bia) 2️⃣ ✅")
            await request("POST", entries_path, {"person_id": str(duda.id)})
            await published(f"{title}\n2. Bia\n8. Duda\n\nConvidados\n7. Caio (conv. Bia) 2️⃣ ✅")
            await request("POST", entries_path, {"person_id": str(duda.id)})
            assert not await notifications._deliver_next(n8n, url)

            await request("DELETE", f"{entries_path}/{main_entry.id}")
            await published(f"{title}\n1. Duda\n\nConvidados\n1. Caio (conv. Bia) 2️⃣ ✅")
            async with factory() as session:
                duda_position = await session.scalar(select(WeeklyAttendanceEntry.source_position).where(
                    WeeklyAttendanceEntry.attendance_id == game.id,
                    WeeklyAttendanceEntry.person_id == duda.id,
                    WeeklyAttendanceEntry.deleted_at.is_(None),
                ))
            assert duda_position == 1
            await request("DELETE", guest_path)
            await published(f"{title}\n1. Duda")
            async with factory() as session:
                duda_id = await session.scalar(select(WeeklyAttendanceEntry.id).where(
                    WeeklyAttendanceEntry.attendance_id == game.id,
                    WeeklyAttendanceEntry.person_id == duda.id,
                ))
            await request("DELETE", f"{entries_path}/{duda_id}")
            await published(notifications.empty_weekly_list_message(game_date))

            await request("POST", "/api/monthly", {
                "person_id": str(bia.id), "month": month.month, "year": month.year,
                "position": 3, "has_paid": True,
            }, status=201)
            await published(f"{monthly_title}\n3. Bia ✅", month, None)
            async with factory() as session:
                monthly_id = await session.scalar(select(MonthlySubscriber.id).where(
                    MonthlySubscriber.person_id == bia.id,
                ))
            monthly_path = f"/api/monthly/{monthly_id}"
            await request("PATCH", monthly_path, {"position": 3, "has_paid": True})
            assert not await notifications._deliver_next(n8n, url)
            await request("PATCH", monthly_path, {"position": 6})
            await published(f"{monthly_title}\n6. Bia ✅", month, None)
            await request("DELETE", monthly_path)
            await published(f"{monthly_title}\n1.", month, None)
            await request("DELETE", monthly_path)
            assert not await notifications._deliver_next(n8n, url)

        await engine.dispose()

    asyncio.run(scenario())
