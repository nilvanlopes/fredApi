"""Private S3 originals and validated, publicly served profile derivatives."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import warnings
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import management as d
from app.admin_api import own_person
from app.auth import current_user
from app.database import get_session
from app.models import Person, PersonProfile
from app.player_profiles import profile_dict

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
_image_slot = asyncio.Semaphore(1)
MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class Crop(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


def storage():
    access = os.getenv("FRED_PROFILE_S3_ACCESS_KEY_ID", "")
    secret = os.getenv("FRED_PROFILE_S3_SECRET_ACCESS_KEY", "")
    if not access or not secret:
        raise HTTPException(503, "O armazenamento de fotos ainda não foi configurado.")
    return boto3.client(
        "s3", endpoint_url=os.getenv("FRED_PROFILE_S3_ENDPOINT", "http://floci:4566"),
        region_name=os.getenv("FRED_PROFILE_S3_REGION", "us-east-1"),
        aws_access_key_id=access, aws_secret_access_key=secret,
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15,
                      retries={"max_attempts": 2}, s3={"addressing_style": "path"}),
    )


def bucket():
    return os.getenv("FRED_PROFILE_S3_BUCKET", "fred-profile-images")


def put_object(key: str, data: bytes, content_type: str):
    try:
        storage().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(503, "Não foi possível salvar a foto. Tente novamente.") from exc


def get_object(key: str) -> bytes:
    try:
        obj = storage().get_object(Bucket=bucket(), Key=key)
        stream = obj["Body"]
        try:
            data = stream.read(MAX_BYTES + 1)
        finally:
            stream.close()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "A foto excede o limite de 10 MiB.")
        return data
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404", "NotFound"}:
            raise HTTPException(404, "Foto não encontrada.") from exc
        raise HTTPException(503, "Não foi possível carregar a foto.") from exc
    except BotoCoreError as exc:
        raise HTTPException(503, "Não foi possível carregar a foto.") from exc


def delete_objects(*keys: str | None):
    keys = tuple(key for key in keys if key)
    if not keys:
        return
    for key in keys:
        try:
            client = storage()
            client.delete_object(Bucket=bucket(), Key=key)
        except (BotoCoreError, ClientError, HTTPException):
            logger.warning("Falha na limpeza de objeto de foto; verificar armazenamento privado.")


def render_avatar(data: bytes, content_type: str, crop: Crop) -> tuple[bytes, str]:
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "A foto excede o limite de 10 MiB.")
    if content_type not in MIMES.values():
        raise HTTPException(415, "Escolha uma imagem JPEG, PNG ou WebP.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                mime = MIMES.get(image.format)
                if mime != content_type:
                    raise HTTPException(415, "O conteúdo da imagem não corresponde ao formato informado.")
                if image.width * image.height > MAX_PIXELS:
                    raise HTTPException(422, "A imagem deve ter no máximo 40 milhões de pixels.")
                if getattr(image, "is_animated", False):
                    raise HTTPException(422, "Escolha uma imagem sem animação.")
                image.load()
                ImageOps.exif_transpose(image, in_place=True)
                left, top = round(crop.x), round(crop.y)
                right, bottom = round(crop.x + crop.width), round(crop.y + crop.height)
                if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                    raise HTTPException(422, "O recorte ultrapassa os limites da imagem.")
                if abs((right - left) - (bottom - top)) > 1:
                    raise HTTPException(422, "O recorte deve ser quadrado.")
                with image.crop((left, top, right, bottom)) as cropped:
                    image.close()
                    with cropped.resize((512, 512), Image.Resampling.LANCZOS) as resized:
                        cropped.close()
                        # A fresh image deliberately excludes source EXIF/ICC/text metadata.
                        clean = Image.new("RGBA", resized.size)
                        with resized.convert("RGBA") as rgba:
                            clean.paste(rgba)
                        output = io.BytesIO()
                        clean.save(output, format="WEBP", quality=85)
                        clean.close()
                        return output.getvalue(), mime
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, "Não foi possível ler essa imagem.") from exc


async def locked_profile(session, person):
    await d.lock(session, f"profile:{person.id}")
    row = await session.scalar(select(PersonProfile).where(PersonProfile.person_id == person.id).with_for_update())
    if row is None:
        row = PersonProfile(person_id=person.id)
        session.add(row)
        await session.flush()
    return row


async def save_photo(session, person, user, row, crop, data, mime, *, replace_source):
    async with _image_slot:
        avatar, verified_mime = await run_in_threadpool(render_avatar, data, mime, crop)
    version = uuid4().hex
    prefix = f"profiles/{person.id}/{version}"
    avatar_key = f"{prefix}/avatar.webp"
    source_key = f"{prefix}/source" if replace_source else row.photo_source_key
    old_source, old_avatar = row.photo_source_key, row.photo_avatar_key
    new_keys = [avatar_key] + ([source_key] if replace_source else [])
    try:
        if replace_source:
            await run_in_threadpool(put_object, source_key, data, verified_mime)
        await run_in_threadpool(put_object, avatar_key, avatar, "image/webp")
        row.photo_source_key = source_key
        row.photo_avatar_key = avatar_key
        row.photo_content_type = verified_mime
        row.photo_crop = crop.model_dump()
        row.photo_version = version
        await d.audit(session, entity_type="profile", entity_id=person.id, person_id=person.id,
                      action="photo_update", user=user, after={"has_photo": True})
        await session.commit()
    except Exception:
        await session.rollback()
        await run_in_threadpool(delete_objects, *new_keys)
        raise
    await run_in_threadpool(delete_objects, old_avatar, old_source if replace_source else None)
    return await profile_dict(session, person)


@router.post("/me/profile/photo")
async def upload_photo(file: UploadFile = File(...), crop: str = Form(...),
                       user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    person = await own_person(session, user)
    try:
        parsed = Crop.model_validate_json(crop)
    except (ValidationError, ValueError):
        raise HTTPException(422, "Recorte inválido.") from None
    try:
        data = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    row = await locked_profile(session, person)
    return await save_photo(session, person, user, row, parsed, data, file.content_type or "", replace_source=True)


@router.patch("/me/profile/photo")
async def recrop_photo(crop: Crop, user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    person = await own_person(session, user)
    row = await locked_profile(session, person)
    if not row.photo_source_key:
        raise HTTPException(404, "Foto não encontrada.")
    data = await run_in_threadpool(get_object, row.photo_source_key)
    return await save_photo(session, person, user, row, crop, data, row.photo_content_type, replace_source=False)


@router.delete("/me/profile/photo")
async def remove_photo(user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    person = await own_person(session, user)
    row = await locked_profile(session, person)
    old = (row.photo_source_key, row.photo_avatar_key)
    row.photo_source_key = row.photo_avatar_key = row.photo_content_type = row.photo_version = None
    row.photo_crop = None
    await d.audit(session, entity_type="profile", entity_id=person.id, person_id=person.id,
                  action="photo_remove", user=user, after={"has_photo": False})
    await session.commit()
    await run_in_threadpool(delete_objects, *old)
    return await profile_dict(session, person)


@router.get("/me/profile/photo/source")
async def photo_source(user=Depends(current_user), session: AsyncSession = Depends(get_session)):
    person = await own_person(session, user)
    await d.lock(session, f"profile:{person.id}")
    row = await session.get(PersonProfile, person.id)
    if row is None or not row.photo_source_key:
        raise HTTPException(404, "Foto não encontrada.")
    data = await run_in_threadpool(get_object, row.photo_source_key)
    return Response(data, media_type=row.photo_content_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                             "Cross-Origin-Resource-Policy": "same-origin"})


@router.get("/public/profiles/{person_id}/avatar")
async def public_avatar(person_id: UUID, session: AsyncSession = Depends(get_session)):
    await d.lock(session, f"profile:{person_id}")
    row = await session.get(PersonProfile, person_id)
    if row is None or not row.photo_avatar_key or await session.get(Person, person_id) is None:
        raise HTTPException(404, "Foto não encontrada.")
    data = await run_in_threadpool(get_object, row.photo_avatar_key)
    return Response(data, media_type="image/webp", headers={"Cache-Control": "no-cache",
                    "X-Content-Type-Options": "nosniff"})
