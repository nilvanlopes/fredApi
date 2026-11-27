"""Photo validation and isolated storage-flow tests; execution is user-owned."""
import asyncio
import io
import os

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import profile_photos as photos
from app import profile_storage_setup
from app.auth import current_user
from app.database import get_session
from app.models import FredAccount, Person
from app.player_profiles import router as profiles_router


def image_bytes(mode="RGB", size=(80, 60), format="PNG"):
    out = io.BytesIO()
    with Image.new(mode, size, "red") as image:
        image.save(out, format=format)
    return out.getvalue()


def test_avatar_is_square_webp_and_does_not_preserve_source_metadata():
    avatar, mime = photos.render_avatar(image_bytes(), "image/png", photos.Crop(x=10, y=0, width=60, height=60))
    assert mime == "image/png"
    with Image.open(io.BytesIO(avatar)) as image:
        assert image.format == "WEBP"
        assert image.size == (512, 512)
        assert not image.getexif()


@pytest.mark.parametrize("data,mime,crop,status", [
    (b"not an image", "image/png", dict(x=0, y=0, width=10, height=10), 422),
    (image_bytes(), "image/jpeg", dict(x=0, y=0, width=10, height=10), 415),
    (image_bytes(), "image/svg+xml", dict(x=0, y=0, width=10, height=10), 415),
    (image_bytes(), "image/png", dict(x=70, y=0, width=60, height=60), 422),
    (image_bytes(), "image/png", dict(x=0, y=0, width=40, height=20), 422),
    (image_bytes(), "image/png", dict(x=80.5, y=0, width=0.5, height=0.5), 422),
    (image_bytes(), "image/png", dict(x=0, y=0, width=0.1, height=0.1), 422),
    (b"x" * (photos.MAX_BYTES + 1), "image/png", dict(x=0, y=0, width=10, height=10), 413),
])
def test_invalid_upload_is_rejected_before_storage(data, mime, crop, status):
    with pytest.raises(HTTPException) as error:
        photos.render_avatar(data, mime, photos.Crop(**crop))
    assert error.value.status_code == status


def test_animated_images_are_rejected():
    out = io.BytesIO()
    with Image.new("RGB", (20, 20), "red") as first, Image.new("RGB", (20, 20), "blue") as second:
        first.save(out, format="WEBP", save_all=True, append_images=[second], duration=100, loop=0)
    with pytest.raises(HTTPException) as error:
        photos.render_avatar(out.getvalue(), "image/webp", photos.Crop(x=0, y=0, width=20, height=20))
    assert error.value.status_code == 422


def test_orientation_is_applied_before_crop():
    out = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    with Image.new("RGB", (80, 40), "red") as image:
        image.save(out, format="JPEG", exif=exif)
    # Once rotated the dimensions are 40x80; this crop only fits that orientation.
    avatar, _ = photos.render_avatar(out.getvalue(), "image/jpeg", photos.Crop(x=0, y=40, width=40, height=40))
    assert avatar


def test_cleanup_still_attempts_other_objects_when_one_delete_fails(monkeypatch):
    calls = []

    class Client:
        def delete_object(self, *, Bucket, Key):
            calls.append(Key)
            if Key == "first":
                raise HTTPException(503)

    monkeypatch.setattr(photos, "storage", lambda: Client())
    photos.delete_objects("first", "second")
    assert calls == ["first", "second"]


def test_provisioning_refuses_any_other_bucket_before_mutating_it(monkeypatch):
    monkeypatch.setattr(profile_storage_setup, "storage", lambda: object())
    monkeypatch.setattr(profile_storage_setup, "bucket", lambda: "another-app-private-bucket")
    with pytest.raises(SystemExit):
        profile_storage_setup.main()


@pytest.mark.skipif(not os.getenv("FRED_TEST_DATABASE_URL"), reason="Requires isolated PostgreSQL")
def test_photo_ownership_recrop_removal_and_failed_replace(monkeypatch):
    async def scenario():
        url = os.environ["FRED_TEST_DATABASE_URL"]
        assert "fred_test" in url
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        identity = {"uid": "a" * 64, "username": "owner", "name": "Owner", "is_admin": False}
        objects = {}
        fail_write = False

        def put(key, data, mime):
            if fail_write and key.endswith("/avatar.webp"):
                raise HTTPException(503, "Storage unavailable")
            objects[key] = data

        def get(key):
            if key not in objects:
                raise HTTPException(404)
            return objects[key]

        def delete(*keys):
            for key in keys:
                objects.pop(key, None)

        monkeypatch.setattr(photos, "put_object", put)
        monkeypatch.setattr(photos, "get_object", get)
        monkeypatch.setattr(photos, "delete_objects", delete)
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE people, fred_accounts, audit_events RESTART IDENTITY CASCADE"))
        async with factory.begin() as session:
            owner = Person(name="Owner", normalized_name="owner", active=True)
            other = Person(name="Other", normalized_name="other", active=True)
            session.add_all([owner, other])
            await session.flush()
            session.add_all([
                FredAccount(uid=identity["uid"], username="owner", name="Owner", email="", is_admin=False, person_id=owner.id),
                FredAccount(uid="b" * 64, username="other", name="Other", email="", is_admin=False, person_id=other.id),
            ])
        app = FastAPI()
        app.include_router(profiles_router)
        app.include_router(photos.router)

        async def actor():
            if identity is None:
                raise HTTPException(401)
            return identity

        async def db():
            async with factory() as session:
                yield session

        app.dependency_overrides.update({current_user: actor, get_session: db})
        crop = '{"x":0,"y":0,"width":60,"height":60}'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/me/profile/photo", files={"file": ("photo.png", image_bytes(), "image/png")}, data={"crop": crop})
            assert response.status_code == 200, response.text
            avatar_url = response.json()["avatar_url"]
            assert len(objects) == 2
            original = await client.get("/api/me/profile/photo/source")
            assert original.status_code == 200
            assert original.headers["cache-control"] == "private, no-store"
            identity = {"uid": "b" * 64, "username": "other", "name": "Other", "is_admin": False}
            assert (await client.get("/api/me/profile/photo/source")).status_code == 404
            rival_bytes = image_bytes(size=(40, 40))
            rival_photo = await client.post("/api/me/profile/photo", files={"file": ("rival.png", rival_bytes, "image/png")},
                                           data={"crop": '{"x":0,"y":0,"width":40,"height":40}'})
            assert rival_photo.status_code == 200
            rival_original = await client.get("/api/me/profile/photo/source")
            assert rival_original.content == rival_bytes
            assert rival_original.content != original.content
            identity = None
            assert (await client.get(avatar_url)).status_code == 200
            assert (await client.get("/api/me/profile/photo/source")).status_code == 401
            identity = {"uid": "a" * 64, "username": "owner", "name": "Owner", "is_admin": False}
            fail_write = True
            failed = await client.post("/api/me/profile/photo", files={"file": ("new.png", image_bytes(), "image/png")}, data={"crop": crop})
            assert failed.status_code == 503
            assert len(objects) == 4
            assert (await client.get(avatar_url)).status_code == 200
            fail_write = False
            recrop = await client.patch("/api/me/profile/photo", json={"x": 10, "y": 0, "width": 60, "height": 60})
            assert recrop.status_code == 200
            assert recrop.json()["avatar_url"] != avatar_url
            assert len(objects) == 4
            removed = await client.delete("/api/me/profile/photo")
            assert removed.status_code == 200
            assert removed.json()["avatar_url"] is None
            assert len(objects) == 2  # The rival's independent photo is preserved.
            assert (await client.get(avatar_url)).status_code == 404
        await engine.dispose()

    asyncio.run(scenario())
