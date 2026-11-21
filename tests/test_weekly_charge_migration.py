import asyncio
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import management as d
from app.models import AuditEvent, EntityRevision, WeeklyAttendance, WeeklyAttendanceEntry


URL = os.getenv("FRED_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")


def test_unify_weekly_charges_requires_proven_duplicate_and_preserves_audit():
    def migrate(connection, revision, direction):
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        module = ScriptDirectory.from_config(config).get_revision(revision).module
        with Operations.context(MigrationContext.configure(connection)):
            getattr(module, direction)()

    async def scenario():
        assert URL and "fred_test" in URL
        engine = create_async_engine(URL)
        try:
            async with engine.connect() as connection, connection.begin() as transaction:
                await connection.run_sync(migrate, "0013_drop_charge_type_check", "downgrade")
                await connection.run_sync(migrate, "0012_drop_guest_name", "downgrade")
                await connection.run_sync(migrate, "0011_unify_weekly_charges", "downgrade")
                async with AsyncSession(bind=connection) as session:
                    participant = await d.person_for_name(session, "Convidado da migração")
                    inviter = await d.person_for_name(session, "Convidante da migração")
                    game_date = date(2024, 11, 6)
                    starts = datetime(2024, 11, 6, 22, 30, tzinfo=timezone.utc)
                    game = WeeklyAttendance(game_date=game_date, capacity=24, cutoff_at=starts-timedelta(hours=3), starts_at=starts)
                    session.add(game)
                    await session.flush()
                    entry = WeeklyAttendanceEntry(
                        attendance_id=game.id, person_id=participant.id, name=participant.name,
                        normalized_name=participant.normalized_name, source_section="main",
                        source_position=99, display_order=99, status="main", is_monthly_subscriber=False,
                        owes_single_payment=False, invited_by=inviter.name,
                        normalized_invited_by=inviter.normalized_name,
                    )
                    session.add(entry)
                    single = await d.set_charge(session, participant.id, "single", game_date, occurred_at=starts)
                    single = await d.set_charge(
                        session, participant.id, "single", game_date, status="cancelled",
                        reason="Cancelamento independente", occurred_at=starts + timedelta(minutes=1),
                    )
                    single_id, legacy_id, person_id = single.id, uuid4(), participant.id
                    single_key = f"charge:{person_id}:single:{game_date}"
                    legacy_key = f"charge:{person_id}:guest:{game_date}"
                    legacy_revision = starts + timedelta(minutes=2)
                    session.add(EntityRevision(key=legacy_key, occurred_at=legacy_revision))
                    session.add(AuditEvent(
                        occurred_at=legacy_revision, actor_name="Gestor", source="panel", action="create",
                        entity_type="charge", entity_id=str(legacy_id), person_id=person_id,
                    ))
                    await session.flush()
                    entry_id = entry.id
                    await session.execute(text("""
                        INSERT INTO charges (id, person_id, type, reference_date, amount_cents, status, guest_name)
                        VALUES (:id, :person_id, 'guest', :game_date, 750, 'pending', 'Nome antigo')
                    """), {"id": legacy_id, "person_id": person_id, "game_date": game_date})
                    await session.commit()

                async with connection.begin_nested() as savepoint:
                    with pytest.raises(DBAPIError, match="exige revisão"):
                        await connection.run_sync(migrate, "0011_unify_weekly_charges", "upgrade")
                    await savepoint.rollback()
                assert await connection.scalar(
                    text("SELECT status FROM charges WHERE id = :id"), {"id": single_id}
                ) == "cancelled"

                await connection.execute(text("""
                    UPDATE audit_events
                    SET after = jsonb_set(after::jsonb, '{reason}', '"Convidado cobrado ao convidante Convidante"')
                    WHERE entity_id = :id AND action = 'update'
                """), {"id": str(single_id)})
                await connection.run_sync(migrate, "0011_unify_weekly_charges", "upgrade")
                await connection.run_sync(migrate, "0012_drop_guest_name", "upgrade")
                await connection.run_sync(migrate, "0013_drop_charge_type_check", "upgrade")
                assert not await connection.scalar(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'charges'
                          AND column_name = 'guest_name'
                    )
                """))
                assert not await connection.scalar(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'charges'::regclass AND conname = 'ck_charge_type'
                    )
                """))

                charges = (await connection.execute(text("""
                    SELECT id, type, status, amount_cents, paid_at FROM charges
                    WHERE person_id = :id AND reference_date = :game_date
                """), {"id": person_id, "game_date": game_date})).all()
                assert charges == [(single_id, "single", "pending", 750, None)]
                assert (await connection.execute(text("""
                    SELECT owes_single_payment, single_payment_amount_cents
                    FROM weekly_attendance_entries WHERE id = :id
                """), {"id": entry_id})).one() == (True, 750)
                assert await connection.scalar(
                    text("SELECT occurred_at FROM entity_revisions WHERE key = :key"), {"key": legacy_key}
                ) is None
                assert await connection.scalar(
                    text("SELECT occurred_at FROM entity_revisions WHERE key = :key"), {"key": single_key}
                ) == legacy_revision

                before, after = (await connection.execute(text("""
                    SELECT before, after FROM audit_events WHERE entity_id = :id AND source = 'migration'
                """), {"id": str(single_id)})).one()
                assert before["status"] == "cancelled"
                assert before["superseded_charge"]["id"] == str(legacy_id)
                assert before["superseded_charge"]["guest_name"] == "Nome antigo"
                assert after["status"] == "pending"
                assert after["superseded_charge_id"] == str(legacy_id)
                assert await connection.scalar(
                    text("SELECT COUNT(*) FROM audit_events WHERE entity_id = :id"), {"id": str(legacy_id)}
                ) == 1

                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(scenario())
