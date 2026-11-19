"""Fred sessions are validated by Authentik, never by client identity headers."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from ipaddress import ip_address
from ipaddress import ip_address
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.authentik_login import (
    HostedLoginRequired, LoginDenied, LoginUnavailable, OUTPOST_COOKIE_NAME, OUTPOST_START,
    logout_redirect, password_cookie,
)
from app.database import get_session

router = APIRouter()
_signup_attempts: dict[str, deque[float]] = defaultdict(deque)
_username_check_attempts: dict[str, deque[float]] = defaultdict(deque)
_username_check_global: deque[float] = deque()
_username_check_in_flight = asyncio.Semaphore(4)
_password_attempts: deque[tuple[float, str]] = deque()
_password_in_flight = asyncio.Semaphore(8)
_LOGIN_ERROR = "Não foi possível entrar. Confira o email ou usuário e a senha."


def public_url() -> str:
    return os.getenv("FRED_PUBLIC_URL", "https://fred.nilvanlopes.com").rstrip("/")


def authentik_url() -> str:
    return os.getenv("AUTHENTIK_BASE_URL", "https://login-fred.nilvanlopes.com").rstrip("/")


def outpost_auth_url() -> str:
    return os.getenv("AUTHENTIK_AUTH_URL", "http://authentik-outpost-fred_proxy:9000/outpost.goauthentik.io/auth/traefik")


def check_write_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("origin") != public_url() or request.headers.get("x-fred-request") != "1":
        raise HTTPException(403, "Origem da solicitação inválida.")


async def outpost_identity(cookie: str, path: str, method: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.get(
                outpost_auth_url(),
                headers={
                    "Cookie": cookie,
                    "X-Forwarded-Host": public_url().split("://", 1)[1],
                    "X-Forwarded-Proto": public_url().split(":", 1)[0],
                    "X-Forwarded-Uri": path,
                    "X-Forwarded-Method": method,
                    "X-Original-URL": public_url() + path,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Não foi possível verificar a sessão. Tente novamente.") from exc
    if response.status_code >= 500:
        raise HTTPException(503, "O serviço de login está indisponível.")
    if not response.is_success:
        raise HTTPException(403 if response.status_code == 403 else 401, "Sessão expirada ou acesso negado.")
    uid = response.headers.get("x-authentik-uid", "")
    username = response.headers.get("x-authentik-username", "")
    groups = set(response.headers.get("x-authentik-groups", "").split("|"))
    if not re.fullmatch(r"[a-f0-9]{64}", uid) or not username or not groups.intersection({"fred-users", "fred-admins"}):
        raise HTTPException(403, "Esta conta ainda não tem acesso ao Fred.")
    return {
        "uid": uid, "username": username,
        "name": response.headers.get("x-authentik-name") or username,
        "email": response.headers.get("x-authentik-email", ""),
        "is_admin": "fred-admins" in groups,
    }

async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    cookie = request.headers.get("cookie")
    if not cookie:
        raise HTTPException(401, "Entre para continuar.")
    user = await outpost_identity(cookie, request.url.path, request.method)
    check_write_origin(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-fred-account") != user["uid"]:
        raise HTTPException(409, "A conta da sessão mudou. Atualize a página antes de continuar.")
    return await portal_user(session, user)


async def portal_user(session: AsyncSession, user: dict) -> dict:
    from app.management import touch_account
    account = await touch_account(session, user)
    user["is_admin"] = account.is_admin
    user["person_id"] = str(account.person_id) if account.person_id else None
    await session.commit()
    return user


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "Esta ação exige acesso de gestor.")
    return user


def auth_links() -> dict:
    return {"login_url": "/api/auth/login", "google_login_url": "/api/auth/google",
            "signup_url": "/api/auth/signup", "logout_url": "/api/auth/logout"}


@router.get("/api/session")
async def session_info(request: Request, session: AsyncSession = Depends(get_session)):
    try:
        user = await current_user(request, session)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return JSONResponse({"authenticated": False, "user": None, **auth_links()}, headers={"Cache-Control": "no-store"})
    return JSONResponse({"authenticated": True, "user": user, **auth_links()}, headers={"Cache-Control": "no-store"})


def safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"


def _outpost_start_url(next: str = "/") -> str:
    portal = public_url()
    query = urlencode({"rd": portal + safe_next(next)})
    return f"{portal}{OUTPOST_START}?{query}"


@router.get("/api/auth/login")
async def login(next: str = "/"):
    return RedirectResponse(_outpost_start_url(next), status_code=302)


def _hosted_login_response() -> JSONResponse:
    return JSONResponse({"status": "hosted_login_required"}, headers={"Cache-Control": "no-store"})


async def _login_fields(request: Request) -> tuple[str, str]:
    # Parse manually to avoid FastAPI returning submitted credentials in a 422.
    if request.headers.get("content-type", "").partition(";")[0].lower() != "application/json":
        raise HTTPException(400, _LOGIN_ERROR)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 8192:
            raise HTTPException(400, _LOGIN_ERROR)
        raw.extend(chunk)
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        raise HTTPException(400, _LOGIN_ERROR) from None
    if not isinstance(body, dict):
        raise HTTPException(400, _LOGIN_ERROR)
    identifier, password = body.get("identifier"), body.get("password")
    if isinstance(identifier, str):
        identifier = identifier.strip()
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 254:
        raise HTTPException(400, _LOGIN_ERROR)
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise HTTPException(400, _LOGIN_ERROR)
    return identifier, password


def _limit_password_attempts(client_ip: str) -> None:
    now = time.monotonic()
    while _password_attempts and now - _password_attempts[0][0] >= 60:
        _password_attempts.popleft()
    if len(_password_attempts) >= 90 or sum(ip == client_ip for _, ip in _password_attempts) >= 15:
        raise HTTPException(429, "Muitas tentativas. Aguarde antes de tentar novamente.")
    _password_attempts.append((now, client_ip))


@router.post("/api/auth/login")
async def login_with_password(request: Request, session: AsyncSession = Depends(get_session)):
    check_write_origin(request)
    identifier, password = await _login_fields(request)
    # Nginx overwrites this header with the IP assigned by the Cloudflare Tunnel.
    # Without it, retain the hosted flow and its own client-IP policies.
    try:
        address = ip_address(request.headers.get("x-fred-client-ip", ""))
    except ValueError:
        return _hosted_login_response()
    if not address.is_global:
        return _hosted_login_response()
    _limit_password_attempts(str(address))
    try:
        async with asyncio.timeout(25), _password_in_flight:
            cookie = await password_cookie(
                portal_url=public_url(), authentik_url=authentik_url(),
                authentik_internal_url=os.getenv("AUTHENTIK_INTERNAL_URL", "http://server:9000"),
                outpost_auth_url=outpost_auth_url(), client_ip=str(address),
                user_agent=request.headers.get("user-agent", ""),
                identifier=identifier, password=password,
            )
            identity = await outpost_identity(f"{cookie.name}={cookie.value}", "/api/session", "GET")
    except HostedLoginRequired:
        return _hosted_login_response()
    except LoginDenied:
        raise HTTPException(401, _LOGIN_ERROR) from None
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            raise HTTPException(401, _LOGIN_ERROR) from None
        raise
    except (LoginUnavailable, httpx.HTTPError, ValueError, TimeoutError):
        raise HTTPException(503, "O serviço de login está indisponível. Tente novamente.") from None

    user = await portal_user(session, identity)
    response = JSONResponse({
        "status": "authenticated",
        "session": {"authenticated": True, "user": user, **auth_links()},
    }, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        cookie.name, cookie.value, path="/", secure=True, httponly=True, samesite="lax",
        expires=datetime.fromtimestamp(cookie.expires, timezone.utc) if cookie.expires is not None else None,
    )
    return response


@router.get("/api/auth/google")
async def google_login(next: str = "/"):
    query = urlencode({"next": _outpost_start_url(next)})
    return RedirectResponse(authentik_url() + "/if/flow/fred-google-start/?" + query, status_code=302)


@router.get("/api/auth/logout")
async def logout(request: Request):
    cookies = [name for name in request.cookies if OUTPOST_COOKIE_NAME.fullmatch(name)]
    target = public_url() + "/"
    if cookies:
        try:
            target = await logout_redirect(
                portal_url=public_url(), authentik_url=authentik_url(), outpost_auth_url=outpost_auth_url(),
                cookie_header=request.headers.get("cookie"),
            )
        except (LoginDenied, LoginUnavailable, httpx.HTTPError, ValueError):
            raise HTTPException(503, "Não foi possível encerrar a sessão. Tente novamente.") from None
    response = RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})
    for name in cookies:
        response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
    return response


class Signup(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=256)
    username: str | None = Field(default=None, max_length=64)
    password_repeat: str | None = None


class UsernameAvailabilityCheck(BaseModel):
    name: str = Field(min_length=1, max_length=150)


def signup_username(name: str) -> str:
    """Keep the public availability check and final enrollment normalization identical."""
    return re.sub(r"[^a-z0-9_.-]+", "-", name.strip().lower()).strip(".-_")[:64]


def _trusted_client_key(request: Request) -> str:
    # Fred's Nginx overwrites this value from Cloudflare's connecting-IP header.
    candidate = request.headers.get("x-fred-client-ip", "")
    try:
        return str(ip_address(candidate))
    except ValueError:
        return request.client.host if request.client else "unknown"


def _limit_username_check(request: Request) -> None:
    now = time.monotonic()
    key = _trusted_client_key(request)
    for old_key in list(_username_check_attempts):
        attempts = _username_check_attempts[old_key]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if not attempts:
            del _username_check_attempts[old_key]
    while _username_check_global and _username_check_global[0] < now - 60:
        _username_check_global.popleft()
    # Bound memory in the unlikely event requests come through many source IPs.
    while len(_username_check_attempts) >= 4096 and key not in _username_check_attempts:
        _username_check_attempts.pop(next(iter(_username_check_attempts)))
    attempts = _username_check_attempts[key]
    if len(attempts) >= 30 or len(_username_check_global) >= 120:
        raise HTTPException(429, "Muitas verificações. Aguarde um minuto e tente novamente.", headers={"Retry-After": "60"})
    attempts.append(now)
    _username_check_global.append(now)


def _username_taken(errors: object) -> bool:
    if not isinstance(errors, dict):
        return False
    username_errors = errors.get("username")
    return isinstance(username_errors, list) and any(
        isinstance(error, dict)
        and error.get("code") == "invalid"
        and isinstance(error.get("string"), str)
        and error["string"].strip().lower() == "username is already taken."
        for error in username_errors
    )


def _required_error(errors: object, field: str) -> bool:
    if not isinstance(errors, dict) or not isinstance(errors.get(field), list):
        return False
    values = errors[field]
    return bool(values) and all(isinstance(error, dict) and error.get("code") == "required" for error in values)


@router.post("/api/auth/username-availability")
async def username_availability(payload: UsernameAvailabilityCheck, request: Request, response: Response):
    check_write_origin(request)
    response.headers["Cache-Control"] = "no-store"
    username = signup_username(payload.name)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
        raise HTTPException(422, "Use ao menos 3 letras ou números no nome de usuário.")
    _limit_username_check(request)
    if _username_check_in_flight.locked():
        raise HTTPException(429, "Muitas verificações simultâneas. Aguarde e tente novamente.", headers={"Retry-After": "2"})

    internal = os.getenv("AUTHENTIK_INTERNAL_URL", "http://server:9000").rstrip("/")
    path = "/api/v3/flows/executor/fred-enrollment/"
    try:
        async with _username_check_in_flight:
            async with httpx.AsyncClient(base_url=internal, timeout=5, follow_redirects=False) as client:
                headers = {
                    "Host": authentik_url().split("://", 1)[1],
                    "X-Forwarded-Proto": "https",
                    "Accept-Language": "en",
                }
                challenge_response = await client.get(path, headers=headers)
                challenge = challenge_response.json()
                fields = challenge.get("fields") if isinstance(challenge, dict) else None
                if not challenge_response.is_success or not isinstance(fields, list) or challenge.get("component") != "ak-stage-prompt":
                    raise ValueError("Unexpected enrollment prompt")
                field_map = {field.get("field_key"): field for field in fields if isinstance(field, dict)}
                expected_fields = {"username", "name", "email", "password", "password_repeat"}
                if set(field_map) != expected_fields:
                    raise ValueError("Enrollment prompt fields changed")
                username_field = field_map["username"]
                if username_field.get("type") != "username" or not username_field.get("required") or username_field.get("initial_value"):
                    raise ValueError("Username prompt is not safely checkable")
                if any(not field_map[key].get("required") or field_map[key].get("initial_value") for key in expected_fields - {"username"}):
                    raise ValueError("Enrollment prompt can proceed without omitted fields")

                csrf = client.cookies.get("authentik_csrf") or client.cookies.get("csrftoken")
                post_headers = {
                    **headers,
                    "Cookie": "; ".join(f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar),
                    "Referer": authentik_url() + "/if/flow/fred-enrollment/",
                    "Origin": authentik_url(),
                }
                if csrf:
                    post_headers["X-authentik-CSRF"] = csrf
                result = await client.post(path, headers=post_headers, json={
                    "component": "ak-stage-prompt", "username": username,
                })
                if result.status_code >= 400 or result.is_redirect:
                    raise ValueError("Enrollment username check failed")
                result_body = result.json()
                errors = result_body.get("response_errors") if isinstance(result_body, dict) else None
                omitted_fields = expected_fields - {"username"}
                if result_body.get("component") != "ak-stage-prompt" or not all(_required_error(errors, key) for key in omitted_fields):
                    raise ValueError("Enrollment did not reject incomplete prompt")
                taken = _username_taken(errors)
                if set(errors) - omitted_fields - ({"username"} if taken else set()):
                    raise ValueError("Unexpected enrollment validation error")
                if "username" in errors and not taken:
                    raise ValueError("Unknown username validation error")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "Não foi possível verificar o nome de usuário agora. Tente novamente.") from exc

    return JSONResponse(
        {"username": username, "available": not taken},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/auth/signup")
async def signup(payload: Signup, request: Request):
    check_write_origin(request)
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    for old_key in list(_signup_attempts):
        attempts = _signup_attempts[old_key]
        while attempts and attempts[0] < now - 3600:
            attempts.popleft()
        if not attempts:
            del _signup_attempts[old_key]
    attempts = _signup_attempts[key]
    if len(attempts) >= 60:
        raise HTTPException(429, "Muitas tentativas. Aguarde antes de tentar novamente.")
    attempts.append(now)
    email = payload.email.strip().lower()
    # The public signup form's "Nome" field is also the requested Authentik
    # username. Normalize full names to a valid username when they contain
    # spaces or accented characters; callers may still provide an explicit one.
    requested_name = payload.name.strip()
    generated = signup_username(requested_name)
    username = payload.username.strip() if payload.username else generated
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
        raise HTTPException(422, "Informe email e usuário válidos (3 a 64 letras, números, ponto, hífen ou sublinhado).")
    if payload.password_repeat is not None and payload.password != payload.password_repeat:
        raise HTTPException(422, "As senhas não conferem.")
    # A fixed enrollment flow alone assigns fred-users. Never forward a group,
    # invitation, flow slug or privilege supplied by the request.
    internal = os.getenv("AUTHENTIK_INTERNAL_URL", "http://server:9000").rstrip("/")
    path = "/api/v3/flows/executor/fred-enrollment/"
    internal_url = httpx.URL(internal)

    def enrollment_target(response: httpx.Response) -> httpx.URL:
        location = response.headers.get("location")
        if response.status_code not in {302, 303} or not location:
            raise ValueError("Unexpected enrollment redirect")
        target = response.url.join(location)
        if (
            target.scheme != internal_url.scheme
            or target.netloc != internal_url.netloc
            or target.userinfo
            or target.raw_path.split(b"?", 1)[0] != path.encode()
            or target.fragment
            or target.params.multi_items() not in ([], [("query", "")])
        ):
            raise ValueError("Unexpected enrollment redirect target")
        return target

    try:
        async with httpx.AsyncClient(base_url=internal, timeout=15, follow_redirects=False) as client:
            headers = {"Host": authentik_url().split("://", 1)[1], "X-Forwarded-Proto": "https", "Accept-Language": "en"}
            initial = await client.get(path, headers=headers)
            body = initial.json()
            if not initial.is_success or not isinstance(body, dict) or body.get("component") != "ak-stage-prompt":
                raise ValueError("Enrollment prompt unavailable")
            csrf = client.cookies.get("authentik_csrf") or client.cookies.get("csrftoken")
            if csrf:
                headers["X-authentik-CSRF"] = csrf
            # Browser cookies are Secure, while this trusted backend hop is HTTP.
            # Keep the isolated enrollment jar across that hop explicitly.
            headers["Cookie"] = "; ".join(f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar)
            headers["Referer"] = authentik_url() + "/if/flow/fred-enrollment/"
            headers["Origin"] = authentik_url()
            response = await client.post(path, headers=headers, json={
                "component": "ak-stage-prompt", "username": username, "name": payload.name.strip(),
                "email": email, "password": payload.password, "password_repeat": payload.password,
            })
            if response.status_code >= 500:
                raise ValueError("Enrollment service unavailable")
            if response.status_code >= 400:
                try:
                    response_errors = response.json().get("response_errors")
                except (ValueError, AttributeError):
                    response_errors = None
                if _username_taken(response_errors):
                    raise HTTPException(422, "Esse nome de usuário já existe. Escolha outro.")
                raise HTTPException(422, "Não foi possível cadastrar. Confira os dados ou entre com uma conta existente.")

            for _ in range(8):
                if response.is_redirect:
                    target = enrollment_target(response)
                    headers["Cookie"] = "; ".join(
                        f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar
                    )
                    response = await client.get(target, headers=headers)
                    continue

                if not response.is_success:
                    raise ValueError("Enrollment stage unavailable")
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid enrollment response")
                if _username_taken(body.get("response_errors")):
                    raise HTTPException(422, "Esse nome de usuário já existe. Escolha outro.")
                if body.get("response_errors") or body.get("non_field_errors"):
                    raise HTTPException(422, "Não foi possível cadastrar. Confira os dados ou entre com uma conta existente.")
                if body.get("component") == "ak-stage-email":
                    break
                raise ValueError("Enrollment did not request email verification")
            else:
                raise ValueError("Enrollment flow exceeded redirect limit")
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(502, "O cadastro está temporariamente indisponível. Tente novamente.") from exc
    return {"status": "confirmation_sent", "message": "Confira seu email para confirmar o cadastro e depois entrar no Fred."}
