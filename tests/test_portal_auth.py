import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth, authentik_login
from app.database import get_session


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(auth.router)
    @app.post("/probe")
    async def probe(user=Depends(auth.current_user)):
        return {"ok": True}
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_session():
        yield session

    app.dependency_overrides[get_session] = fake_session
    monkeypatch.setenv("FRED_PUBLIC_URL", "https://fred.nilvanlopes.com")
    auth._signup_attempts.clear()
    auth._username_check_attempts.clear()
    auth._username_check_global.clear()
    auth._password_attempts.clear()
    return TestClient(app)


def test_session_requires_cookie_even_with_forged_identity(client):
    response = client.get("/api/session", headers={"X-authentik-uid": "a" * 64, "X-authentik-groups": "fred-admins"})
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["user"] is None
    assert response.headers["cache-control"] == "no-store"


def test_login_rejects_external_return_url(client):
    response = client.get("/api/auth/login?next=//evil.example", follow_redirects=False)
    assert response.status_code == 302
    assert "evil.example" not in response.headers["location"]
    assert "fred.nilvanlopes.com" in response.headers["location"]


@pytest.mark.parametrize("endpoint", ["login", "google"])
def test_profile_login_preserves_local_hash_and_rejects_foreign_target(client, endpoint):
    from urllib.parse import parse_qs, urlsplit
    target = "/#profile/12345678-1234-1234-1234-123456789abc"
    response = client.get(f"/api/auth/{endpoint}", params={"next": target}, follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    if endpoint == "google":
        location = parse_qs(urlsplit(location).query)["next"][0]
    assert parse_qs(urlsplit(location).query)["rd"] == [auth.public_url() + target]
    rejected = client.get(f"/api/auth/{endpoint}", params={"next": "//evil.example/#profile"}, follow_redirects=False)
    assert "evil.example" not in rejected.headers["location"]



PORTAL = "https://fred.nilvanlopes.com"
IDP = "https://login-fred.nilvanlopes.com"
LOGIN_HEADERS = {"Origin": PORTAL, "X-Fred-Request": "1", "X-Fred-Client-IP": "1.1.1.1"}
LOGIN_FIELDS = {"identifier": "jogador", "password": "senha de teste"}
OUTPOST_COOKIE = "authentik_proxy_abcd"


@pytest.mark.parametrize("scenario", ["success", "mfa", "bad_password", "foreign_redirect", "bad_state", "no_membership"])
def test_password_login_with_authentik_and_outpost(client, monkeypatch, scenario):
    monkeypatch.setenv("AUTHENTIK_BASE_URL", IDP)
    from app import management
    account = AsyncMock(return_value=SimpleNamespace(is_admin=False, person_id=None))
    monkeypatch.setattr(management, "touch_account", account)
    authorize = "/application/o/authorize/?client_id=fred&state=testing"
    flow_page = httpx.URL(IDP + authentik_login.LOGIN_PAGE).copy_set_param("next", authorize)
    visited = []

    def upstream(request):
        visited.append((request.url.path, request.method))
        if request.url.path == authentik_login.OUTPOST_START:
            assert request.url.params["rd"] == PORTAL + "/"
            return httpx.Response(302, headers={
                "Location": IDP + authorize,
                "Set-Cookie": f"{OUTPOST_COOKIE}=pending; Path=/; Secure; HttpOnly",
            })
        if request.url.path == authentik_login.AUTHORIZE:
            assert OUTPOST_COOKIE not in request.headers.get("cookie", "")
            if "authentik_session=" not in request.headers.get("cookie", ""):
                return httpx.Response(302, headers={
                    "Location": str(flow_page),
                    "Set-Cookie": "authentik_session=before; Path=/; Secure; HttpOnly",
                })
            assert request.headers["cookie"] == "authentik_session=after; authentik_csrf=csrf-token"
            state = "wrong" if scenario == "bad_state" else "testing"
            return httpx.Response(302, headers={
                "Location": PORTAL + authentik_login.OUTPOST_CALLBACK + f"?code=code&state={state}",
            })
        if request.url.path == authentik_login.EXECUTOR:
            assert request.url.params["query"] == flow_page.query.decode()
            if request.method == "GET":
                assert request.headers["cookie"] == "authentik_session=before"
                return httpx.Response(200, json={"component": "ak-stage-identification", "password_fields": True},
                                      headers={"Set-Cookie": "authentik_csrf=csrf-token; Path=/; Secure"})
            assert request.headers["cookie"] == "authentik_session=before; authentik_csrf=csrf-token"
            assert request.headers["x-authentik-csrf"] == "csrf-token"
            assert json.loads(request.content) == {
                "component": "ak-stage-identification", "uid_field": LOGIN_FIELDS["identifier"],
                "password": LOGIN_FIELDS["password"],
            }
            if scenario == "mfa":
                return httpx.Response(200, json={"component": "ak-stage-authenticator-validate"})
            if scenario == "bad_password":
                return httpx.Response(200, json={"component": "ak-stage-identification",
                                               "response_errors": {"__all__": [{"string": "denied"}]}})
            return httpx.Response(200, json={
                "component": "xak-flow-redirect",
                "to": "https://example.invalid/" if scenario == "foreign_redirect" else authorize,
                "final_redirect": True,
            }, headers={"Set-Cookie": "authentik_session=after; Path=/; Secure; HttpOnly"})
        if request.url.path == authentik_login.OUTPOST_CALLBACK:
            assert request.headers["cookie"] == f"{OUTPOST_COOKIE}=pending"
            return httpx.Response(302, headers=[
                ("Location", PORTAL + "/"),
                ("Set-Cookie", f"{OUTPOST_COOKIE}=complete; Path=/; Secure; HttpOnly"),
                ("Set-Cookie", "other=not-forwarded; Path=/; Secure; HttpOnly"),
            ])
        pytest.fail(f"Unexpected upstream request: {request.url.path}")

    monkeypatch.setattr(authentik_login, "_InternalAuthTransport", lambda routes, ip: httpx.MockTransport(upstream))

    original_get = httpx.AsyncClient.get

    async def verify_cookie(self, url, **kwargs):
        if url != auth.outpost_auth_url():
            return await original_get(self, url, **kwargs)
        headers = kwargs["headers"]
        assert headers["Cookie"] == f"{OUTPOST_COOKIE}=complete"
        assert headers["X-Forwarded-Uri"] == "/api/session"
        return httpx.Response(200, headers={
            "x-authentik-uid": "c" * 64,
            "x-authentik-username": "jogador",
            "x-authentik-groups": "fichasrpg-users" if scenario == "no_membership" else "fred-users",
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", verify_cookie)
    response = client.post("/api/auth/login", headers=LOGIN_HEADERS, json=LOGIN_FIELDS)
    if scenario == "success":
        assert response.status_code == 200
        assert response.json()["status"] == "authenticated"
        account.assert_awaited_once()
        cookies = response.headers.get_list("set-cookie")
        assert len(cookies) == 1
        assert f"{OUTPOST_COOKIE}=complete" in cookies[0]
        assert {"httponly", "secure", "samesite=lax", "path=/"} <= set(cookies[0].lower().split("; ")[1:])
        assert visited[-1] == (authentik_login.OUTPOST_CALLBACK, "GET")
        session = client.get("/api/session", headers={"Cookie": f"{OUTPOST_COOKIE}=complete"})
        assert session.json()["authenticated"] is True
        assert session.json()["user"]["username"] == "jogador"
        assert response.json()["session"] == session.json()
    else:
        account.assert_not_awaited()
        assert response.status_code == {
            "mfa": 200, "bad_password": 401, "foreign_redirect": 503, "bad_state": 503, "no_membership": 401,
        }[scenario]
        assert "set-cookie" not in response.headers
        if scenario == "mfa":
            assert response.json() == {"status": "hosted_login_required"}
            assert visited[-1] == (authentik_login.EXECUTOR, "POST")
        if scenario in {"bad_password", "no_membership"}:
            assert response.json() == {"detail": auth._LOGIN_ERROR}
    assert LOGIN_FIELDS["password"] not in response.text
    if response.status_code == 200:
        assert response.headers["cache-control"] == "no-store"


def test_password_login_rejects_cross_origin_and_does_not_echo_bad_input(client, monkeypatch):
    authenticate = AsyncMock()
    monkeypatch.setattr(auth, "password_cookie", authenticate)
    wrong_origin = client.post("/api/auth/login", headers={**LOGIN_HEADERS, "Origin": "https://example.invalid"},
                               json=LOGIN_FIELDS)
    bad_password = client.post("/api/auth/login", headers=LOGIN_HEADERS,
                               json={**LOGIN_FIELDS, "password": [LOGIN_FIELDS["password"]]})
    oversized = client.post("/api/auth/login", headers=LOGIN_HEADERS,
                            json={**LOGIN_FIELDS, "password": "x" * 8193})
    assert wrong_origin.status_code == 403
    assert bad_password.status_code == 400
    assert oversized.status_code == 400
    assert LOGIN_FIELDS["password"] not in bad_password.text
    authenticate.assert_not_awaited()


def test_password_login_limits_retries_and_requires_ingress_ip(client, monkeypatch):
    authenticate = AsyncMock(side_effect=auth.LoginDenied)
    monkeypatch.setattr(auth, "password_cookie", authenticate)
    no_ingress = client.post("/api/auth/login", headers={**LOGIN_HEADERS, "X-Fred-Client-IP": ""},
                             json=LOGIN_FIELDS)
    assert no_ingress.json() == {"status": "hosted_login_required"}
    for _ in range(15):
        assert client.post("/api/auth/login", headers=LOGIN_HEADERS, json=LOGIN_FIELDS).status_code == 401
    assert client.post("/api/auth/login", headers=LOGIN_HEADERS, json=LOGIN_FIELDS).status_code == 429
    assert authenticate.await_count == 15

def test_google_uses_dedicated_flow(client):
    response = client.get("/api/auth/google", follow_redirects=False)
    assert response.status_code == 302
    redirect = httpx.URL(response.headers["location"])
    assert redirect.path == "/if/flow/fred-google-start/"

    outpost_start = httpx.URL(redirect.params["next"])
    assert str(outpost_start.copy_with(query=None)) == PORTAL + authentik_login.OUTPOST_START
    assert outpost_start.params["rd"] == PORTAL + "/"


@pytest.mark.parametrize("case", ["active", "expired", "missing", "foreign_redirect", "unavailable"])
def test_logout_revokes_outpost_session_and_clears_pending_authentik_flow(client, monkeypatch, case):
    monkeypatch.setenv("AUTHENTIK_BASE_URL", IDP)
    outpost = httpx.URL("http://outpost:9000" + authentik_login.OUTPOST_SIGN_OUT)
    monkeypatch.setenv("AUTHENTIK_AUTH_URL", "http://outpost:9000/outpost.goauthentik.io/auth/traefik")
    end_session = authentik_login.END_SESSION + "?id_token_hint=test.token"

    async def sign_out(url, **kwargs):
        assert url == outpost
        assert kwargs["headers"]["Host"] == httpx.URL(PORTAL).host
        assert kwargs["headers"]["Cookie"] == f"{OUTPOST_COOKIE}=complete"
        if case == "unavailable":
            raise httpx.ConnectError("offline")
        target = {
            "active": IDP + end_session,
            "expired": PORTAL + authentik_login.OUTPOST_START + "?rd=ignored",
            "foreign_redirect": "https://example.invalid" + end_session,
        }[case]
        return httpx.Response(302, headers={"Location": target}, request=httpx.Request("GET", url))

    upstream = AsyncMock(side_effect=sign_out)
    monkeypatch.setattr(httpx.AsyncClient, "get", upstream)
    headers = {} if case == "missing" else {"Cookie": f"{OUTPOST_COOKIE}=complete"}
    response = client.get("/api/auth/logout", headers=headers, follow_redirects=False)

    if case == "missing":
        upstream.assert_not_awaited()
        assert "set-cookie" not in response.headers
    else:
        upstream.assert_awaited_once()
    if case in {"foreign_redirect", "unavailable"}:
        assert response.status_code == 503
        assert "location" not in response.headers
        assert "set-cookie" not in response.headers
        return
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    if case != "missing":
        assert response.headers["set-cookie"].startswith(f'{OUTPOST_COOKIE}="";')
        assert "Max-Age=0" in response.headers["set-cookie"]
    if case == "active":
        target = httpx.URL(response.headers["location"])
        assert target == httpx.URL(IDP + authentik_login.CANCEL_FLOW).copy_set_param("next", end_session)
    else:
        assert response.headers["location"] == PORTAL + "/"


def test_signup_requires_same_origin(client):
    response = client.post("/api/auth/signup", json={"name": "Jogador", "email": "player@example.com", "password": "long-password"},
                           headers={"Origin": "https://evil.example", "X-Fred-Request": "1"})
    assert response.status_code == 403


def test_signup_validates_username_before_enrollment(client):
    response = client.post("/api/auth/signup", json={"name": "Jogador", "username": "../admin", "email": "player@example.com", "password": "long-password"},
                           headers={"Origin": "https://fred.nilvanlopes.com", "X-Fred-Request": "1"})
    assert response.status_code == 422


def test_username_availability_uses_authentik_prompt_without_submitting_account(client, monkeypatch):
    executor = "http://server:9000/api/v3/flows/executor/fred-enrollment/"
    fields = [
        {"field_key": "username", "type": "username", "required": True, "initial_value": ""},
        {"field_key": "name", "type": "text", "required": True, "initial_value": ""},
        {"field_key": "email", "type": "email", "required": True, "initial_value": ""},
        {"field_key": "password", "type": "password", "required": True, "initial_value": ""},
        {"field_key": "password_repeat", "type": "password", "required": True, "initial_value": ""},
    ]
    posted = []

    async def prompt(self, url, **kwargs):
        self.cookies.set("authentik_csrf", "csrf-token")
        return httpx.Response(200, json={"component": "ak-stage-prompt", "fields": fields},
                              request=httpx.Request("GET", executor))

    async def validate(self, url, **kwargs):
        payload = kwargs["json"]
        posted.append(payload)
        assert set(payload) == {"component", "username"}
        errors = {
            key: [{"string": "This field is required.", "code": "required"}]
            for key in ("name", "email", "password", "password_repeat")
        }
        if payload["username"] == "pyuteste":
            errors["username"] = [{"string": "Username is already taken.", "code": "invalid"}]
        return httpx.Response(200, json={"component": "ak-stage-prompt", "response_errors": errors},
                              request=httpx.Request("POST", executor))

    monkeypatch.setattr(httpx.AsyncClient, "get", prompt)
    monkeypatch.setattr(httpx.AsyncClient, "post", validate)
    headers = {"Origin": PORTAL, "X-Fred-Request": "1"}
    taken = client.post("/api/auth/username-availability", headers=headers, json={"name": "Pyuteste"})
    available = client.post("/api/auth/username-availability", headers=headers, json={"name": "Jogador Novo"})

    assert taken.status_code == available.status_code == 200
    assert taken.json() == {"username": "pyuteste", "available": False}
    assert available.json() == {"username": "jogador-novo", "available": True}
    assert taken.headers["cache-control"] == "no-store"
    assert posted == [
        {"component": "ak-stage-prompt", "username": "pyuteste"},
        {"component": "ak-stage-prompt", "username": "jogador-novo"},
    ]


def test_session_outpost_unavailable_fails_closed(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx.AsyncClient, "get", fail)
    client.cookies.set("authentik_proxy", "untrusted")
    response = client.get("/api/session")
    assert response.status_code == 503


def test_session_rejects_outpost_identity_without_membership(client, monkeypatch):
    async def denied(*args, **kwargs):
        return httpx.Response(200, headers={"X-authentik-uid": "a" * 64, "X-authentik-username": "someone", "X-authentik-groups": "fichasrpg-users"})
    monkeypatch.setattr(httpx.AsyncClient, "get", denied)
    client.cookies.set("authentik_proxy", "untrusted")
    assert client.get("/api/session").status_code == 403


def test_session_reads_identity_only_from_validated_outpost(client, monkeypatch):
    import app.management as management

    async def verified(*args, **kwargs):
        return httpx.Response(200, headers={"X-authentik-uid": "a" * 64, "X-authentik-username": "player", "X-authentik-groups": "fred-users"})
    monkeypatch.setattr(httpx.AsyncClient, "get", verified)
    touch = AsyncMock(return_value=SimpleNamespace(is_admin=False, person_id=None))
    monkeypatch.setattr(management, "touch_account", touch)
    client.cookies.set("authentik_proxy", "validated")
    response = client.get("/api/session", headers={"X-authentik-username": "pyu", "X-authentik-groups": "fred-admins"})
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "player"
    assert response.json()["user"]["is_admin"] is False


@pytest.mark.parametrize("headers, expected", [
    ({"Origin": "https://evil.example", "X-Fred-Request": "1", "X-Fred-Account": "a"*64}, 403),
    ({"Origin": "https://fred.nilvanlopes.com", "X-Fred-Request": "1", "X-Fred-Account": "b"*64}, 409),
])
def test_writes_check_origin_and_current_account(client, monkeypatch, headers, expected):
    async def verified(*args, **kwargs):
        return httpx.Response(200, headers={"X-authentik-uid": "a"*64, "X-authentik-username": "player", "X-authentik-groups": "fred-users"})
    monkeypatch.setattr(httpx.AsyncClient, "get", verified)
    client.cookies.set("authentik_proxy", "validated")
    assert client.post("/probe", headers=headers).status_code == expected


def test_signup_uses_fixed_flow_and_email_confirmation(client, monkeypatch):
    executor = "http://server:9000/api/v3/flows/executor/fred-enrollment/"
    requests = []
    get_count = 0

    async def prompt(self, url, **kwargs):
        nonlocal get_count
        get_count += 1
        requests.append(("GET", url, kwargs))
        if get_count == 1:
            self.cookies.set("authentik_csrf", "csrf-token")
            return httpx.Response(200, json={"component": "ak-stage-prompt"},
                                 request=httpx.Request("GET", executor))
        if get_count == 2:
            assert str(url) == executor
            assert kwargs["headers"]["Cookie"] == "authentik_csrf=csrf-token"
            return httpx.Response(302, headers={"Location": executor + "?query="},
                                 request=httpx.Request("GET", url))
        assert str(url) == executor + "?query="
        return httpx.Response(200, json={"component": "ak-stage-email"},
                              request=httpx.Request("GET", url))

    async def submit(self, url, **kwargs):
        requests.append(("POST", url, kwargs))
        assert url == "/api/v3/flows/executor/fred-enrollment/"
        assert kwargs["headers"]["X-authentik-CSRF"] == "csrf-token"
        assert kwargs["json"]["username"] == "pyuteste"
        assert "group" not in kwargs["json"]
        return httpx.Response(302, headers={"Location": executor},
                              request=httpx.Request("POST", executor))
    monkeypatch.setattr(httpx.AsyncClient, "get", prompt)
    monkeypatch.setattr(httpx.AsyncClient, "post", submit)
    response = client.post("/api/auth/signup", json={"name": "pyuteste", "email": "player@example.com", "password": "long-password", "group": "fred-admins"},
                           headers={"Origin": "https://fred.nilvanlopes.com", "X-Fred-Request": "1"})
    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_sent"
    assert [method for method, _, _ in requests] == ["GET", "POST", "GET", "GET"]


def test_signup_rejects_redirect_outside_enrollment_executor(client, monkeypatch):
    executor = "http://server:9000/api/v3/flows/executor/fred-enrollment/"

    async def prompt(self, url, **kwargs):
        return httpx.Response(200, json={"component": "ak-stage-prompt"},
                              request=httpx.Request("GET", executor))

    async def submit(self, url, **kwargs):
        return httpx.Response(302, headers={"Location": "https://example.com/"},
                              request=httpx.Request("POST", executor))

    monkeypatch.setattr(httpx.AsyncClient, "get", prompt)
    monkeypatch.setattr(httpx.AsyncClient, "post", submit)
    response = client.post("/api/auth/signup", json={
        "name": "Jogador", "email": "player@example.com", "password": "long-password",
    }, headers={"Origin": "https://fred.nilvanlopes.com", "X-Fred-Request": "1"})
    assert response.status_code == 502
