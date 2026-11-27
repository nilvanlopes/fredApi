"""Player profile and rating integration checks; opt in with FRED_TEST_DATABASE_URL."""
import asyncio
import os
from datetime import date, datetime, time, timezone

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import management as d
from app.auth import current_user
from app.database import get_session
from app.models import (
    Charge, FredAccount, MonthlySubscriber, Person, PersonAlias, PersonProfile, PlayerRating,
    WeeklyAttendance, WeeklyAttendanceEntry,
)
from app.player_profiles import router

URL = os.getenv("FRED_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL FRED_TEST_DATABASE_URL")


def test_public_profiles_are_separate_from_history_and_ratings_are_private_upserts():
    async def scenario():
        assert URL and "fred_test" in URL, "Tests must use a dedicated fred_test database"
        engine = create_async_engine(URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        # 01:00 UTC on Nov 1 is still Oct 31 in Brasília: October is current.
        now = datetime(2030, 11, 1, 1, tzinfo=timezone.utc)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(d, "now", lambda: now)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE person_aliases, people, fred_accounts, weekly_attendances RESTART IDENTITY CASCADE"))

        owner_user = {"uid": "d" * 64, "username": "owner", "name": "Titular", "email": "", "is_admin": False}
        rival_user = {"uid": "e" * 64, "username": "rival", "name": "Rival", "email": "", "is_admin": False}
        identity = owner_user
        async with factory.begin() as session:
            owner = Person(name="Titular", normalized_name="titular", active=True)
            rival = Person(name="Rival", normalized_name="rival", active=True)
            history_alias = PersonAlias(alias="Nome de lista", alias_normalized="nome de lista",
                                        canonical_name="Titular", canonical_normalized="titular")
            session.add_all([owner, rival, history_alias])
            await session.flush()
            session.add_all([
                FredAccount(uid=owner_user["uid"], username="owner", name="Titular", email="", is_admin=False, person_id=owner.id),
                FredAccount(uid=rival_user["uid"], username="rival", name="Rival", email="", is_admin=False, person_id=rival.id),
                PersonProfile(person_id=owner.id, nicknames=["Tita"], positions=["ponta"], primary_position="ponta"),
                MonthlySubscriber(person_id=owner.id, name=owner.name, normalized_name=owner.normalized_name,
                                  month=10, year=2030, position=1, has_paid=False),
                Charge(person_id=rival.id, type="monthly", reference_date=date(2030, 10, 1),
                       amount_cents=1250, status="paid", paid_at=now),
                MonthlySubscriber(person_id=rival.id, name=rival.name, normalized_name=rival.normalized_name,
                                  month=9, year=2030, position=1),
                MonthlySubscriber(person_id=rival.id, name=rival.name, normalized_name=rival.normalized_name,
                                  month=11, year=2030, position=1),
                MonthlySubscriber(person_id=rival.id, name=rival.name, normalized_name=rival.normalized_name,
                                  month=10, year=2030, position=1, deleted_at=now),
            ])
            games = []
            for game_date, starts_at in (
                (date(2030, 10, 30), datetime(2030, 10, 30, 19, 30, tzinfo=d.TZ)),
                (date(2030, 11, 6), datetime(2030, 11, 6, 20, 30, tzinfo=d.TZ)),
                (date(2030, 10, 23), datetime(2030, 10, 23, 19, 30, tzinfo=d.TZ)),
            ):
                game = WeeklyAttendance(
                    game_date=game_date, capacity=12,
                    cutoff_at=datetime.combine(game_date, time(16), d.TZ), starts_at=starts_at,
                )
                session.add(game)
                games.append(game)
            await session.flush()
            past, future, guest_game = games
            session.add_all([
                WeeklyAttendanceEntry(attendance_id=past.id, person_id=owner.id,
                    source_section="main", source_position=1, display_order=1, name="Titular",
                    normalized_name="titular", status="main"),
                # A second main row for this person still contributes only one game.
                WeeklyAttendanceEntry(attendance_id=past.id, person_id=owner.id,
                    source_section="main", source_position=2, display_order=2, name="Tita",
                    normalized_name="tita", status="main"),
                WeeklyAttendanceEntry(attendance_id=past.id, person_id=owner.id,
                    source_section="guests", source_position=3, display_order=3, name="Convidada",
                    normalized_name="convidada", status="main"),
                WeeklyAttendanceEntry(attendance_id=future.id, person_id=owner.id,
                    source_section="main", source_position=1, display_order=1, name="Titular",
                    normalized_name="titular", status="main"),
                WeeklyAttendanceEntry(attendance_id=future.id, person_id=owner.id,
                    source_section="main", source_position=2, display_order=2, name="Espera",
                    normalized_name="espera", status="waiting"),
                WeeklyAttendanceEntry(attendance_id=guest_game.id, person_id=owner.id,
                    source_section="guests", source_position=1, display_order=1, name="Titular convidada",
                    normalized_name="titular convidada", status="main"),
            ])
            owner_id, rival_id = owner.id, rival.id

        app = FastAPI()
        app.include_router(router)

        async def actor():
            return identity

        async def session_dependency():
            async with factory() as session:
                yield session

        app.dependency_overrides.update({current_user: actor, get_session: session_dependency})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            public = await client.get(f"/api/public/profiles/{owner_id}")
            assert public.status_code == 200
            assert public.json()["name"] == "Titular"
            assert public.json()["is_subscriber"] is True
            assert public.json()["nicknames"] == ["Tita"]
            assert "Nome de lista" not in public.text
            assert public.json()["games_count"] == 2
            assert public.json()["rating_average"] is None
            assert public.json()["rating_count"] == 0
            assert not ({"email", "charges", "publish_identity", "evaluator_person_id"} & public.json().keys())
            paid_rival = await client.get(f"/api/public/profiles/{rival_id}")
            assert paid_rival.json()["is_subscriber"] is False

            app.dependency_overrides.pop(current_user)
            assert (await client.get(f"/api/public/profiles/{owner_id}")).status_code == 200
            assert (await client.get("/api/me/profile")).status_code == 401
            assert (await client.patch("/api/me/profile", json={"bio": "forged"})).status_code == 401
            assert (await client.put(f"/api/me/ratings/{rival_id}", json={"stars": 4})).status_code == 401
            app.dependency_overrides[current_user] = actor
            identity = {"uid": "f" * 64, "username": "unlinked", "name": "Unlinked", "is_admin": False}
            assert (await client.get("/api/me/profile")).status_code == 403
            assert (await client.put(f"/api/me/ratings/{rival_id}", json={"stars": 4})).status_code == 403
            identity = owner_user

            current = await client.get("/api/me/profile")
            assert current.status_code == 200 and current.json()["person_id"] == str(owner_id)
            assert current.json()["is_subscriber"] is True
            changed = await client.patch("/api/me/profile", json={
                "bio": "Jogo na ponta", "positions": ["ponta", "oposto"],
                "primary_position": "oposto", "sex": "feminino", "handedness": "canhoto",
                "skills": {"passe": 80, "ataque": 75, "defesa": 70, "bloqueio": 65, "saque": 90},
            })
            assert changed.status_code == 200, changed.text
            assert changed.json()["skills"]["saque"] == 90
            assert changed.json()["primary_position"] == "oposto"
            renamed = await client.patch("/api/me/profile", json={"nicknames": ["  Nova   Tita  "]})
            assert renamed.status_code == 200
            assert renamed.json()["nicknames"] == ["Nova Tita"]
            async with factory() as session:
                assert await session.scalar(select(PersonAlias.alias)) == "Nome de lista"
                historical_names = (await session.scalars(select(WeeklyAttendanceEntry.name))).all()
                assert "Tita" in historical_names
                assert "Nova Tita" not in historical_names
                assert await session.get(PersonProfile, rival_id) is None
            assert (await client.patch("/api/me/profile", json={"email": "private@example.test"})).status_code == 422
            assert (await client.patch("/api/me/profile", json={"bio": "uma\nlinha"})).status_code == 422
            assert (await client.patch("/api/me/profile", json={
                "skills": {"passe": 80, "ataque": 75, "defesa": 70, "bloqueio": 65},
            })).status_code == 422
            assert (await client.patch("/api/me/profile", json={
                "skills": {"passe": True, "ataque": 75, "defesa": 70, "bloqueio": 65, "saque": 90},
            })).status_code == 422
            assert (await client.patch("/api/me/profile", json={
                "positions": [],
            })).status_code == 422
            assert (await client.patch("/api/me/profile", json={
                "positions": ["ponta"], "primary_position": None,
            })).status_code == 422
            assert (await client.patch("/api/me/profile", json={
                "positions": ["ponta"], "primary_position": "oposto",
            })).status_code == 422

            first = await client.put(f"/api/me/ratings/{rival_id}", json={"stars": 4})
            assert first.status_code == 200 and first.json()["publish_identity"] is False
            assert first.headers["cache-control"] == "private, no-store"
            replacement = await client.put(f"/api/me/ratings/{rival_id}", json={
                "stars": 2, "publish_identity": True,
            })
            assert replacement.status_code == 200
            own_rating = await client.get(f"/api/me/ratings/{rival_id}")
            assert own_rating.headers["cache-control"] == "private, no-store"
            assert own_rating.json()["stars"] == 2
            assert own_rating.json()["publish_identity"] is True
            assert own_rating.json()["rating_average"] == 2.0
            assert own_rating.json()["rating_count"] == 1
            assert (await client.put(f"/api/me/ratings/{owner_id}", json={"stars": 5})).status_code == 409
            assert (await client.put(f"/api/me/ratings/{rival_id}", json={"stars": 6})).status_code == 422
            public_target = await client.get(f"/api/public/profiles/{rival_id}")
            assert public_target.json()["rating_average"] == 2.0
            assert public_target.json()["rating_count"] == 1
            assert "publish_identity" not in public_target.json()
            assert "stars" not in public_target.json()

            identity = rival_user
            rival_view = await client.get(f"/api/me/ratings/{owner_id}")
            assert rival_view.json()["stars"] is None
            assert rival_view.json()["publish_identity"] is False

            identity = owner_user
            concurrent = await asyncio.gather(
                client.put(f"/api/me/ratings/{rival_id}", json={"stars": 3}),
                client.put(f"/api/me/ratings/{rival_id}", json={"stars": 5, "publish_identity": True}),
            )
            assert all(response.status_code == 200 for response in concurrent)
            assert all(response.headers["cache-control"] == "private, no-store" for response in concurrent)
            async with factory() as session:
                rows = (await session.scalars(select(PlayerRating).where(
                    PlayerRating.evaluator_person_id == owner_id,
                    PlayerRating.target_person_id == rival_id,
                ))).all()
                assert len(rows) == 1
                assert rows[0].stars in {3, 5}
                assert rows[0].created_at is not None
                assert rows[0].updated_at is not None
                assert await session.scalar(select(func.count()).select_from(PlayerRating)) == 1
                try:
                    await d.merge_people(session, owner_id, rival_id, user=owner_user)
                except HTTPException as exc:
                    assert exc.status_code == 409
                else:
                    raise AssertionError("A player with a profile or ratings must not be merged silently")
                await session.rollback()
            async with factory() as session:
                assert await session.get(Person, owner_id) is not None
                assert await session.get(Person, rival_id) is not None
                assert await session.get(PersonProfile, owner_id) is not None
                assert await session.scalar(select(PlayerRating.id).where(
                    PlayerRating.evaluator_person_id == owner_id,
                    PlayerRating.target_person_id == rival_id,
                )) is not None

        await engine.dispose()
        monkeypatch.undo()

    asyncio.run(scenario())
