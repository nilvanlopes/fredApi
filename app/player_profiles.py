"""Public player profiles and private, editable player ratings."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import management as d
from app.admin_api import own_person
from app.auth import current_user
from app.database import get_session
from app.models import (
    MonthlySubscriber, Person, PersonProfile, PlayerRating,
    WeeklyAttendance, WeeklyAttendanceEntry,
)

router = APIRouter(prefix="/api")
POSITIONS = ("ponta", "levantador", "central", "oposto", "libero")


class SkillsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passe: int = Field(ge=0, le=100, strict=True)
    ataque: int = Field(ge=0, le=100, strict=True)
    defesa: int = Field(ge=0, le=100, strict=True)
    bloqueio: int = Field(ge=0, le=100, strict=True)
    saque: int = Field(ge=0, le=100, strict=True)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nicknames: list[str] | None = Field(default=None, max_length=10)
    bio: str | None = Field(default=None, max_length=140)
    positions: list[Literal["ponta", "levantador", "central", "oposto", "libero"]] | None = Field(default=None, max_length=5)
    primary_position: Literal["ponta", "levantador", "central", "oposto", "libero"] | None = None
    sex: Literal["masculino", "feminino"] | None = None
    handedness: Literal["destro", "canhoto", "ambidestro"] | None = None
    skills: SkillsInput | None = None

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, value):
        if value is not None and any(char in value for char in "\r\n"):
            raise ValueError("A frase não pode conter quebras de linha")
        return value

    @field_validator("nicknames")
    @classmethod
    def validate_nicknames(cls, value):
        if value is None:
            raise ValueError("A lista de apelidos não pode ser nula")
        cleaned = [" ".join(item.split()) for item in value]
        if any(not item or len(item) > 40 or "\n" in item or "\r" in item for item in cleaned):
            raise ValueError("Cada apelido deve ter de 1 a 40 caracteres, sem quebra de linha")
        if len({item.casefold() for item in cleaned}) != len(cleaned):
            raise ValueError("Os apelidos não podem se repetir")
        return cleaned

    @field_validator("positions")
    @classmethod
    def validate_positions(cls, value):
        if value is None:
            raise ValueError("A lista de posições não pode ser nula")
        if len(set(value)) != len(value):
            raise ValueError("As posições não podem se repetir")
        return value


class RatingPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stars: int = Field(ge=1, le=5, strict=True)
    publish_identity: bool = False


async def profile_dict(session: AsyncSession, person: Person) -> dict:
    """Return the public profile contract, shared by avatar endpoints."""
    profile = await session.get(PersonProfile, person.id)
    nicknames = list(profile.nicknames or []) if profile else []
    positions = list(profile.positions or []) if profile else []
    brasilia_now = d.aware(d.now()).astimezone(d.TZ)
    is_subscriber = await session.scalar(select(MonthlySubscriber.id).where(
        MonthlySubscriber.person_id == person.id,
        MonthlySubscriber.month == brasilia_now.month,
        MonthlySubscriber.year == brasilia_now.year,
        MonthlySubscriber.deleted_at.is_(None),
    ).limit(1)) is not None
    average, rating_count = (await session.execute(
        select(func.avg(PlayerRating.stars), func.count(PlayerRating.id)).where(
            PlayerRating.target_person_id == person.id,
        )
    )).one()

    games = (await session.scalars(select(WeeklyAttendance).where(
        select(WeeklyAttendanceEntry.id).where(
            WeeklyAttendanceEntry.attendance_id == WeeklyAttendance.id,
            WeeklyAttendanceEntry.person_id == person.id,
            WeeklyAttendanceEntry.deleted_at.is_(None),
            WeeklyAttendanceEntry.status == "main",
        ).exists(),
    ))).all()
    now = d.aware(d.now())
    eligible_ids = [game.id for game in games if d.aware(d.starts(game)) <= now]
    games_count = 0
    if eligible_ids:
        games_count = await session.scalar(select(func.count(distinct(WeeklyAttendanceEntry.attendance_id))).where(
            WeeklyAttendanceEntry.attendance_id.in_(eligible_ids),
            WeeklyAttendanceEntry.person_id == person.id,
            WeeklyAttendanceEntry.deleted_at.is_(None),
            WeeklyAttendanceEntry.status == "main",
        )) or 0

    avatar_url = (
        f"/api/public/profiles/{person.id}/avatar?v={profile.photo_version}"
        if profile and profile.photo_avatar_key else None
    )
    return {
        "person_id": person.id,
        "name": person.name,
        "is_subscriber": is_subscriber,
        "nicknames": nicknames,
        "bio": profile.bio or "" if profile else "",
        "positions": positions,
        "primary_position": profile.primary_position if profile else None,
        "sex": profile.sex if profile else None,
        "handedness": profile.handedness if profile else None,
        "skills": profile.skills if profile else None,
        "avatar_url": avatar_url,
        "rating_average": float(average) if average is not None else None,
        "rating_count": int(rating_count or 0),
        "games_count": int(games_count),
    }


@router.get("/public/profiles/{person_id}")
async def public_profile(person_id: UUID, response: Response, session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    person = await session.get(Person, person_id)
    if person is None:
        raise HTTPException(404, "Perfil não encontrado")
    return await profile_dict(session, person)


async def require_own_person(user, session: AsyncSession) -> Person:
    return await own_person(session, user)


@router.get("/me/profile")
async def my_profile(response: Response, user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    person = await require_own_person(user, session)
    profile = await session.get(PersonProfile, person.id)
    result = await profile_dict(session, person)
    result.update({
        "photo_crop": profile.photo_crop if profile else None,
        "photo_version": profile.photo_version if profile else None,
        "photo_content_type": profile.photo_content_type if profile else None,
    })
    return result


@router.patch("/me/profile")
async def patch_my_profile(payload: ProfilePatch, response: Response,
                           user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    person = await require_own_person(user, session)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return await my_profile(response, user, session)

    # Make first creation and concurrent partial updates safe in PostgreSQL.
    await d.lock(session, f"profile:{person.id}")
    await session.execute(insert(PersonProfile).values(person_id=person.id).on_conflict_do_nothing(
        index_elements=[PersonProfile.person_id],
    ))
    profile = await session.scalar(select(PersonProfile).where(
        PersonProfile.person_id == person.id,
    ).with_for_update())
    next_positions = values.get("positions", profile.positions or [])
    next_primary = values.get("primary_position", profile.primary_position)
    if next_positions and next_primary is None:
        raise HTTPException(422, "Selecione uma posição principal")
    if next_primary is not None and next_primary not in next_positions:
        raise HTTPException(422, "A posição principal deve estar entre as posições selecionadas")
    before = {key: getattr(profile, key) for key in values}
    for key, value in values.items():
        setattr(profile, key, value.model_dump() if isinstance(value, BaseModel) else value)
    after = {key: getattr(profile, key) for key in values}
    if before != after:
        await d.audit(session, entity_type="player_profile", entity_id=person.id,
                      action="profile_updated", user=user, person_id=person.id,
                      before=before, after=after, source="player_profile")
    await session.commit()
    return await my_profile(response, user, session)


async def ensure_current_person(user, session: AsyncSession) -> Person:
    account = await d.touch_account(session, user)
    if account.person_id is None:
        raise HTTPException(403, "Aguarde o vínculo da sua conta pelo gestor")
    return await d.get_or_404(session, Person, account.person_id)


@router.get("/me/ratings/{target_id}")
async def my_rating(target_id: UUID, response: Response,
                    user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "private, no-store"
    evaluator = await ensure_current_person(user, session)
    target = await session.get(Person, target_id)
    if target is None:
        raise HTTPException(404, "Jogador não encontrado")
    if target.id == evaluator.id:
        raise HTTPException(409, "Não é possível avaliar o próprio perfil")
    rating = await session.scalar(select(PlayerRating).where(
        PlayerRating.evaluator_person_id == evaluator.id,
        PlayerRating.target_person_id == target.id,
    ))
    average, count = (await session.execute(
        select(func.avg(PlayerRating.stars), func.count(PlayerRating.id)).where(
            PlayerRating.target_person_id == target.id,
        )
    )).one()
    return {
        "stars": rating.stars if rating else None,
        "publish_identity": bool(rating.publish_identity) if rating else False,
        "rating_average": float(average) if average is not None else None,
        "rating_count": int(count or 0),
    }


@router.put("/me/ratings/{target_id}")
async def put_my_rating(target_id: UUID, payload: RatingPut, response: Response,
                        user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    response.headers["Cache-Control"] = "private, no-store"
    evaluator = await ensure_current_person(user, session)
    target = await session.get(Person, target_id)
    if target is None:
        raise HTTPException(404, "Jogador não encontrado")
    if target.id == evaluator.id:
        raise HTTPException(409, "Não é possível avaliar o próprio perfil")
    stmt = insert(PlayerRating).values(
        evaluator_person_id=evaluator.id,
        target_person_id=target.id,
        stars=payload.stars,
        publish_identity=payload.publish_identity,
    ).on_conflict_do_update(
        constraint="uq_player_ratings_evaluator_target",
        set_={"stars": payload.stars, "publish_identity": payload.publish_identity,
              "updated_at": func.now()},
    ).returning(PlayerRating)
    rating = (await session.execute(stmt)).scalar_one()
    # Keep an audit trail without placing rating or consent values in player-visible history.
    await d.audit(session, entity_type="player_rating", entity_id=target.id,
                  action="rating_updated", user=user, person_id=evaluator.id,
                  before={}, after={}, source="player_profile")
    await session.commit()
    public_profile = await profile_dict(session, target)
    return {
        "stars": rating.stars,
        "publish_identity": rating.publish_identity,
        "rating_average": public_profile["rating_average"],
        "rating_count": public_profile["rating_count"],
    }
