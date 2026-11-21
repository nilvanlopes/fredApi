import asyncio
from datetime import datetime, timedelta
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import management as d
from app.admin_api import charge_items
from app.aliases import create_alias
from app.main import process_monthly_message, process_weekly_message
from app.models import Charge, MonthlySubscriber, Person, ProcessedConversationMessage, WeeklyAttendanceEntry
from app.message_templates import render_weekly_attendance_message
from app.schemas import ProcessMessageRequest


TEST_DATABASE = os.getenv("FRED_TEST_DATABASE_URL")


def _canonical_weekly_message(response, *, paid_names=()):
    entries = sorted(response.entries, key=lambda entry: (entry.section != "main", entry.position))
    render_entries = [SimpleNamespace(
        name=entry.name,
        invited_by=entry.invited_by,
        status="main" if entry.section == "main" else "waiting",
        prebuilt_team_number=entry.prebuilt_team_number,
        person_id=entry.name,
    ) for entry in entries]
    return render_weekly_attendance_message(
        response.game_date, render_entries, paid_person_ids=set(paid_names),
    )


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_live_weekly_snapshot_removal_returns_complete_database_list(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))
        game_time = datetime(2026, 11, 18, 17, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)

        def payload(body, provider, minutes):
            return ProcessMessageRequest(
                text=body, received_at=game_time + timedelta(minutes=minutes), source="waha",
                chat_id=group, message_id=f"false_{group}_{provider}_sender@lid",
                sender_id="sender@lid", sender_name="Contato",
            )

        async with factory() as session:
            first_text = "LISTA VÔLEI FREDERICO 18/11/2026\n1. Alice\n2. Bruno\n\nConvidados\n1. Caio (conv. Alice)"
            seeded = await process_weekly_message(payload(first_text, "seed", 0), session)
            assert seeded.correction_text is None
            second_text = "LISTA VÔLEI FREDERICO 18/11/2026\n1. Alice\n\nConvidados\n1. Caio (conv. Alice)"
            updated = await process_weekly_message(payload(second_text, "remove-bruno", 1), session)
            expected = _canonical_weekly_message(updated)
            assert {item.name for item in updated.entries} == {"Alice", "Caio"}
            assert updated.correction_text == expected
            assert "Convidados\n1. Caio (conv. Alice)" in updated.correction_text
            assert "Bruno" not in updated.correction_text
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_live_weekly_snapshot_compacts_positions_and_returns_reindexed_list(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))
        game_time = datetime(2026, 11, 18, 17, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)

        def payload(body, provider, minutes):
            return ProcessMessageRequest(
                text=body, received_at=game_time + timedelta(minutes=minutes), source="waha",
                chat_id=group, message_id=f"false_{group}_{provider}_sender@lid",
                sender_id="sender@lid", sender_name="Contato",
            )

        async with factory() as session:
            initial = (
                "LISTA VÔLEI FREDERICO 18/11/2026\n1. Alice\n2. Bruno\n"
                "\nConvidados\n1. Caio (conv. Alice)\n2. Davi (conv. Alice)"
            )
            seeded = await process_weekly_message(payload(initial, "seed-gaps", 0), session)
            assert seeded.correction_text is None
            incoming = (
                "LISTA VÔLEI FREDERICO 18/11/2026\n1. Alice\n3. Bruno\n"
                "\nConvidados\n1. Caio (conv. Alice)\n3. Davi (conv. Alice)"
            )
            updated = await process_weekly_message(payload(incoming, "with-gaps", 1), session)
            rows = (await session.scalars(select(WeeklyAttendanceEntry).where(
                WeeklyAttendanceEntry.deleted_at.is_(None),
            ).order_by(WeeklyAttendanceEntry.source_section, WeeklyAttendanceEntry.source_position))).all()
            positions = {
                section: [row.source_position for row in rows if row.source_section == section]
                for section in ("main", "guests")
            }
            assert positions == {"main": [1, 2], "guests": [1, 2]}
            expected = _canonical_weekly_message(updated)
            assert updated.correction_text == expected
            assert "Convidados\n1. Caio (conv. Alice)\n2. Davi (conv. Alice)" in updated.correction_text
            assert "2. Bruno" in updated.correction_text
            assert "2. Davi" in updated.correction_text
            assert [(entry.section, entry.position) for entry in updated.entries] == [
                ("main", 1), ("main", 2), ("guests", 1), ("guests", 2),
            ]
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_live_weekly_snapshot_corrects_duplicate_positions_in_both_sections(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))
        game_time = datetime(2026, 11, 18, 17, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)
        incoming = (
            "LISTA VÔLEI FREDERICO 18/11/2026\n1. Alice\n2. Bruno\n2. Carol\n"
            "\nConvidados\n1. Davi (conv. Alice)\n2. Eva (conv. Alice)\n"
            "2. Fabio (conv. Alice)"
        )
        payload = ProcessMessageRequest(
            text=incoming, received_at=game_time, source="waha", chat_id=group,
            message_id=f"false_{group}_duplicate-positions_sender@lid", sender_id="sender@lid",
        )

        async with factory() as session:
            updated = await process_weekly_message(payload, session)
            rows = (await session.scalars(select(WeeklyAttendanceEntry).where(
                WeeklyAttendanceEntry.deleted_at.is_(None),
            ).order_by(WeeklyAttendanceEntry.source_section, WeeklyAttendanceEntry.source_position))).all()
            positions = {
                section: [row.source_position for row in rows if row.source_section == section]
                for section in ("main", "guests")
            }
            assert positions == {"main": [1, 2, 3], "guests": [1, 2, 3]}
            assert [(entry.section, entry.position) for entry in updated.entries] == [
                ("main", 1), ("main", 2), ("main", 3),
                ("guests", 1), ("guests", 2), ("guests", 3),
            ]
            expected = _canonical_weekly_message(updated)
            assert updated.correction_text == expected
            assert (
                "Convidados\n1. Davi (conv. Alice)\n2. Eva (conv. Alice)\n3. Fabio (conv. Alice)"
                in updated.correction_text
            )
            assert "3. Carol" in updated.correction_text
            assert "3. Fabio" in updated.correction_text
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_live_whatsapp_adds_inviter_only_to_new_guests_and_keeps_received_text(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))

        game_time = datetime(2026, 11, 18, 17, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)
        original = (
            "*LISTA VÔLEI FREDERICO 18/11/2026*\r\n"
            "1. Maria da Silva\r\n2. Paulo\r\n\r\nConvidados\r\n"
            "1. Antes\r\n2. Ana (conv.Paulo)\r\n3. Sozinho (conv)\r\n"
        )

        def payload(body, provider, minutes, *, contact="Maria WhatsApp"):
            return ProcessMessageRequest(
                text=body, received_at=game_time + timedelta(minutes=minutes), source="waha",
                chat_id=group, message_id=f"false_{group}_{provider}_12345@lid",
                sender_id="12345@lid", sender_name="Nome público", sender_contact_name=contact,
            )

        async with factory() as session:
            seed = await process_weekly_message(payload(original, "seed", 0), session)
            assert seed.correction_text is None
            await create_alias(session, alias="Maria WhatsApp", canonical_name="Maria da Silva")
            await session.commit()

            raw = original.replace("2. Paulo\r\n", "2. Paulo\r\n3. Marca (convidado)\r\n")
            raw += "4) Novo*✅ 2️⃣\r\n5. Repetido\r\n6. Repetido\r\n"
            first = payload(raw, "first", 1)
            updated = await process_weekly_message(first, session)
            assert updated.correction_text == _canonical_weekly_message(updated, paid_names={"Novo"})
            assert "Convidados\n" in updated.correction_text
            assert "Novo (conv. Maria WhatsApp) 2️⃣ ✅" in updated.correction_text
            assert updated.correction_notice is None
            by_name = {entry.name: entry for entry in updated.entries}
            assert by_name["Marca"].invited_by is None
            assert by_name["Antes"].invited_by is None
            assert by_name["Ana"].invited_by == "Paulo"
            assert by_name["Sozinho"].invited_by == "Sozinho"
            assert by_name["Repetido"].invited_by is None
            assert by_name["Novo"].invited_by == "Maria WhatsApp"
            assert by_name["Novo"].prebuilt_team_number == 2
            processed = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == first.message_id
            ))
            assert processed.raw_text == raw
            assert processed.sender_name == "Nome público"
            assert "correction_text" not in processed.result
            assert (await process_weekly_message(first, session)).correction_text is None

            charges = (await session.execute(select(Charge, Person.name).join(Person))).all()
            debtor = next(item for item in await charge_items(session, charges) if item["name"] == "Novo")
            assert debtor["debtor_name"] == "Maria da Silva"

            copied = original + "4) Novo*✅ 2️⃣\r\n5. Outra\r\n"
            later = await process_weekly_message(payload(copied, "later", 2, contact="Contato sem cadastro"), session)
            expected_later = _canonical_weekly_message(later, paid_names={"Novo"})
            assert later.correction_text == expected_later
            assert next(entry for entry in later.entries if entry.name == "Novo").invited_by == "Maria WhatsApp"
            assert next(entry for entry in later.entries if entry.name == "Outra").invited_by == "Contato sem cadastro"
            assert await session.scalar(select(Person).where(Person.normalized_name == "contato sem cadastro")) is None

            stale = payload(original + "4. Antigo\r\n", "stale", 1)
            ignored = await process_weekly_message(stale, session)
            assert ignored.correction_text is None
            assert {entry.name for entry in ignored.entries} == {entry.name for entry in later.entries}
            stored_stale = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == stale.message_id
            ))
            assert stored_stale.status == "stale" and stored_stale.raw_text == stale.text

            unsafe_contact = payload(copied + "6. Sem contato\r\n", "no-contact", 3, contact="Ana\n7. Outro")
            fixed = await process_weekly_message(unsafe_contact, session)
            assert fixed.correction_text is None
            assert next(entry for entry in fixed.entries if entry.name == "Sem contato").invited_by is None
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_live_whatsapp_moves_self_signed_non_subscriber_to_end_of_guests(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))

        game_time = datetime(2026, 11, 18, 15, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)
        original = (
            "*LISTA VÔLEI FREDERICO 18/11/2026*\r\n"
            "1. Maria\r\n2. Paulo\r\n3. \r\n4. Nome antigo\r\n\r\nConvidados:\r\n"
            "1. Ana (conv. Paulo)\r\n2) Beto\r\n3) \r\n"
        )

        def payload(body, provider, minutes, contact):
            return ProcessMessageRequest(
                text=body, received_at=game_time + timedelta(minutes=minutes), source="waha",
                chat_id=group, message_id=f"false_{group}_{provider}_12345@lid",
                sender_id="12345@lid", sender_contact_name=contact,
            )

        async with factory() as session:
            await process_monthly_message(ProcessMessageRequest(
                text="LISTA DE ASSINANTES DO MÊS DE NOVEMBRO DE 2026\n1. Maria ✅\n2. Joana",
                received_at=game_time - timedelta(minutes=1),
            ), session)
            await create_alias(session, alias="Nina WhatsApp", canonical_name="Nina")
            await session.commit()
            seed = await process_weekly_message(payload(original, "seed", 0, "Maria"), session)
            assert seed.correction_text == _canonical_weekly_message(seed)
            assert "Convidados\n1. Ana (conv. Paulo)\n2. Beto" in seed.correction_text
            assert seed.correction_notice is None
            assert {entry.name for entry in seed.entries if entry.section == "main"} == {
                "Maria", "Paulo", "Nome antigo",
            }

            raw = original.replace("3. \r\n", "3. Nina*✅ 2️⃣\r\n").replace(
                "4. Nome antigo\r\n", "4. Nome antigo\r\n5. Outra\r\n",
            )
            incoming = payload(raw, "self-signed", 1, "Nina WhatsApp")
            corrected = await process_weekly_message(incoming, session)
            assert corrected.correction_notice == (
                "Nina não está na lista de assinantes, movendo para a lista de convidados.\n"
                "Outra não está na lista de assinantes, movendo para a lista de convidados."
            )
            assert corrected.correction_text == _canonical_weekly_message(corrected, paid_names={"Nina"})
            assert "Convidados\n1. Ana (conv. Paulo)\n2. Beto\n3. Nina (conv) 2️⃣ ✅" in corrected.correction_text
            by_name = {entry.name: entry for entry in corrected.entries}
            assert (by_name["Nina"].section, by_name["Nina"].position, by_name["Nina"].invited_by) == ("guests", 3, "Nina")
            assert by_name["Nina"].status == "waiting" and not by_name["Nina"].is_monthly_subscriber
            assert by_name["Nina"].prebuilt_team_number == 2
            assert (by_name["Outra"].section, by_name["Outra"].position) == ("guests", 4)
            assert by_name["Outra"].invited_by == "Nina WhatsApp"
            assert by_name["Nome antigo"].position == 3
            assert by_name["Ana"].invited_by == "Paulo"
            stored = await session.scalar(select(ProcessedConversationMessage).where(
                ProcessedConversationMessage.provider_message_id == incoming.message_id,
            ))
            assert stored.raw_text == raw
            assert (await process_weekly_message(incoming, session)).correction_text is None

            subscriber = corrected.correction_text.replace(
                "3. Nome antigo\n\nConvidados",
                "3. Nome antigo\n4. Joana\n\nConvidados",
            )
            accepted = await process_weekly_message(payload(subscriber, "subscriber", 2, "Joana"), session)
            assert accepted.correction_text is None
            assert accepted.correction_notice is None
            joana = next(entry for entry in accepted.entries if entry.name == "Joana")
            assert joana.section == "main"

            guest_in_main = subscriber.replace(
                "4. Joana\n\nConvidados",
                "4. Joana\n5. Ana\n\nConvidados",
            ).replace("1. Ana (conv. Paulo)\n", "")
            returned = await process_weekly_message(payload(guest_in_main, "moved-guest", 3, "Ana"), session)
            assert returned.correction_notice == (
                "Ana não está na lista de assinantes, movendo para a lista de convidados."
            )
            assert returned.correction_text == _canonical_weekly_message(returned, paid_names={"Nina"})
            ana = next(entry for entry in returned.entries if entry.name == "Ana")
            assert (ana.section, ana.position, ana.invited_by) == ("guests", 4, "Paulo")

            first_list = "LISTA VÔLEI FREDERICO 25/11/2026\n1) Nova"
            first = await process_weekly_message(payload(first_list, "first-list", 4, "Nova"), session)
            assert first.correction_text is None
            assert first.correction_notice is None
            assert [(entry.section, entry.position) for entry in first.entries] == [("main", 1)]
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_live_whatsapp_moves_new_non_subscriber_added_by_subscriber(monkeypatch):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))

        game_time = datetime(2026, 11, 18, 15, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)
        original = "*LISTA VÔLEI FREDERICO 18/11/2026*\n1. Maria\n"

        def payload(body, provider, minutes):
            return ProcessMessageRequest(
                text=body, received_at=game_time + timedelta(minutes=minutes), source="waha",
                chat_id=group, message_id=f"false_{group}_{provider}_12345@lid",
                sender_id="12345@lid", sender_contact_name="Maria",
            )

        async with factory() as session:
            await process_monthly_message(ProcessMessageRequest(
                text="LISTA DE ASSINANTES DO MÊS DE NOVEMBRO DE 2026\n1. Maria ✅\n2. Joana",
                received_at=game_time - timedelta(minutes=1),
            ), session)
            await process_weekly_message(payload(original, "seed-new", 0), session)
            raw = original + "2. Joana\n3. Beltrano\n4. Outra Pessoa\n"
            corrected = await process_weekly_message(payload(raw, "added-new", 1), session)
            assert corrected.correction_text == _canonical_weekly_message(corrected)
            assert corrected.correction_notice == (
                "Beltrano não está na lista de assinantes, movendo para a lista de convidados.\n"
                "Outra Pessoa não está na lista de assinantes, movendo para a lista de convidados."
            )
            by_name = {entry.name: entry for entry in corrected.entries}
            assert by_name["Joana"].section == "main"
            assert "Joana não está na lista de assinantes" not in corrected.correction_notice
            joana_subscription = await session.scalar(select(MonthlySubscriber).where(
                MonthlySubscriber.normalized_name == "joana",
                MonthlySubscriber.month == 11,
                MonthlySubscriber.year == 2026,
                MonthlySubscriber.deleted_at.is_(None),
            ))
            assert joana_subscription is not None and not joana_subscription.has_paid
            assert (by_name["Beltrano"].section, by_name["Beltrano"].position) == ("guests", 1)
            assert by_name["Beltrano"].invited_by == "Maria"
            assert by_name["Outra Pessoa"].invited_by == "Maria"
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "hour, candidate_position, expected_section, sender_contact, keep_all_existing",
    [
        (15, 13, "guests", "Contato", False),
        (15, 25, "guests", "Contato", False),
        (18, 13, "main", "Contato", False),
        (18, 13, "main", "Magalhães", False),
        (18, 13, "guests", "Contato", True),
        (18, 25, "guests", "Contato", False),
    ],
)
@pytest.mark.skipif(not TEST_DATABASE, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")
def test_new_non_subscribers_are_marked_or_moved_by_cutoff_and_capacity(
    monkeypatch, hour, candidate_position, expected_section, sender_contact, keep_all_existing,
):
    async def scenario():
        assert TEST_DATABASE and "fred_test" in TEST_DATABASE
        engine = create_async_engine(TEST_DATABASE)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text(
                "TRUNCATE processed_conversation_messages, people, person_aliases, monthly_subscribers, "
                "weekly_attendances, weekly_attendance_entries, charges, audit_events, entity_revisions "
                "RESTART IDENTITY CASCADE"
            ))

        game_time = datetime(2026, 11, 18, hour, 40, tzinfo=d.TZ)
        monkeypatch.setattr(d, "now", lambda: game_time)
        group = "120363000000000000@g.us"
        monkeypatch.setenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", group)

        def payload(body, provider, minutes):
            return ProcessMessageRequest(
                text=body, received_at=game_time + timedelta(minutes=minutes), source="waha",
                chat_id=group, message_id=f"false_{group}_{provider}_12345@lid",
                sender_id="12345@lid", sender_contact_name=sender_contact,
            )

        initial_names = [f"Pessoa {i}" for i in range(1, 25)]
        initial_names[12] = "Allan"
        initial = "LISTA VÔLEI FREDERICO 18/11/2026\n" + "".join(
            f"{position}. {name}\n" for position, name in enumerate(initial_names, 1)
        )
        if candidate_position <= 24 and not keep_all_existing:
            current_names = [name for name in initial_names if name != "Allan"]
            current_names.insert(candidate_position - 1, "Magalhães")
        elif candidate_position <= 24:
            current_names = list(initial_names)
            current_names.insert(candidate_position - 1, "Magalhães")
        else:
            current_names = initial_names + ["Magalhães"]
        incoming = "LISTA VÔLEI FREDERICO 18/11/2026\n" + "".join(
            f"{position}. {name}\n" for position, name in enumerate(current_names, 1)
        )

        async with factory() as session:
            await process_weekly_message(payload(initial, "seed-guests", 0), session)
            result = await process_weekly_message(payload(incoming, "guests", 1), session)
            candidate = next(entry for entry in result.entries if entry.name == "Magalhães")
            self_signed = sender_contact == "Magalhães"
            expected_inviter = sender_contact
            assert candidate.invited_by == expected_inviter
            assert candidate.section == expected_section
            if expected_section == "main":
                assert candidate.position == 24
                assert candidate.status == "main"
                assert result.correction_text is not None
                marker = "(conv)" if self_signed else f"(conv. {expected_inviter})"
                assert f"Magalhães {marker}" in result.correction_text
                assert result.correction_text.rstrip().endswith(f"24. Magalhães {marker}")
                if self_signed:
                    assert result.correction_notice == (
                        "Magalhães não está na lista de assinantes, identificando como convidado."
                    )
                else:
                    # An additional insertion after Magalhães must join the tail,
                    # so it cannot jump ahead of him even when submitted at position 13.
                    original_order = [entry.name for entry in result.entries if entry.section == "main"]
                    original_order.remove("Pessoa 1")
                    original_order.insert(12, "Luana")
                    later = "LISTA VÔLEI FREDERICO 18/11/2026\n" + "".join(
                        f"{position}. {name}\n" for position, name in enumerate(original_order, 1)
                    )
                    next_result = await process_weekly_message(
                        ProcessMessageRequest(
                            text=later, received_at=game_time + timedelta(minutes=2), source="waha",
                            chat_id=group, message_id=f"false_{group}_later_12345@lid",
                            sender_id="12345@lid", sender_contact_name="Hayanne",
                        ), session,
                    )
                    by_name = {entry.name: entry for entry in next_result.entries}
                    assert (by_name["Magalhães"].section, by_name["Magalhães"].position) == ("main", 23)
                    assert (by_name["Luana"].section, by_name["Luana"].position) == ("main", 24)
                    assert "23. Magalhães (conv. Contato)\n24. Luana (conv. Hayanne)" in next_result.correction_text
            else:
                assert candidate.position == 1
                assert result.correction_notice == (
                    "Magalhães não está na lista de assinantes, movendo para a lista de convidados."
                )
                assert result.correction_text == _canonical_weekly_message(result)
        await engine.dispose()

    asyncio.run(scenario())
