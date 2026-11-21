"""Player consolidation against the isolated PostgreSQL test database."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
import os

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import management as d
from app.admin_api import router
from app.aliases import create_alias, detach_alias_history
from app.auth import current_user
from app.database import get_session
from app.models import AuditEvent, Charge, EntityRevision, MonthlySubscriber, Person, PersonAlias, WeeklyAttendance, WeeklyAttendanceEntry

URL = os.getenv("FRED_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
ADMIN = {"uid": "a" * 64, "username": "gestor", "name": "Gestor", "email": "gestor@example.com", "is_admin": True}
PLAYER = {"uid": "b" * 64, "username": "jogador", "name": "Jogador", "email": "jogador@example.com", "is_admin": False}
GAME_DATE = date(2025, 1, 1)
PLAYED_AT = datetime.combine(GAME_DATE, time(19, 30), d.TZ)


@asynccontextmanager
async def merge_fixture():
    assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
    engine = create_async_engine(URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,person_aliases,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        app = FastAPI()
        app.include_router(router)
        identity = ADMIN.copy()

        async def actor():
            return identity

        async def sessions():
            async with factory() as session:
                yield session

        app.dependency_overrides[current_user] = actor
        app.dependency_overrides[get_session] = sessions
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield factory, client, identity
    finally:
        await engine.dispose()


def game_row(game_date=GAME_DATE):
    starts_at = datetime.combine(game_date, time(19, 30), d.TZ)
    return WeeklyAttendance(game_date=game_date, capacity=24, starts_at=starts_at, cutoff_at=starts_at.replace(hour=16, minute=0))


def entry_row(game, person, position=1, inviter=None):
    return WeeklyAttendanceEntry(attendance_id=game.id, person_id=person.id, name=person.name,
                                 normalized_name=person.normalized_name, source_section="main",
                                 source_position=position, display_order=position, status="main",
                                 invited_by=inviter.name if inviter else None,
                                 normalized_invited_by=inviter.normalized_name if inviter else None,
                                 joined_at=game.starts_at - timedelta(hours=1))


def monthly_row(person, position, *, deleted_at=None):
    return MonthlySubscriber(person_id=person.id, name=person.name, normalized_name=person.normalized_name,
                             month=GAME_DATE.month, year=GAME_DATE.year, position=position, deleted_at=deleted_at)


def test_merge_moves_existing_records_and_retains_the_old_import_names():
    async def scenario():
        async with merge_fixture() as (factory, client, identity):
            async with factory() as session:
                source = await d.person_for_name(session, "Gomes 👆🏾")
                target = await d.person_for_name(session, "Gomes")
                other = await d.person_for_name(session, "Outro jogador")
                await create_alias(session, alias="Gomão", canonical_name=source.name)
                account = await d.touch_account(session, PLAYER)
                account.person_id = source.id
                game = game_row()
                session.add(game)
                await session.flush()
                source_entry = entry_row(game, source)
                invited_entry = entry_row(game, other, position=2, inviter=source)
                subscription = monthly_row(source, 1)
                old_subscription = monthly_row(target, 2, deleted_at=PLAYED_AT)
                session.add_all([source_entry, invited_entry, subscription, old_subscription])
                paid = await d.set_charge(session, source.id, "monthly", GAME_DATE, status="paid", occurred_at=PLAYED_AT)
                history = await d.audit(session, entity_type="weekly", entity_id=game.id, action="join", person_id=source.id,
                                        user=ADMIN, occurred_at=PLAYED_AT, after={"original_name": source.name})
                source_revision = f"weekly:{source.id}:{GAME_DATE}"
                target_revision = f"weekly:{target.id}:{GAME_DATE}"
                session.add_all([EntityRevision(key=source_revision, occurred_at=PLAYED_AT),
                                 EntityRevision(key=target_revision, occurred_at=PLAYED_AT - timedelta(hours=1))])
                await session.commit()

            path = f"/api/people/{source.id}/merge"
            identity.update(PLAYER)
            response = await client.post(path, json={"target_id": str(target.id)})
            assert response.status_code == 403
            identity.update(ADMIN)
            response = await client.post(path, json={"target_id": str(source.id)})
            assert response.status_code == 422
            response = await client.post(path, json={"target_id": str(target.id)})
            assert response.status_code == 200 and response.json() == {"ok": True}

            people = (await client.get("/api/people")).json()["items"]
            assert {p["id"] for p in people} == {str(target.id), str(other.id)}
            assert set(next(p for p in people if p["id"] == str(target.id))["aliases"]) == {source.name, "Gomão"}
            assert (await client.post("/api/people", json={"name": source.name})).status_code == 409

            identity.update(PLAYER)
            mine = (await client.get("/api/me")).json()
            assert mine["person"]["id"] == str(target.id)
            assert mine["monthly"][0]["id"] == str(subscription.id)
            assert mine["games"][0]["own_entry"]["id"] == str(source_entry.id)
            assert mine["charges"][0]["id"] == str(paid.id)
            assert any(event["id"] == str(history.id) for event in mine["history"])

            async with factory() as session:
                assert await session.get(Person, source.id) is None
                for name in (source.name, "Gomão"):
                    assert (await d.person_for_name(session, name)).id == target.id
                assert (await session.get(WeeklyAttendanceEntry, invited_entry.id)).normalized_invited_by == target.normalized_name
                merged_charge = await session.get(Charge, paid.id)
                assert (merged_charge.person_id, merged_charge.status, merged_charge.paid_at) == (target.id, "paid", PLAYED_AT)
                assert await session.get(EntityRevision, source_revision) is None
                assert (await session.get(EntityRevision, target_revision)).occurred_at == PLAYED_AT
                event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "merge"))
                assert event.person_id == target.id and event.actor_uid == ADMIN["uid"]
                assert event.before["id"] == str(source.id) and event.after["moved"]["weekly"] == 1
                active = await d.monthly_upsert(session, await session.get(Person, target.id), GAME_DATE.month, GAME_DATE.year)
                assert active.id == subscription.id
                assert (await session.get(MonthlySubscriber, old_subscription.id)).deleted_at == PLAYED_AT
    asyncio.run(scenario())


def test_merge_recalculates_the_target_game_after_cutoff_using_the_moved_paid_subscription():
    async def scenario():
        async with merge_fixture() as (factory, client, _):
            async with factory() as session:
                source = await d.person_for_name(session, "Kell")
                target = await d.person_for_name(session, "Ana R.")
                waiting = await d.person_for_name(session, "Outro jogador")
                game = game_row()
                previous = game_row(date(2024, 12, 25))
                session.add_all([game, previous, monthly_row(source, 1)])
                await session.flush()
                entry = entry_row(game, target)
                waiting_entry = entry_row(game, waiting, position=2)
                waiting_entry.status = "waiting"
                previous_entry = entry_row(previous, target)
                entry.owes_single_payment = previous_entry.owes_single_payment = True
                session.add_all([entry, waiting_entry, previous_entry])
                await d.set_charge(session, source.id, "monthly", GAME_DATE, status="paid", occurred_at=PLAYED_AT)
                charge = await d.set_charge(session, target.id, "single", GAME_DATE)
                previous_charge = await d.set_charge(session, target.id, "single", previous.game_date)
                await session.commit()

            response = await client.post(f"/api/people/{source.id}/merge", json={"target_id": str(target.id)})
            assert response.status_code == 200
            async with factory() as session:
                updated = await session.get(WeeklyAttendanceEntry, entry.id)
                assert updated.is_monthly_subscriber and not updated.owes_single_payment
                assert updated.status == "main"
                assert (await session.get(Charge, charge.id)).status == "cancelled"
                assert (await session.get(WeeklyAttendanceEntry, waiting_entry.id)).status == "waiting"
                assert (await session.get(WeeklyAttendanceEntry, previous_entry.id)).owes_single_payment
                assert (await session.get(Charge, previous_charge.id)).status == "pending"
    asyncio.run(scenario())


@pytest.mark.parametrize("editing", [False, True])
def test_alias_save_associates_legacy_subscription_and_recalculates_the_game(editing):
    async def scenario():
        async with merge_fixture() as (factory, client, _):
            async with factory() as session:
                target = await d.person_for_name(session, "Ana R.")
                if editing:
                    original_alias, *_ = await create_alias(session, alias="Ana antiga", canonical_name=target.name)
                game = game_row()
                session.add(game)
                await session.flush()
                legacy = monthly_row(target, 1)
                legacy.person_id = None
                legacy.name = "Kell"
                legacy.normalized_name = "kell"
                legacy.has_paid = True
                entry = entry_row(game, target)
                entry.owes_single_payment = True
                session.add_all([legacy, entry])
                charge = await d.set_charge(session, target.id, "single", GAME_DATE)
                await session.commit()

            alias_path = f"/api/people/{target.id}/aliases"
            if editing:
                response = await client.patch(f"{alias_path}/id/{original_alias.id}", json={"alias": "Kell"})
            else:
                response = await client.post(alias_path, json={"alias": "Kell"})
            assert response.status_code == 200
            async with factory() as session:
                assert (await session.get(MonthlySubscriber, legacy.id)).person_id == target.id
                updated = await session.get(WeeklyAttendanceEntry, entry.id)
                assert updated.is_monthly_subscriber and not updated.owes_single_payment
                assert (await session.get(Charge, charge.id)).status == "cancelled"
    asyncio.run(scenario())


def test_removing_alias_detaches_legacy_rows_and_unambiguous_charges():
    async def scenario():
        async with merge_fixture() as (factory, _client, _identity):
            async with factory() as session:
                canonical = await d.person_for_name(session, "Thiago Sousa")
                await create_alias(session, alias="Tiago", canonical_name=canonical.name)
                game = game_row()
                session.add(game)
                await session.flush()
                weekly = entry_row(game, canonical)
                weekly.name = "Tiago"
                weekly.normalized_name = canonical.normalized_name
                subscription = monthly_row(canonical, 1)
                subscription.name = "Tiago"
                subscription.normalized_name = canonical.normalized_name
                session.add_all([weekly, subscription])
                monthly_charge = await d.set_charge(session, canonical.id, "monthly", date(GAME_DATE.year, GAME_DATE.month, 1), status="paid")
                single_charge = await d.set_charge(session, canonical.id, "single", GAME_DATE, status="pending")
                await session.flush()

                counts = await detach_alias_history(session, alias="Tiago", canonical=canonical)
                recovered = await session.scalar(select(Person).where(Person.normalized_name == "tiago"))
                assert recovered is not None and recovered.id != canonical.id
                assert weekly.person_id == recovered.id and weekly.name == "Tiago"
                assert subscription.person_id == recovered.id and subscription.name == "Tiago"
                assert counts["weekly"] == 1 and counts["monthly"] == 1
                assert monthly_charge.person_id == recovered.id
                assert single_charge.person_id == recovered.id and single_charge.status == "cancelled"
                assert weekly.is_monthly_subscriber and not weekly.owes_single_payment

    asyncio.run(scenario())


def test_removing_alias_recalculates_historical_coverage_after_a_subscription_moves():
    async def scenario():
        async with merge_fixture() as (factory, client, _):
            async with factory() as session:
                canonical = await d.person_for_name(session, "Thiago Sousa")
                alias, *_ = await create_alias(session, alias="Tiago", canonical_name=canonical.name)
                game = game_row()
                session.add(game)
                await session.flush()
                weekly = entry_row(game, canonical)
                subscription = monthly_row(canonical, 1)
                subscription.name = "Tiago"
                session.add_all([weekly, subscription])
                await d.set_charge(session, canonical.id, "monthly", GAME_DATE, status="paid")
                single_charge = await d.set_charge(session, canonical.id, "single", GAME_DATE)
                await d.recalculate(session, game, at=d.now())
                assert single_charge.status == "cancelled"
                await session.commit()

            response = await client.delete(f"/api/people/{canonical.id}/aliases/id/{alias.id}")
            assert response.status_code == 200
            async with factory() as session:
                entry = await session.get(WeeklyAttendanceEntry, weekly.id)
                assert entry.person_id == canonical.id and not entry.is_monthly_subscriber
                assert entry.status == "main" and entry.owes_single_payment
                assert (await session.get(Charge, single_charge.id)).status == "pending"
    asyncio.run(scenario())


def test_alias_list_supports_edit_remove_and_protects_display_name():
    async def scenario():
        async with merge_fixture() as (factory, client, _):
            async with factory() as session:
                person=await d.person_for_name(session,"Gomes")
                alias,*_=await create_alias(session,alias="Gomão",canonical_name=person.name)
                await session.commit()
                person_id,alias_id=person.id,alias.id

            listed=(await client.get("/api/people")).json()["items"]
            details=next(row for row in listed if row["id"]==str(person_id))["alias_details"]
            assert details==[{"id":str(alias_id),"alias":"Gomão","protected":False}]

            changed=await client.patch(f"/api/people/{person_id}/aliases/id/{alias_id}",json={"alias":"Gomes Junior"})
            assert changed.status_code==200
            async with factory() as session:
                assert (await d.person_for_name(session,"Gomes Junior")).id==person_id

            removed=await client.delete(f"/api/people/{person_id}/aliases/id/{alias_id}")
            assert removed.status_code==200
            renamed=await client.patch(f"/api/people/{person_id}",json={"name":"Gomes Prado"})
            assert renamed.status_code==200
            listed=(await client.get("/api/people")).json()["items"]
            protected=next(row for row in listed if row["id"]==str(person_id))["alias_details"]
            protected_alias=next(row for row in protected if row["alias"]=="Gomes Prado")
            assert protected_alias["protected"] is True
            protected_path=f"/api/people/{person_id}/aliases/id/{protected_alias['id']}"
            assert (await client.patch(protected_path,json={"alias":"Outro nome"})).status_code==409
            assert (await client.delete(protected_path)).status_code==409
            async with factory() as session:
                assert (await d.person_for_name(session,"Gomes Prado")).id==person_id
                assert await session.scalar(select(PersonAlias).where(PersonAlias.id==protected_alias["id"])) is not None
    asyncio.run(scenario())


@pytest.mark.parametrize(("conflict", "detail"), [
    ("monthly", "mensalidade ativa"),
    ("weekly", "inscrição ativa"),
    ("charges", "cobrança de mensalidade"),
    ("accounts", "contas vinculadas"),
])
def test_merge_conflicts_do_not_change_either_player(conflict, detail):
    async def scenario():
        async with merge_fixture() as (factory, client, _):
            async with factory() as session:
                source = await d.person_for_name(session, "Gomes 👆🏾")
                target = await d.person_for_name(session, "Gomes")
                if conflict == "monthly":
                    session.add_all([monthly_row(source, 1), monthly_row(target, 2)])
                elif conflict == "weekly":
                    game = game_row()
                    session.add(game)
                    await session.flush()
                    session.add_all([entry_row(game, source), entry_row(game, target, position=2)])
                elif conflict == "charges":
                    await d.set_charge(session, source.id, "monthly", GAME_DATE, status="paid")
                    await d.set_charge(session, target.id, "monthly", GAME_DATE)
                else:
                    (await d.touch_account(session, ADMIN)).person_id = target.id
                    (await d.touch_account(session, PLAYER)).person_id = source.id
                await session.commit()

            response = await client.post(f"/api/people/{source.id}/merge", json={"target_id": str(target.id)})
            assert response.status_code == 409 and detail in response.json()["detail"]
            async with factory() as session:
                assert await session.get(Person, source.id) is not None
                assert await session.get(Person, target.id) is not None
                assert await session.scalar(select(PersonAlias).where(PersonAlias.alias_normalized == source.normalized_name)) is None
                assert await session.scalar(select(AuditEvent).where(AuditEvent.action == "merge")) is None
                if conflict == "charges":
                    rows = (await session.scalars(select(Charge))).all()
                    assert {c.person_id: c.status for c in rows} == {source.id: "paid", target.id: "pending"}
    asyncio.run(scenario())
