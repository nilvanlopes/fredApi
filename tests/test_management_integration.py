"""Real PostgreSQL integration checks; opt in with FRED_TEST_DATABASE_URL."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app import management as d
from app import admin_api
from app.admin_api import router
from app.auth import current_user
from app.database import get_session
from app.models import Charge, EntityRevision, MonthlySubscriber, ProcessedConversationMessage, WeeklyAttendance, WeeklyAttendanceEntry, AuditEvent
from app.parser import parse_weekly_attendance_message
from app.services import apply_weekly_attendance, promote_due_weekly_attendances
from fastapi import FastAPI, HTTPException

URL=os.getenv("FRED_TEST_DATABASE_URL")
pytestmark=pytest.mark.skipif(not URL,reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")


def test_management_end_to_end():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        admin={"uid":"a"*64,"username":"pyu","name":"Gestor","email":"admin@example.com","is_admin":True}
        player={"uid":"b"*64,"username":"player","name":"Jogador","email":"player@example.com","is_admin":False}
        other={"uid":"c"*64,"username":"other","name":"Outro","email":"other@example.com","is_admin":False}
        identity=admin
        app=FastAPI()
        app.include_router(router)
        async def actor(): return identity
        async def session_dep():
            async with factory() as session: yield session
        app.dependency_overrides[current_user]=actor
        app.dependency_overrides[get_session]=session_dep
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            async def request(method,path,**kwargs):
                r=await client.request(method,path,**kwargs)
                assert r.status_code<400,(method,path,r.status_code,r.text)
                return r.json()
            # Mirror current_user's account upsert for the initial manager.
            await request("GET","/api/me")
            p=await request("POST","/api/people",json={"name":"Alice"})
            p2=await request("POST","/api/people",json={"name":"Bob"})
            identity=player
            own=await request("GET","/api/me")
            assert own["person"] is None and own["games"]==[]
            assert (await client.get("/api/people")).status_code==403
            identity=other
            await request("GET","/api/me")
            identity=admin
            await request("PATCH",f"/api/accounts/{player['uid']}",json={"person_id":p["id"]})
            await request("PATCH",f"/api/accounts/{other['uid']}",json={"person_id":p2["id"]})
            next_date=date.today()+timedelta(days=7)
            next_date+=timedelta(days=(2-next_date.weekday())%7)
            g=await request("POST","/api/games",json={"game_date":str(next_date),"capacity":1})
            await request("POST","/api/monthly",json={"person_id":p["id"],"month":next_date.month,"year":next_date.year,"has_paid":True})
            identity=player
            await request("POST",f"/api/me/games/{g['id']}/join")
            mine=await request("GET","/api/me")
            assert mine["games"][0]["own_entry"]["status"]=="main"
            assert "Bob" not in str(mine)
            identity=other
            await request("POST",f"/api/me/games/{g['id']}/join")
            theirs=await request("GET","/api/me")
            assert theirs["games"][0]["own_entry"]["status"]=="waiting"
            assert not theirs["charges"]
            identity=admin
            detail=await request("GET",f"/api/games/{g['id']}")
            assert len(detail["entries"])==2
            bills=await request("GET","/api/charges")
            monthly=bills["items"][0]
            await request("PATCH",f"/api/charges/{monthly['id']}",json={"status":"paid"})
            assert (await request("GET","/api/debtors"))["total_cents"]==0
            assert (await request("GET", "/api/charges?type=single"))["items"] == []
            # Local roles and account links are administrative changes, audited.
            await request("PATCH",f"/api/accounts/{other['uid']}",json={"is_admin":True})
            assert (await request("GET","/api/audit"))["items"]
            # The player can leave before 19:30; a tombstone remains.
            identity=player
            await request("DELETE",f"/api/me/games/{g['id']}/join")
            assert (await request("GET","/api/me"))["games"][0]["own_entry"] is None
            identity=player
            assert (await client.delete(f"/api/accounts/{other['uid']}")).status_code==403
            identity=admin
            assert (await client.delete(f"/api/accounts/{admin['uid']}")).status_code==409
            assert (await client.delete(f"/api/accounts/{'d'*64}")).status_code==404
            await request("DELETE",f"/api/accounts/{other['uid']}")
            assert other["uid"] not in [item["uid"] for item in (await request("GET","/api/accounts"))["items"]]
            # Accounts are ordered by username: player precedes the manager pyu.
            assert [item["uid"] for item in (await request("GET","/api/accounts"))["items"]]==[player["uid"],admin["uid"]]
            assert (await request("GET",f"/api/games/{g['id']}"))["entries"]
            assert any(item["action"]=="delete" and item["entity_type"]=="account" for item in (await request("GET","/api/audit"))["items"])
        async with factory() as session:
            people=(await session.execute(text("SELECT id,name FROM people ORDER BY name"))).all()
            alice,bob=people[0][0],people[1][0]
            gdb=await session.get(WeeklyAttendance,g["id"])
            # Old WhatsApp snapshot cannot resurrect a later manual withdrawal.
            old=d.now()-timedelta(days=1)
            parsed=parse_weekly_attendance_message(f"LISTA VOLEI FREDERICO {next_date:%d/%m/%Y}\n1. Alice\n2. Bob",received_at=old)
            await apply_weekly_attendance(session,parsed=parsed,received_at=old,commit=False)
            active=await d.active_entries(session,gdb.id)
            assert alice not in [e.person_id for e in active]
            assert await session.scalar(select(func_count_audit_stale()))
            # Post-cutoff vacant slots promote FIFO and create an avulso.
            future=datetime.combine(next_date,time(17),d.TZ)
            await d.recalculate(session,gdb,at=future)
            bentry=next(e for e in await d.active_entries(session,gdb.id) if e.person_id==bob)
            assert bentry.status=="main"
            charge=await session.scalar(select(Charge).where(Charge.person_id==bob,Charge.type=="single"))
            assert charge.status=="pending" and charge.amount_cents==750
            await d.remove_entry(session,gdb,bentry,at=future)
            assert charge.status=="cancelled"
            await d.add_entry(session,gdb,await d.person_for_name(session,"Bob"),at=future+timedelta(minutes=1))
            assert charge.status=="pending"
            with pytest.raises(Exception) as error:
                d.ensure_open(gdb,datetime.combine(next_date,time(19,30),d.TZ))
            assert error.value.status_code==409
            # Reading a historical game must not promote waiting players or bill them.
            historical_date=date(2025,1,1)
            historical=WeeklyAttendance(game_date=historical_date,capacity=24,cutoff_at=datetime.combine(historical_date,time(16),d.TZ),starts_at=datetime.combine(historical_date,time(19,30),d.TZ))
            session.add(historical)
            await session.flush()
            waiting=WeeklyAttendanceEntry(attendance_id=historical.id,person_id=alice,name="Alice",normalized_name="alice",source_section="guests",source_position=1,display_order=1,status="waiting",is_monthly_subscriber=False,owes_single_payment=False,joined_at=datetime.combine(historical_date,time(15),d.TZ))
            session.add(waiting)
            await session.flush()
            await d.recalculate(session,historical,source="system")
            assert waiting.status=="waiting"
            assert await session.scalar(select(Charge).where(Charge.person_id==alice,Charge.reference_date==historical_date)) is None
            # Cancellation preserves the original paid_at, without a refund operation.
            paid=await d.set_charge(session,alice,"single",historical_date,status="paid")
            paid_at=paid.paid_at
            await d.set_charge(session,alice,"single",historical_date,status="cancelled")
            assert paid.paid_at==paid_at
            # A paid avulso can leave/rejoin without billing twice or refunding.
            paid_future=await d.set_charge(session,bob,"single",gdb.game_date,status="paid",occurred_at=future+timedelta(minutes=2))
            original_paid_at=paid_future.paid_at
            current_entry=next(e for e in await d.active_entries(session,gdb.id) if e.person_id==bob)
            await d.remove_entry(session,gdb,current_entry,at=future+timedelta(minutes=3))
            assert paid_future.status=="cancelled" and paid_future.paid_at==original_paid_at
            await d.add_entry(session,gdb,await d.person_for_name(session,"Bob"),at=future+timedelta(minutes=4))
            assert paid_future.status=="paid" and paid_future.paid_at==original_paid_at
            await session.rollback()
        await engine.dispose()
    asyncio.run(scenario())


def test_scheduled_promotion_uses_latest_compacted_list_order():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        game_date = date(2030, 1, 2)  # Wednesday
        cutoff = datetime.combine(game_date, time(16), d.TZ)
        main_names = [f"Main{position:02d}" for position in range(2, 19)]
        guest_names = [f"Guest{position:02d}" for position in range(1, 9)]
        snapshot = (
            f"LISTA VÔLEI FREDERICO {game_date:%d/%m/%Y}\n1.\n"
            + "\n".join(f"{position}. {name}" for position, name in enumerate(main_names, start=2))
            + "\n\nConvidados\n"
            + "\n".join(f"{position}. {name} (conv. Main02)" for position, name in enumerate(guest_names, start=1))
        )
        async with factory() as session:
            game = WeeklyAttendance(
                game_date=game_date, capacity=24, cutoff_at=cutoff,
                starts_at=datetime.combine(game_date, time(19, 30), d.TZ),
            )
            session.add(game)
            await session.flush()
            await apply_weekly_attendance(
                session, parsed=parse_weekly_attendance_message(snapshot, received_at=cutoff - timedelta(hours=1)),
                received_at=cutoff - timedelta(hours=1), commit=False,
            )
            entries = await d.active_entries(session, game.id)
            assert [entry.display_order for entry in entries] == list(range(1, 26))
            # Existing records can have older timestamps in an order that no
            # longer matches the latest WhatsApp snapshot. Display order wins.
            for index, entry in enumerate(entries):
                entry.joined_at = cutoff - timedelta(minutes=index + 1)
            await session.flush()

            promoted = await promote_due_weekly_attendances(session, now=cutoff)

        expected_main = main_names + guest_names[:7]
        expected_display = main_names + [f"{name} (conv. Main02)" for name in guest_names[:7]]
        expected_text = (
            f"LISTA VÔLEI FREDERICO {game_date:%d/%m}\n"
            + "\n".join(f"{position}. {name}" for position, name in enumerate(expected_display, start=1))
            + f"\n\nConvidados\n1. {guest_names[7]} (conv. Main02)"
        )
        assert len(promoted.processed) == 1
        assert [entry.name for entry in promoted.processed[0].promoted] == expected_main
        assert promoted.processed[0].text == expected_text
        async with factory() as session:
            game = await session.scalar(select(WeeklyAttendance).where(WeeklyAttendance.game_date == game_date))
            assert game is not None
            late_joiner = await d.person_for_name(session, "LateJoiner")
            entry = await d.add_entry(
                session, game, late_joiner, at=cutoff + timedelta(minutes=1), source="self_service",
            )
            assert entry.display_order == 26 and entry.status == "waiting"
        await engine.dispose()

    asyncio.run(scenario())


def test_whatsapp_snapshot_refreshes_the_weekly_list_order_and_source_positions():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        async with factory() as session:
            game_date=date.today()+timedelta(days=7)
            game_date+=timedelta(days=(2-game_date.weekday())%7)
            game=WeeklyAttendance(game_date=game_date,capacity=24,cutoff_at=datetime.combine(game_date,time(16),d.TZ),starts_at=datetime.combine(game_date,time(19,30),d.TZ))
            session.add(game)
            await session.flush()
            received_at=datetime.combine(game_date,time(17),d.TZ)
            first=parse_weekly_attendance_message(f"LISTA VOLEI FREDERICO {game_date:%d/%m/%Y}\n1. Alice\n2. Bob\n3. Charlie",received_at=received_at)
            await apply_weekly_attendance(session,parsed=first,received_at=received_at,commit=False)
            received_at+=timedelta(minutes=1)
            corrected=parse_weekly_attendance_message(f"LISTA VOLEI FREDERICO {game_date:%d/%m/%Y}\n1. Charlie\n2. Alice\n3. Bob",received_at=received_at)
            await apply_weekly_attendance(session,parsed=corrected,received_at=received_at,commit=False)
            rows=await d.active_entries(session,game.id)
            assert [row.name for row in rows]==["Charlie","Alice","Bob"]
            assert [row.source_position for row in rows]==[1,2,3]
            await session.rollback()
        await engine.dispose()
    asyncio.run(scenario())


def test_admin_game_detail_uses_whatsapp_section_and_position_order():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE weekly_attendances RESTART IDENTITY CASCADE"))
        async with factory() as session:
            game_date = date(2025, 1, 8)
            game = WeeklyAttendance(
                game_date=game_date, capacity=2,
                cutoff_at=datetime.combine(game_date, time(16), d.TZ),
                starts_at=datetime.combine(game_date, time(19, 30), d.TZ),
            )
            session.add(game)
            await session.flush()
            source_order = [
                ("Alice", "main", 1, "waiting", 4),
                ("Bob", "main", 4, "main", 2),
                ("Charlie", "guests", 1, "main", 1),
                ("Diana", "guests", 3, "waiting", 3),
            ]
            for name, source_section, source_position, status, display_order in source_order:
                session.add(WeeklyAttendanceEntry(
                    attendance_id=game.id, name=name, normalized_name=name.lower(), status=status,
                    source_section=source_section, source_position=source_position, display_order=display_order,
                ))
            await session.flush()

            detail = await admin_api.game_get(game.id, user={"is_admin": True}, session=session)
            assert detail["main_count"] == detail["waiting_count"] == 2
            assert [(
                row["name"], row["source_section"], row["source_position"], row["status"], row["position"],
            ) for row in detail["entries"]] == source_order
        await engine.dispose()

    asyncio.run(scenario())


def test_audit_projects_semantic_list_changes_and_filters_group_participants():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,audit_events,processed_conversation_messages RESTART IDENTITY CASCADE"))
        async with factory() as session:
            alice = await d.person_for_name(session, "Alice")
            bob = await d.person_for_name(session, "Bob")
            await d.audit(session, entity_type="charge", entity_id="monthly-charge", action="update",
                person_id=alice.id, before={"status":"pending"}, after={"status":"paid","type":"monthly","person_id":alice.id,"reference_date":date(2026,11,1)})
            await d.audit(session, entity_type="charge", entity_id="single-charge", action="update",
                person_id=bob.id, before={"status":"pending"}, after={"status":"paid","type":"single","person_id":bob.id,"reference_date":date(2026,11,17)})
            await d.audit(session, entity_type="charge", entity_id="whatsapp-charge", action="update", source="whatsapp",
                person_id=alice.id, before={"status":"pending"}, after={"status":"paid","type":"monthly","person_id":alice.id,"reference_date":date(2026,11,1)})
            await d.audit(session, entity_type="weekly", entity_id="game", action="replace_player",
                person_id=bob.id, before={"person_id":alice.id,"name":"Alice","game_date":date(2026,11,17)},
                after={"person_id":bob.id,"name":"Bob","game_date":date(2026,11,17)})
            await d.audit(session, entity_type="person", entity_id=alice.id, action="alias",
                person_id=alice.id, after={"alias":"Al","canonical_person_name":"Alice"})
            await d.audit(session, entity_type="ingestion", entity_id="weekly:2026-11-17", action="weekly_attendance",
                source="whatsapp", after={"message_id":"raw-ingestion","status":"applied"})
            await d.audit(session, entity_type="weekly", entity_id="game", action="update", source="import",
                person_id=alice.id, before={"status":"waiting"}, after={"status":"main"})
            previous = ProcessedConversationMessage(
                fingerprint="audit-before", chat_id="audit-chat", source_ordinal=1,
                occurred_at=d.now(), message_type="weekly_attendance", status="applied",
                analyzer="test", confidence=1, analysis={}, result={}, raw_text="Lista anterior: Alice",
            )
            current = ProcessedConversationMessage(
                fingerprint="audit-after", chat_id="audit-chat", source_ordinal=2,
                occurred_at=d.now(), message_type="weekly_attendance", status="applied",
                analyzer="test", confidence=1, analysis={}, result={}, raw_text="Lista atual: Alice e Bob",
            )
            session.add_all([previous, current])
            await session.flush()
            await d.audit(session, entity_type="list", entity_id="weekly:2026-11-17", action="list_change",
                source="whatsapp", person_id=None, after={
                    "message_id": current.id, "previous_message_id": previous.id,
                    "changes": [{"kind": "player_replaced", "people": [
                        {"id": str(alice.id), "name": "Alice", "is_actor": False},
                        {"id": str(bob.id), "name": "Bob", "is_actor": False},
                    ]}],
                    "participant_ids": [str(alice.id), str(bob.id)],
                })
            await session.commit()

            alice_events = await admin_api.audit_list(person_id=alice.id, limit=20, user={"is_admin": True}, session=session)
            item = next(event for event in alice_events["items"] if event["action"] == "list_change")
            assert item["changes"] == [{"kind": "player_replaced", "people": [
                {"id": str(alice.id), "name": "Alice", "is_actor": False},
                {"id": str(bob.id), "name": "Bob", "is_actor": False},
            ]}]
            assert item["message_diff"] == {
                "before": "Lista anterior: Alice", "after": "Lista atual: Alice e Bob",
            }
            assert item["participant_ids"] == [str(alice.id), str(bob.id)]
            bob_events = await admin_api.audit_list(person_id=bob.id, limit=20, user={"is_admin": True}, session=session)
            assert any(event["action"] == "list_change" for event in bob_events["items"])
            missing_events = await admin_api.audit_list(person_id=uuid4(), limit=20, user={"is_admin": True}, session=session)
            assert missing_events["items"] == []

            all_events = await admin_api.audit_list(limit=20, user={"is_admin": True}, session=session)
            assert not any(event["entity_type"] == "ingestion" for event in all_events["items"])
            assert not any(event["source"] == "import" for event in all_events["items"])
            assert any(event["action"] == "list_change" for event in all_events["items"])
            semantic = [change for event in all_events["items"] for change in event.get("changes", []) if event["action"] != "list_change"]
            paid = [change["kind"] for change in semantic]
            assert "monthly_paid" in paid and "guest_paid" in paid
            assert paid.count("monthly_paid") == 1
            replacement = next(event for event in all_events["items"] if event["action"] == "replace_player")
            assert replacement["changes"] == [{"kind":"player_replaced","reference_date":"2026-11-17","people":[
                {"id":str(alice.id),"name":"Alice","is_actor":False},
                {"id":str(bob.id),"name":"Bob","is_actor":False},
            ]}]
            alias_event = next(event for event in all_events["items"] if event["action"] == "alias")
            assert alias_event["changes"] == [{"kind":"alias_added","alias":"Al","people":[{"id":str(alice.id),"name":"Alice"}]}]
        await engine.dispose()

    asyncio.run(scenario())


def test_late_whatsapp_snapshot_reconciles_pending_charges_for_its_game_date():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        async with factory() as session:
            game_date=date(2026,11,11)
            starts_at=datetime(2026,11,11,19,30,tzinfo=d.TZ)
            received_at=datetime(2026,11,12,18,38,tzinfo=d.TZ)
            game=WeeklyAttendance(game_date=game_date,capacity=24,cutoff_at=datetime(2026,11,11,16,tzinfo=d.TZ),starts_at=starts_at)
            session.add(game)
            await session.flush()

            omitted=await d.person_for_name(session,"Omitted")
            paid_person=await d.person_for_name(session,"Already paid")
            waived_person=await d.person_for_name(session,"Waived")
            orphan=await d.person_for_name(session,"Orphan charge")
            for position,person in enumerate((omitted,paid_person,waived_person),1):
                session.add(WeeklyAttendanceEntry(
                    attendance_id=game.id,person_id=person.id,name=person.name,
                    normalized_name=person.normalized_name,source_section="main",
                    source_position=position,display_order=position,status="main",
                    is_monthly_subscriber=False,owes_single_payment=True,
                    joined_at=starts_at-timedelta(hours=1),
                ))
            await session.flush()
            for person in (omitted,paid_person,waived_person):
                await d.set_charge(session,person.id,"single",game_date,status="pending",occurred_at=starts_at-timedelta(minutes=30))
            paid=await d.set_charge(session,paid_person.id,"single",game_date,status="paid",occurred_at=starts_at-timedelta(minutes=20))
            paid_at=paid.paid_at
            waived=await d.set_charge(session,waived_person.id,"single",game_date,status="waived",occurred_at=starts_at-timedelta(minutes=10),reason="Dispensa confirmada")
            orphan_charge=await d.set_charge(session,orphan.id,"single",game_date,status="pending",occurred_at=starts_at-timedelta(minutes=5))
            await session.flush()

            first=parse_weekly_attendance_message(
                f"LISTA VOLEI FREDERICO {game_date:%d/%m/%Y}\n1. Alice",
                received_at=received_at,
            )
            await apply_weekly_attendance(session,parsed=first,received_at=received_at,commit=False)

            assert (await session.scalar(select(Charge).where(Charge.person_id==omitted.id,Charge.type=="single"))).status=="cancelled"
            assert (await session.scalar(select(Charge).where(Charge.person_id==orphan.id,Charge.type=="single"))).status=="cancelled"
            assert paid.status=="paid" and paid.paid_at==paid_at
            assert waived.status=="waived"

            later=received_at+timedelta(minutes=1)
            corrected=parse_weekly_attendance_message(
                f"LISTA VOLEI FREDERICO {game_date:%d/%m/%Y}\n1. Alice\n2. Omitted",
                received_at=later,
            )
            await apply_weekly_attendance(session,parsed=corrected,received_at=later,commit=False)
            restored=await session.scalar(select(Charge).where(Charge.person_id==omitted.id,Charge.type=="single"))
            assert restored.status=="pending"
            assert orphan_charge.status=="cancelled"
            await session.rollback()
        await engine.dispose()
    asyncio.run(scenario())


def test_weekly_whatsapp_check_marks_pay_only_eligible_charges(monkeypatch):
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))

        game_date = date(2026, 11, 11)
        start = datetime.combine(game_date, time(19, 30), d.TZ)
        first_at = datetime.combine(game_date, time(17), d.TZ)
        checked_at = first_at + timedelta(minutes=20)
        monkeypatch.setattr(d, "now", lambda: first_at + timedelta(hours=1))
        async with factory() as session:
            game = WeeklyAttendance(
                game_date=game_date, capacity=5, starts_at=start,
                cutoff_at=datetime.combine(game_date, time(16), d.TZ),
            )
            session.add(game)
            await session.flush()

            async def apply_list(at, *names):
                lines = "\n".join(f"{position}. {name}" for position, name in enumerate(names, 1))
                parsed = parse_weekly_attendance_message(
                    f"LISTA VOLEI FREDERICO {game_date:%d/%m/%Y}\n{lines}", received_at=at,
                )
                return await apply_weekly_attendance(session, parsed=parsed, received_at=at, commit=False)

            regulars = ("Alice (conv Lauro)", "Bob", "Waived", "Cancelled")
            await apply_list(first_at, *regulars, "Returning")
            people = {entry.name: entry.person_id for entry in await d.active_entries(session, game.id)}

            async def charge_for(name):
                return await session.scalar(select(Charge).where(
                    Charge.person_id == people[name], Charge.type == "single", Charge.reference_date == game_date,
                ))

            await d.set_charge(session, people["Waived"], "single", game_date, status="waived",
                               occurred_at=first_at + timedelta(minutes=5), reason="Dispensa confirmada")
            await d.set_charge(session, people["Cancelled"], "single", game_date, status="cancelled",
                               occurred_at=first_at + timedelta(minutes=5), reason="Cancelamento manual")
            await apply_list(first_at + timedelta(minutes=10), *regulars)
            assert (await charge_for("Returning")).status == "cancelled"

            result = await apply_list(checked_at, "Alice (conv Lauro)✅", "Bob", "Waived✅",
                                      "Cancelled✅", "Returning✅", "Waiting✅")
            entries = {entry.name: entry for entry in result.entries}
            alice_charge = await charge_for("Alice")
            returning_charge = await charge_for("Returning")
            assert alice_charge.status == returning_charge.status == "paid"
            assert alice_charge.paid_at == returning_charge.paid_at == checked_at
            assert not entries["Alice"].owes_single_payment
            assert not entries["Returning"].owes_single_payment
            assert entries["Bob"].owes_single_payment
            for name in ("Waived", "Cancelled"):
                charge = await charge_for(name)
                assert charge.status == "paid" and charge.paid_at == checked_at
                assert not entries[name].owes_single_payment
            waiting = next(entry for entry in await d.active_entries(session, game.id) if entry.name == "Waiting")
            people["Waiting"] = waiting.person_id
            assert waiting.status == "waiting"
            assert await charge_for("Waiting") is None

            await apply_list(checked_at - timedelta(minutes=1), "Alice (conv Lauro)", "Bob✅", "Waived",
                             "Cancelled", "Returning", "Waiting")
            assert (await charge_for("Bob")).status == "pending"

            second_check_at = checked_at + timedelta(minutes=1)
            waived_at = checked_at + timedelta(minutes=2)
            bob_id = people["Bob"]
            await d.set_charge(session, bob_id, "single", game_date, status="waived",
                               occurred_at=waived_at, reason="Dispensa posterior")
            weekly_revision = await session.get(EntityRevision, f"weekly:{bob_id}:{game_date}")
            charge_revision = await session.get(EntityRevision, f"charge:{bob_id}:single:{game_date}")
            assert weekly_revision.occurred_at < second_check_at < charge_revision.occurred_at

            result = await apply_list(second_check_at, "Alice (conv Lauro)", "Bob✅", "Waived",
                                      "Cancelled", "Returning", "Waiting")
            assert alice_charge.status == returning_charge.status == "paid"
            assert alice_charge.paid_at == returning_charge.paid_at == checked_at
            bob_charge = await charge_for("Bob")
            assert bob_charge.status == "waived" and bob_charge.paid_at is None
            assert weekly_revision.occurred_at == second_check_at
            assert charge_revision.occurred_at == waived_at
            attempted_update = await session.scalar(select(AuditEvent.id).where(
                AuditEvent.entity_type == "charge", AuditEvent.entity_id == str(bob_charge.id),
                AuditEvent.source == "whatsapp", AuditEvent.occurred_at == second_check_at,
            ))
            assert attempted_update is None
            assert not next(entry for entry in result.entries if entry.name == "Bob").owes_single_payment
            await session.rollback()
        await engine.dispose()

    asyncio.run(scenario())


def test_pending_guest_charge_is_shown_on_the_guest_and_grouped_under_inviter():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        admin = {"uid": "a"*64, "username": "gestor", "is_admin": True}
        inviter_user = {"uid": "b"*64, "username": "pyu"}
        guest_user = {"uid": "c"*64, "username": "thiago"}
        identity = admin
        async with factory() as session:
            inviter=await d.person_for_name(session,"Pyu")
            new_inviter=await d.person_for_name(session,"Jéssica")
            guest=await d.person_for_name(session,"Thiago Sousa (convidado de Pyu)")
            (await d.touch_account(session, inviter_user)).person_id = inviter.id
            (await d.touch_account(session, guest_user)).person_id = guest.id
            game_date=date(2026,11,11)
            game=WeeklyAttendance(game_date=game_date,capacity=24,cutoff_at=datetime(2026,11,11,16,tzinfo=d.TZ),starts_at=datetime(2026,11,11,19,30,tzinfo=d.TZ))
            session.add(game)
            await session.flush()
            entry=WeeklyAttendanceEntry(
                attendance_id=game.id,person_id=guest.id,name="Thiago Sousa",
                normalized_name=guest.normalized_name,source_section="main",
                source_position=13,display_order=13,status="main",
                is_monthly_subscriber=False,owes_single_payment=True,
                invited_by=inviter.name,normalized_invited_by=inviter.normalized_name,
                joined_at=game.starts_at-timedelta(hours=1),
            )
            session.add(entry)
            charge=await d.set_charge(session,guest.id,"single",game_date,status="pending")
            await session.commit()

            charges=await admin_api.charges(status=None,type=None,person_id=None,start_date=None,end_date=None,user={"is_admin":True},session=session)
            debts=await admin_api.debtors(user={"is_admin":True},session=session)
            row=next(item for item in charges["items"] if item["id"]==charge.id)
            inviter_debt=next(item for item in debts["items"] if item["person_id"]==inviter.id)
            assert row["name"]=="Thiago Sousa"
            assert row["type"]=="single"
            assert row["invited_by"]=="Pyu"
            assert row["debtor_person_id"]==inviter.id
            assert inviter_debt["amount_cents"]==750 and inviter_debt["count"]==1
            assert all(item["person_id"]!=guest.id for item in debts["items"])

        app=FastAPI()
        app.include_router(router)
        async def actor():
            return identity
        async def session_dep():
            async with factory() as session:
                yield session
        app.dependency_overrides[current_user]=actor
        app.dependency_overrides[get_session]=session_dep

        path=f"/api/games/{game.id}/entries/{entry.id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            identity = inviter_user
            response = await client.get("/api/me")
            response.raise_for_status()
            personal_charge, = response.json()["charges"]
            assert personal_charge["person_id"] == str(guest.id)
            assert personal_charge["name"] == "Thiago Sousa"
            assert personal_charge["amount_cents"] == 750
            identity = guest_user
            response = await client.get("/api/me")
            response.raise_for_status()
            assert response.json()["charges"] == []
            identity = admin

            async def assert_attribution(debtor, invited_by):
                charges_response=await client.get("/api/charges?status=pending&type=single")
                debts_response=await client.get("/api/debtors")
                charges_response.raise_for_status()
                debts_response.raise_for_status()
                row,=charges_response.json()["items"]
                assert row["id"]==str(charge.id)
                assert row["person_id"]==str(guest.id)
                assert row["invited_by"]==invited_by
                assert row["debtor_person_id"]==str(debtor.id)
                debts=debts_response.json()
                assert debts["total_cents"]==750
                debt,=debts["items"]
                assert debt["person_id"]==str(debtor.id)
                assert debt["amount_cents"]==750 and debt["count"]==1

            response=await client.patch(path,json={"invited_by":"  JÉSSICA  "})
            response.raise_for_status()
            await assert_attribution(new_inviter,"JÉSSICA")
            async with factory() as session:
                saved=await session.get(WeeklyAttendanceEntry,entry.id)
                assert saved.invited_by=="JÉSSICA"
                assert saved.normalized_invited_by==new_inviter.normalized_name
                # Simulate an entry edited before the normalization fix.
                saved.normalized_invited_by=inviter.normalized_name
                await session.commit()
            await assert_attribution(new_inviter,"JÉSSICA")

            response=await client.patch(path,json={"invited_by":None})
            response.raise_for_status()
            await assert_attribution(guest,None)
            identity = inviter_user
            response = await client.get("/api/me")
            response.raise_for_status()
            assert response.json()["charges"] == []
            identity = guest_user
            response = await client.get("/api/me")
            response.raise_for_status()
            personal_charge, = response.json()["charges"]
            assert personal_charge["id"] == str(charge.id)
            assert personal_charge["debtor_person_id"] == str(guest.id)
            async with factory() as session:
                saved=await session.get(WeeklyAttendanceEntry,entry.id)
                assert saved.invited_by is None
                assert saved.normalized_invited_by is None
        await engine.dispose()
    asyncio.run(scenario())


def test_weekly_replace_player_transfers_only_the_selected_entry_and_charge(monkeypatch):
    async def scenario():
        assert URL and "fred_test" in URL
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE people, weekly_attendances, processed_conversation_messages, charges, "
                "audit_events, entity_revisions RESTART IDENTITY CASCADE"
            ))
        game_date = date(2026, 11, 11)
        listed_at = datetime.combine(game_date, time(17), d.TZ)
        corrected_at = listed_at + timedelta(days=1)
        monkeypatch.setattr(d, "now", lambda: corrected_at)
        admin = {"uid": "a" * 64, "username": "gestor", "is_admin": True}
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
            wrong = await d.person_for_name(session, "Cadastro incorreto")
            right = await d.person_for_name(session, "Jogador correto")
            inviter = await d.person_for_name(session, "Convidante")
            occupied = await d.person_for_name(session, "Já inscrito")
            inactive = await d.person_for_name(session, "Inativo")
            inactive.active = False
            collision = await d.person_for_name(session, "Com outra cobrança")
            game = WeeklyAttendance(
                game_date=game_date, capacity=2, cutoff_at=listed_at - timedelta(hours=1),
                starts_at=listed_at + timedelta(hours=2, minutes=30),
            )
            source = ProcessedConversationMessage(
                fingerprint="replace-player-source", source="waha", message_type="weekly_attendance",
                occurred_at=listed_at, status="applied", raw_text="Lista original", chat_id="test",
                source_ordinal=1, analyzer="parser", confidence=1, analysis={}, result={},
            )
            session.add_all([game, source])
            await session.flush()
            entry = WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=wrong.id, name=wrong.name,
                normalized_name=wrong.normalized_name, source_position=7, source_section="guests",
                status="main", display_order=2, joined_at=listed_at, source_message_id=source.id,
                prebuilt_team_number=3, invited_by=inviter.name, normalized_invited_by=inviter.normalized_name,
            )
            other = WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=occupied.id, name=occupied.name,
                normalized_name=occupied.normalized_name, source_position=1, source_section="main",
                status="main", display_order=1, joined_at=listed_at,
            )
            session.add_all([entry, other])
            charge = await d.set_charge(
                session, wrong.id, "single", game_date, status="paid", amount=975, occurred_at=listed_at,
            )
            previous_charge = await d.set_charge(session, wrong.id, "single", game_date - timedelta(days=7))
            await d.set_charge(session, collision.id, "single", game_date)
            await session.commit()

        path = f"/api/games/{game.id}/entries/{entry.id}/player"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            identity = {"uid": "b" * 64, "username": "jogador", "is_admin": False}
            assert (await client.patch(path, json={"person_id": str(right.id)})).status_code == 403
            identity = admin
            for target_id, expected in [
                (uuid4(), 404), (inactive.id, 409), (occupied.id, 409), (collision.id, 409),
            ]:
                response = await client.patch(path, json={"person_id": str(target_id)})
                assert response.status_code == expected

            response = await client.patch(path, json={"person_id": str(right.id)})
            assert response.status_code == 200, response.text
            response = await client.patch(path, json={"person_id": str(right.id)})
            assert response.status_code == 200
            response = await client.get(f"/api/games/{game.id}")
            response.raise_for_status()
            assert [row["person_id"] for row in response.json()["entries"]] == [str(occupied.id), str(right.id)]
            response = await client.get(f"/api/charges?person_id={right.id}")
            response.raise_for_status()
            transferred, = response.json()["items"]
            assert transferred["id"] == str(charge.id)
            assert transferred["amount_cents"] == 975
            assert transferred["status"] == "paid"
            assert datetime.fromisoformat(transferred["paid_at"]) == listed_at
            assert transferred["person_id"] == str(right.id)
            assert transferred["debtor_person_id"] == str(inviter.id)

        async with factory() as session:
            saved = await session.get(WeeklyAttendanceEntry, entry.id)
            assert saved.name == right.name and saved.normalized_name == right.normalized_name
            assert saved.display_order == 2 and saved.status == "main"
            assert saved.source_position == 7 and saved.source_section == "guests"
            assert saved.source_message_id == source.id and saved.joined_at == listed_at
            assert saved.invited_by == inviter.name and saved.prebuilt_team_number == 3
            assert not saved.owes_single_payment
            assert (await session.get(Charge, previous_charge.id)).person_id == wrong.id
            assert {event.action for event in await session.scalars(
                select(AuditEvent).where(AuditEvent.person_id == right.id)
            )} == {"replace_player", "identity_transfer"}
            for person in (wrong, right):
                for key in (f"weekly:{person.id}:{game_date}", f"charge:{person.id}:single:{game_date}"):
                    assert (await session.get(EntityRevision, key)).occurred_at == corrected_at

            older_message = parse_weekly_attendance_message(
                f"LISTA VOLEI FREDERICO {game_date:%d/%m/%Y}\n1. Já inscrito\n2. Cadastro incorreto",
                received_at=listed_at,
            )
            await apply_weekly_attendance(session, parsed=older_message, received_at=listed_at, commit=False)
            assert saved.person_id == right.id and saved.deleted_at is None
            bill = await session.get(Charge, charge.id)
            assert bill.person_id == right.id and bill.status == "paid" and bill.paid_at == listed_at
        await engine.dispose()

    asyncio.run(scenario())


def test_weekly_replace_player_recalculates_monthly_coverage_and_preserves_waiting(monkeypatch):
    async def scenario():
        assert URL and "fred_test" in URL
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE people, weekly_attendances, charges, audit_events, entity_revisions RESTART IDENTITY CASCADE"
            ))
        game_date = date(2026, 11, 11)
        cutoff = datetime.combine(game_date, time(16), d.TZ)
        monkeypatch.setattr(d, "now", lambda: cutoff + timedelta(days=1))
        async with factory() as session:
            original = await d.person_for_name(session, "Cadastro original")
            monthly = await d.person_for_name(session, "Mensalista")
            waiting = await d.person_for_name(session, "Jogador da espera")
            await d.monthly_upsert(session, monthly, game_date.month, game_date.year, has_paid=True)
            game = WeeklyAttendance(game_date=game_date, capacity=1, cutoff_at=cutoff)
            session.add(game)
            await session.flush()
            principal = WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=original.id, name=original.name,
                normalized_name=original.normalized_name, source_section="main",
                source_position=1, display_order=1, status="main",
            )
            duplicate = WeeklyAttendanceEntry(
                attendance_id=game.id, person_id=original.id, name=original.name,
                normalized_name=original.normalized_name, source_section="guests",
                source_position=1, display_order=2, status="main",
            )
            session.add_all([principal, duplicate])
            charge = await d.set_charge(session, original.id, "single", game_date)
            await session.flush()

            admin = {"uid": "a" * 64, "username": "gestor", "is_admin": True}
            with pytest.raises(HTTPException) as error:
                await d.replace_entry_player(session, game, principal, monthly, user=admin)
            assert error.value.status_code == 409
            assert charge.person_id == original.id
            duplicate.status = "waiting"
            await session.flush()
            await d.replace_entry_player(session, game, duplicate, waiting, user=admin)
            assert duplicate.status == "waiting"
            assert duplicate.person_id == waiting.id
            assert not duplicate.owes_single_payment
            assert charge.person_id == original.id and charge.status == "pending"
            assert await session.scalar(select(Charge).where(Charge.person_id == waiting.id)) is None

            await d.replace_entry_player(session, game, principal, monthly, user=admin)
            assert charge.person_id == monthly.id and charge.status == "cancelled"
            assert principal.person_id == monthly.id and principal.is_monthly_subscriber
            assert principal.status == "main" and not principal.owes_single_payment
            assert duplicate.status == "waiting" and duplicate.display_order == 2
        await engine.dispose()

    asyncio.run(scenario())


def test_paid_monthly_recalculates_past_games_only_in_that_month():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        async with factory() as session:
            person=await d.person_for_name(session,"Allan")
            november=WeeklyAttendance(
                game_date=date(2026,11,4),capacity=24,
                cutoff_at=datetime(2026,11,4,16,tzinfo=d.TZ),
                starts_at=datetime(2026,11,4,19,30,tzinfo=d.TZ),
            )
            october=WeeklyAttendance(
                game_date=date(2026,10,28),capacity=24,
                cutoff_at=datetime(2026,10,28,16,tzinfo=d.TZ),
                starts_at=datetime(2026,10,28,19,30,tzinfo=d.TZ),
            )
            session.add_all([november,october])
            await session.flush()
            entries=[]
            for game in (november,october):
                entry=WeeklyAttendanceEntry(
                    attendance_id=game.id,person_id=person.id,name=person.name,
                    normalized_name=person.normalized_name,source_section="main",
                    source_position=1,display_order=1,status="main",
                    is_monthly_subscriber=False,owes_single_payment=True,
                    joined_at=game.starts_at-timedelta(hours=1),
                )
                session.add(entry)
                charge=await d.set_charge(session,person.id,"single",game.game_date,status="pending")
                entries.append((entry,charge))
            await session.flush()

            await d.monthly_upsert(
                session,person,11,2026,has_paid=True,at=d.now(),
            )

            assert entries[0][0].is_monthly_subscriber is True
            assert entries[0][0].owes_single_payment is False
            assert entries[0][1].status=="cancelled"
            assert entries[1][0].is_monthly_subscriber is False
            assert entries[1][0].owes_single_payment is True
            assert entries[1][1].status=="pending"
            await session.rollback()
        await engine.dispose()
    asyncio.run(scenario())


def func_count_audit_stale():
    from sqlalchemy import func
    return func.count(AuditEvent.id).filter(AuditEvent.status=="stale")


def test_legacy_duplicates_leave_and_rejoin_once():
    async def scenario():
        assert URL and "fred_test" in URL
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        player={"uid":"d"*64,"username":"duplicate-player","name":"Player","email":"player@example.com","is_admin":False}
        async with factory() as session:
            p=await d.person_for_name(session,"Player")
            account=await d.touch_account(session,player)
            account.person_id=p.id
            future_date=date.today()+timedelta(days=7)
            future_date+=timedelta(days=(2-future_date.weekday())%7)
            g=WeeklyAttendance(game_date=future_date,capacity=1,cutoff_at=d.now()-timedelta(hours=1),starts_at=datetime.combine(future_date,time(19,30),d.TZ))
            session.add(g)
            await session.flush()
            principal=WeeklyAttendanceEntry(attendance_id=g.id,person_id=p.id,name=p.name,normalized_name=p.normalized_name,source_section="main",source_position=1,display_order=2,status="main",is_monthly_subscriber=False,owes_single_payment=True,joined_at=d.now()-timedelta(minutes=5))
            waiting=WeeklyAttendanceEntry(attendance_id=g.id,person_id=p.id,name=p.name,normalized_name=p.normalized_name,source_section="guests",source_position=1,display_order=1,status="waiting",is_monthly_subscriber=False,owes_single_payment=False,joined_at=d.now()-timedelta(minutes=4))
            tombstone=WeeklyAttendanceEntry(attendance_id=g.id,person_id=p.id,name=p.name,normalized_name=p.normalized_name,source_section="main",source_position=8,display_order=8,status="main",is_monthly_subscriber=False,owes_single_payment=False,joined_at=d.now()-timedelta(minutes=20),deleted_at=d.now()-timedelta(minutes=10))
            session.add_all([principal,waiting,tombstone])
            bill=await d.set_charge(session,p.id,"single",g.game_date,status="paid",occurred_at=d.now()-timedelta(minutes=3))
            paid_at=bill.paid_at
            await session.commit()
            game_id,person_id,principal_id,tombstone_id=g.id,p.id,principal.id,tombstone.id
        app=FastAPI()
        app.include_router(router)
        async def actor(): return player
        async def sessions():
            async with factory() as session: yield session
        app.dependency_overrides[current_user]=actor
        app.dependency_overrides[get_session]=sessions
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            mine=(await client.get("/api/me")).json()
            assert mine["games"][0]["own_entry"]["status"]=="main"
            assert mine["games"][0]["own_entry"]["id"]==str(principal_id)
            assert (await client.post(f"/api/me/games/{game_id}/join")).status_code==200
            async with factory() as session:
                active=await d.active_entries(session,game_id)
                assert len(active)==2 and tombstone_id not in {e.id for e in active}
            assert (await client.delete(f"/api/me/games/{game_id}/join")).status_code==200
            async with factory() as session:
                assert not await d.active_entries(session,game_id)
                events=(await session.scalars(select(AuditEvent).where(AuditEvent.person_id==person_id,AuditEvent.action=="leave"))).all()
                assert len(events[-1].after["entry_ids"])==2
                bill=await session.scalar(select(Charge).where(Charge.person_id==person_id))
                assert bill.status=="cancelled" and bill.paid_at==paid_at
            assert (await client.post(f"/api/me/games/{game_id}/join")).status_code==200
            async with factory() as session:
                assert len(await d.active_entries(session,game_id))==1
                bills=(await session.scalars(select(Charge).where(Charge.person_id==person_id))).all()
                assert len(bills)==1 and bills[0].status=="paid" and bills[0].paid_at==paid_at
                assert len((await session.scalars(select(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.person_id==person_id))).all())==3
                game=await session.get(WeeklyAttendance,game_id)
                person=await d.person_for_name(session,"Player")
                earlier=await d.person_for_name(session,"Earlier")
                game.capacity=2
                session.add(WeeklyAttendanceEntry(attendance_id=game.id,person_id=earlier.id,name=earlier.name,normalized_name=earlier.normalized_name,source_section="main",source_position=20,display_order=20,status="main",is_monthly_subscriber=False,owes_single_payment=False,joined_at=d.now()-timedelta(days=1)))
                await session.flush()
                await d.recalculate(session,game,at=d.now())
                game.capacity=1
                await d.recalculate(session,game,at=d.now())
                mine=next(e for e in await d.active_entries(session,game.id) if e.person_id==person_id)
                assert mine.status=="main" and bills[0].status=="paid"
                assert bills[0].paid_at==paid_at
                game.capacity=2
                await d.recalculate(session,game,at=d.now())
                assert mine.status=="main" and bills[0].status=="paid" and bills[0].paid_at==paid_at
                monthly=await d.monthly_upsert(session,person,game.game_date.month,game.game_date.year,has_paid=True)
                assert bills[0].status=="cancelled" and bills[0].paid_at==paid_at
                await d.monthly_remove(session,monthly)
                assert bills[0].status=="paid" and bills[0].paid_at==paid_at
                assert len((await session.scalars(select(Charge).where(Charge.person_id==person_id,Charge.type=="single"))).all())==1
                await session.rollback()
        await engine.dispose()
    asyncio.run(scenario())


def test_payment_waiver_transitions_visibility_and_preservation():
    """Run only against an isolated database via docker/test.sh."""
    async def scenario():
        assert URL and "fred_test" in URL
        engine=create_async_engine(URL)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE people,fred_accounts,monthly_subscribers,weekly_attendances,charges,audit_events,entity_revisions RESTART IDENTITY CASCADE"))
        admin={"uid":"e"*64,"username":"pyu","name":"Manager","email":"manager@example.com","is_admin":True}
        player={"uid":"f"*64,"username":"waiver-player","name":"Player","email":"player@example.com","is_admin":False}
        identity=admin
        app=FastAPI()
        app.include_router(router)
        async def actor(): return identity
        async def sessions():
            async with factory() as session: yield session
        app.dependency_overrides[current_user]=actor
        app.dependency_overrides[get_session]=sessions
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            async def request(method,path,**kwargs):
                response=await client.request(method,path,**kwargs)
                assert response.status_code<400,(method,path,response.status_code,response.text)
                return response.json()
            person=await request("POST","/api/people",json={"name":"Player"})
            identity=player
            await request("GET","/api/me")
            identity=admin
            await request("PATCH",f"/api/accounts/{player['uid']}",json={"person_id":person["id"]})
            month,year=11,2026
            await request("POST","/api/monthly",json={"person_id":person["id"],"month":month,"year":year})
            item=(await request("GET",f"/api/monthly?month={month}&year={year}"))["items"][0]
            monthly_id,charge_id=item["id"],item["charge_id"]
            for reason in ("","   "):
                response=await client.patch(f"/api/charges/{charge_id}",json={"status":"waived","reason":reason})
                assert response.status_code==422
            identity=player
            assert (await client.patch(f"/api/charges/{charge_id}",json={"status":"waived","reason":"Not authorized"})).status_code==403
            identity=admin
            await request("PATCH",f"/api/charges/{charge_id}",json={"status":"waived","reason":"Dispensa autorizada pelo gestor"})
            item=(await request("GET",f"/api/monthly?month={month}&year={year}"))["items"][0]
            assert item["charge_status"]=="waived" and item["has_paid"] is False
            assert (await request("GET","/api/charges?status=waived"))["items"][0]["status"]=="waived"
            assert (await request("GET","/api/charges?status=paid"))["total_cents"]==0
            assert (await request("GET","/api/debtors"))["total_cents"]==0
            # Non-financial editing must not turn an exemption back into a debt.
            await request("PATCH",f"/api/monthly/{monthly_id}",json={"position":2})
            assert (await request("GET",f"/api/monthly?month={month}&year={year}"))["items"][0]["charge_status"]=="waived"
            assert (await request("GET","/api/debtors"))["total_cents"]==0
            identity=player
            mine=await request("GET","/api/me")
            assert mine["monthly"][0]["charge_status"]=="waived"
            assert mine["charges"][0]["status"]=="waived"
            identity=admin
            events=(await request("GET","/api/audit"))["items"]
            waived=next(e for e in events if e["entity_type"]=="charge" and e["after"].get("status")=="waived")
            assert waived["before"]["status"]=="pending" and waived["after"]["reason"]=="Dispensa autorizada pelo gestor"
            # Explicit reactivation and payment are separate administrative operations.
            await request("PATCH",f"/api/charges/{charge_id}",json={"status":"pending","reason":"Reativação explícita"})
            assert (await request("GET","/api/debtors"))["total_cents"]==1250
            reactivation=next(e for e in (await request("GET","/api/audit"))["items"] if e["entity_type"]=="charge" and e["before"].get("status")=="waived" and e["after"].get("status")=="pending")
            assert reactivation["actor_uid"]==admin["uid"] and reactivation["after"]["reason"]=="Reativação explícita"
            await request("PATCH",f"/api/charges/{charge_id}",json={"status":"paid"})
            assert (await client.patch(f"/api/charges/{charge_id}",json={"status":"waived","reason":"Must undo payment first"})).status_code==409
            paid=(await request("GET","/api/charges?status=paid"))["items"][0]
            assert paid["status"]=="paid" and paid["paid_at"] is not None
            await request("PATCH",f"/api/charges/{charge_id}",json={"status":"pending","reason":"Desfazer confirmação de pagamento"})
            await request("PATCH",f"/api/charges/{charge_id}",json={"status":"waived","reason":"Nova dispensa"})
        async with factory() as session:
            from app.models import Person
            p=await session.get(Person,person["id"])
            # Existing MCP reads also distinguish waived from unpaid.
            import app.mcp_server as mcp
            original_factory=mcp.SessionLocal
            mcp.SessionLocal=factory
            try:
                subscribers=await mcp.get_monthly_subscribers(month=month,year=year)
                assert subscribers.subscribers[0].charge_status=="waived"
                assert not (await mcp.search_person("Player",unpaid_only=True)).matches
                summary=await mcp.get_person_payment_summary("Player",date(year,month,1),date(year,month,30))
                assert summary.total_unpaid_cents==0
            finally:
                mcp.SessionLocal=original_factory
            # Timestamp arbitration: old messages preserve waiver; newer explicit
            # monthly payment status remains authoritative by the approved rule.
            await d.monthly_upsert(session,p,month,year,has_paid=False,at=d.now()-timedelta(days=1),source="whatsapp")
            c=await session.get(Charge,charge_id)
            assert c.status=="waived"
            await d.monthly_upsert(session,p,month,year,has_paid=False,at=d.now()+timedelta(seconds=1),source="whatsapp")
            assert c.status=="pending"
            # Avulso exemption survives removal, reentry, capacity changes and becoming monthly.
            guest=await d.person_for_name(session,"Guest")
            future_date=date.today()+timedelta(days=7)
            future_date+=timedelta(days=(2-future_date.weekday())%7)
            game=WeeklyAttendance(game_date=future_date,capacity=1,cutoff_at=d.now()-timedelta(hours=1),starts_at=datetime.combine(future_date,time(19,30),d.TZ))
            session.add(game)
            await session.flush()
            entry=await d.add_entry(session,game,guest,user=admin)
            avulso=await d.set_charge(session,guest.id,"single",game.game_date,status="waived",user=admin,reason="Convidado dispensado")
            assert entry.status=="main" and avulso.status=="waived"
            await d.recalculate(session,game,at=d.now())
            assert avulso.status=="waived" and not entry.owes_single_payment
            await d.remove_entry(session,game,entry,user=player,source="self_service",all_for_person=True)
            assert avulso.status=="waived"
            entry=await d.add_entry(session,game,guest,user=player,source="self_service")
            assert avulso.status=="waived" and entry.status=="main"
            earlier=await d.person_for_name(session,"Earlier Guest")
            game.capacity=2
            earlier_entry=await d.add_entry(session,game,earlier,user=admin)
            earlier_entry.joined_at=d.now()-timedelta(days=1)
            game.capacity=1
            await d.recalculate(session,game,at=d.now())
            assert entry.status=="main" and avulso.status=="waived"
            game.capacity=2
            await d.recalculate(session,game,at=d.now())
            assert entry.status=="main" and avulso.status=="waived"
            monthly=await d.monthly_upsert(session,guest,game.game_date.month,game.game_date.year)
            assert avulso.status=="waived"
            await d.monthly_remove(session,monthly)
            assert avulso.status=="waived"
            # A newer attendance snapshot contains no explicit payment instruction.
            parsed=parse_weekly_attendance_message(f"LISTA VOLEI FREDERICO {future_date:%d/%m/%Y}\n1. Guest\n2. Earlier Guest",received_at=d.now())
            await apply_weekly_attendance(session,parsed=parsed,received_at=d.now(),commit=False)
            assert avulso.status=="waived"
            assert len((await session.scalars(select(Charge).where(Charge.person_id==guest.id,Charge.type=="single"))).all())==1
            await session.rollback()
        await engine.dispose()
    asyncio.run(scenario())
