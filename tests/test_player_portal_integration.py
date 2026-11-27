"""Player self-service portal integration checks; opt in with FRED_TEST_DATABASE_URL."""
import asyncio
import os
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import management as d
from app import payment_notifications
from app.admin_api import router
from app.auth import current_user
from app.database import get_session
from app.models import (
    Charge, FredAccount, MonthlySubscriber, PaymentListNotification,
    Person, PersonAlias, ProcessedConversationMessage, WeeklyAttendance, WeeklyAttendanceEntry,
)

URL = os.getenv("FRED_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")


def test_player_portal_self_service_is_scoped_and_queues_complete_updates(monkeypatch):
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime(2030, 11, 20, 20, tzinfo=timezone.utc)  # 17:00 in Brasilia
        monkeypatch.setattr(d, "now", lambda: now)
        monkeypatch.setenv("FRED_PAYMENT_WEBHOOK_URL", "http://n8n.test/webhook/fred-payment-list")
        monkeypatch.setenv("FRED_PAYMENT_WEBHOOK_TOKEN", "test-token")
        monkeypatch.setattr(payment_notifications, "SessionLocal", factory)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE people, fred_accounts, monthly_subscribers, weekly_attendances, charges, "
                "audit_events, entity_revisions, processed_conversation_messages, payment_list_notifications "
                "RESTART IDENTITY CASCADE"
            ))

        owner_user = {"uid": "b" * 64, "username": "player", "name": "Jogadora", "email": "", "is_admin": False}
        rival_user = {"uid": "c" * 64, "username": "rival", "name": "Rival", "email": "", "is_admin": False}
        identity = owner_user
        game_date = date(2030, 11, 20)
        assert game_date.weekday() == 2
        month_date = date(2030, 11, 1)
        async with factory.begin() as session:
            owner = Person(name="Jogadora", normalized_name="jogadora", active=True)
            rival = Person(name="Rival", normalized_name="rival", active=True)
            rival_guest = Person(name="Convidado do Rival", normalized_name="convidado do rival", active=True)
            legacy_alias = PersonAlias(alias="Nome Antigo", alias_normalized="nome antigo",
                                       canonical_name=rival_guest.name,
                                       canonical_normalized=rival_guest.normalized_name)
            game = WeeklyAttendance(
                game_date=game_date, capacity=4,
                cutoff_at=datetime.combine(game_date, time(16), d.TZ),
                starts_at=datetime.combine(game_date, time(19, 30), d.TZ),
            )
            session.add_all([owner, rival, rival_guest, legacy_alias, game])
            await session.flush()
            source_message = ProcessedConversationMessage(
                fingerprint="weekly-main", chat_id="123@g.us", provider_message_id="weekly-main",
                message_type="weekly_attendance", aggregate_key=f"weekly:{game_date}", source="whatsapp",
                source_ordinal=1, occurred_at=now - timedelta(days=1), sender_name="Gestor",
                raw_text=f"LISTA VÔLEI FREDERICO {game_date:%d/%m/%Y}\n1. Jogadora",
                status="applied", analyzer="rules", confidence=1, analysis={}, result={},
            )
            session.add_all([
                FredAccount(uid=owner_user["uid"], username="player", name="Jogadora", email="", is_admin=False, person_id=owner.id),
                FredAccount(uid=rival_user["uid"], username="rival", name="Rival", email="", is_admin=False, person_id=rival.id),
                MonthlySubscriber(person_id=owner.id, name=owner.name, normalized_name=owner.normalized_name,
                                  month=11, year=2030, position=1, has_paid=True),
                Charge(person_id=owner.id, type="monthly", reference_date=month_date,
                       amount_cents=1250, status="paid", paid_at=now),
                source_message,
                ProcessedConversationMessage(
                    fingerprint="weekly-other-date", chat_id="123@g.us", provider_message_id="weekly-other-date",
                    message_type="weekly_attendance", aggregate_key="weekly:2030-11-27", source="whatsapp",
                    source_ordinal=1, occurred_at=now, sender_name="Gestor",
                    raw_text="LISTA VÔLEI FREDERICO 27/11/2030\n1. Outro", status="applied",
                    analyzer="rules", confidence=1, analysis={}, result={},
                ),
                ProcessedConversationMessage(
                    fingerprint="weekly-outbound", chat_id="123@g.us", provider_message_id="weekly-outbound",
                    message_type="weekly_attendance", aggregate_key=f"weekly:{game_date}", source="fred-payment-list",
                    source_ordinal=2, occurred_at=now, sender_name="Gestor",
                    raw_text=f"LISTA VÔLEI FREDERICO {game_date:%d/%m/%Y}\n1. Corrigida",
                    status="unchanged", analyzer="rules", confidence=1, analysis={}, result={},
                ),
                ProcessedConversationMessage(
                    fingerprint="weekly-stale", chat_id="123@g.us", provider_message_id="weekly-stale",
                    message_type="weekly_attendance", aggregate_key=f"weekly:{game_date}", source="whatsapp",
                    source_ordinal=3, occurred_at=now, sender_name="Gestor",
                    raw_text=f"LISTA VÔLEI FREDERICO {game_date:%d/%m/%Y}\n1. Antiga",
                    status="stale", analyzer="rules", confidence=1, analysis={}, result={},
                ),
            ])
            await session.flush()
            session.add(WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=rival_guest.id,
                name="Nome Antigo", normalized_name=rival_guest.normalized_name,
                source_message_id=source_message.id,
                invited_by=rival.name, normalized_invited_by=rival.normalized_name,
                source_section="main", source_position=1, display_order=1,
                status="main", is_monthly_subscriber=False,
                owes_single_payment=False, joined_at=now - timedelta(hours=1),
            ))

        app = FastAPI()
        app.include_router(router)

        async def actor():
            return identity

        async def session_dependency():
            async with factory() as session:
                yield session

        app.dependency_overrides.update({current_user: actor, get_session: session_dependency})

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def request(method, path, **kwargs):
                return await client.request(method, path, **kwargs)

            all_games = await request("GET", "/api/me/games")
            assert all_games.status_code == 200
            assert [item["id"] for item in all_games.json()["items"]] == [str(game.id)]
            assert all_games.json()["items"][0]["can_join"] is True

            join = await request("POST", f"/api/me/games/{game.id}/join")
            assert join.status_code == 200
            async with factory() as session:
                weekly_events = (await session.scalars(select(PaymentListNotification).where(
                    PaymentListNotification.aggregate_key == f"weekly:{game_date}",
                ))).all()
                assert len(weekly_events) == 1
            assert (await request("POST", f"/api/me/games/{game.id}/join")).status_code == 200
            async with factory() as session:
                assert await session.scalar(select(PaymentListNotification.id).where(
                    PaymentListNotification.aggregate_key == f"weekly:{game_date}",
                ).order_by(PaymentListNotification.id.desc()).offset(1).limit(1)) is None

            before_rival_delete = await request("GET", f"/api/me/games/{game.id}")
            rival_entry = next(entry for entry in before_rival_delete.json()["entries"]
                               if entry["name"] == "Nome Antigo")
            assert rival_entry["can_remove"] is False
            assert rival_entry["has_source"] is True
            assert rival_entry["source_message_id"] == str(source_message.id)
            assert rival_entry["history_names"] == ["Nome Antigo", "Convidado do Rival"]
            denied = await request("DELETE", f"/api/me/games/{game.id}/guests/{rival_entry['id']}")
            assert denied.status_code == 404

            add_guest = await request("POST", f"/api/me/games/{game.id}/guests", json={"name": "Convidada Nova"})
            assert add_guest.status_code == 200, add_guest.text
            assert (await request("POST", f"/api/me/games/{game.id}/guests", json={"name": "Convidada Nova"})).status_code == 200
            detail = await request("GET", f"/api/me/games/{game.id}")
            assert detail.status_code == 200
            guest = next(entry for entry in detail.json()["entries"] if entry["name"] == "Convidada Nova")
            assert guest["can_remove"] is True
            assert detail.json()["can_add_guest"] is True

            async with factory() as session:
                event = (await session.scalars(select(PaymentListNotification).where(
                    PaymentListNotification.aggregate_key == f"weekly:{game_date}",
                ).order_by(PaymentListNotification.id.desc()))).first()
                payload = await payment_notifications._webhook_payload(session, event)
                assert payload["list_type"] == "weekly_attendance"
                assert payload["text"].count("Convidada Nova") == 1
                assert "Jogadora" in payload["text"]
                count_after_guest = await session.scalar(select(func.count(PaymentListNotification.id)).where(
                    PaymentListNotification.aggregate_key == f"weekly:{game_date}",
                ))
                assert count_after_guest == 2

            mine = await request("GET", "/api/me")
            guest_charge = next(item for item in mine.json()["charges"] if item["name"] == "Convidada Nova")
            assert guest_charge["debtor_person_id"] == str(owner.id)
            assert guest_charge["status"] == "pending"

            history = await request("GET", f"/api/me/games/{game.id}/history")
            assert history.status_code == 200
            assert history.headers["cache-control"] == "no-store"
            assert [item["text"].splitlines()[-1] for item in history.json()["items"]] == [
                "1. Jogadora", "1. Corrigida", "1. Antiga",
            ]
            assert "chat_id" not in history.json()["items"][0]
            assert "sender_id" not in history.json()["items"][0]

            monthly = await request("GET", "/api/me/monthly?month=11&year=2030")
            assert monthly.status_code == 200
            assert monthly.json()["own_subscription"]["position"] == 1
            assert monthly.json()["can_leave"] is True
            assert (await request("GET", "/api/me/monthly?month=10&year=2030")).json()["can_join"] is False
            assert (await request("POST", "/api/me/monthly?month=10&year=2030")).status_code == 409

            removed = await request("DELETE", "/api/me/monthly?month=11&year=2030")
            assert removed.status_code == 200
            assert (await request("DELETE", "/api/me/monthly?month=11&year=2030")).status_code == 200
            async with factory() as session:
                monthly_charge = await session.scalar(select(Charge).where(
                    Charge.person_id == owner.id, Charge.type == "monthly", Charge.reference_date == month_date,
                ))
                assert monthly_charge.status == "paid"
                assert len((await session.scalars(select(PaymentListNotification).where(
                    PaymentListNotification.aggregate_key == "monthly:2030-11",
                ))).all()) == 1
                assert len((await session.scalars(select(PaymentListNotification).where(
                    PaymentListNotification.aggregate_key == f"weekly:{game_date}",
                ))).all()) == 3  # own join, guest add, changed weekly billing after subscription removal

            assert (await request("POST", "/api/me/monthly?month=11&year=2030")).status_code == 200
            assert (await request("POST", "/api/me/monthly?month=11&year=2030")).status_code == 200
            async with factory() as session:
                assert len((await session.scalars(select(PaymentListNotification).where(
                    PaymentListNotification.aggregate_key == "monthly:2030-11",
                ))).all()) == 2
                monthly_charge = await session.scalar(select(Charge).where(
                    Charge.person_id == owner.id, Charge.type == "monthly", Charge.reference_date == month_date,
                ))
                assert monthly_charge.status == "paid"
                current_subscriber = await session.scalar(select(MonthlySubscriber).where(
                    MonthlySubscriber.person_id == owner.id, MonthlySubscriber.month == 11,
                    MonthlySubscriber.year == 2030, MonthlySubscriber.deleted_at.is_(None),
                ))
                assert current_subscriber.position == 1

            # Only the owner who supplied the inviter identity can remove this guest.
            detail = await request("GET", f"/api/me/games/{game.id}")
            guest = next(entry for entry in detail.json()["entries"] if entry["name"] == "Convidada Nova")
            deleted = await request("DELETE", f"/api/me/games/{game.id}/guests/{guest['id']}")
            assert deleted.status_code == 200
            assert (await request("DELETE", f"/api/me/games/{game.id}/guests/{guest['id']}")).status_code == 404
            async with factory() as session:
                events = (await session.scalars(select(PaymentListNotification).where(
                    PaymentListNotification.aggregate_key == f"weekly:{game_date}",
                ))).all()
                assert len(events) == 5

            add_last_guest = await request("POST", f"/api/me/games/{game.id}/guests", json={"name": "Convidada Final"})
            assert add_last_guest.status_code == 200
            now = datetime.combine(game_date, time(20), d.TZ).astimezone(timezone.utc)
            closed_detail = await request("GET", f"/api/me/games/{game.id}")
            assert closed_detail.status_code == 200
            assert closed_detail.json()["can_join"] is False
            assert closed_detail.json()["can_leave"] is False
            assert closed_detail.json()["can_add_guest"] is False
            assert all(entry["can_remove"] is False for entry in closed_detail.json()["entries"])
            assert (await request("POST", f"/api/me/games/{game.id}/join")).status_code == 409
            assert (await request("DELETE", f"/api/me/games/{game.id}/join")).status_code == 409
            assert (await request("POST", f"/api/me/games/{game.id}/guests", json={"name": "Atrasado"})).status_code == 409
            final_guest = next(entry for entry in closed_detail.json()["entries"]
                               if entry["name"] == "Convidada Final")
            assert (await request("DELETE", f"/api/me/games/{game.id}/guests/{final_guest['id']}")).status_code == 409

        await engine.dispose()

    asyncio.run(scenario())
