"""Execute Fred's Authentik flow and complete its normal outpost OAuth callback."""
from __future__ import annotations

import re
from http.cookiejar import Cookie

import httpx


OUTPOST_START = "/outpost.goauthentik.io/start"
OUTPOST_CALLBACK = "/outpost.goauthentik.io/callback"
OUTPOST_SIGN_OUT = "/outpost.goauthentik.io/sign_out"
OUTPOST_COOKIE_NAME = re.compile(r"authentik_proxy_[a-f0-9]+")
AUTHORIZE = "/application/o/authorize/"
END_SESSION = "/application/o/fred/end-session/"
CANCEL_FLOW = "/flows/-/cancel/"
LOGIN_PAGE = "/if/flow/fred-authentication-flow/"
EXECUTOR = "/api/v3/flows/executor/fred-authentication-flow/"


class LoginDenied(Exception):
    pass


class HostedLoginRequired(Exception):
    pass


class LoginUnavailable(Exception):
    pass


def _same_origin(url: httpx.URL, origin: httpx.URL) -> bool:
    return url.scheme == origin.scheme and url.netloc == origin.netloc and not url.userinfo


def _check_target(url: httpx.URL, origin: httpx.URL, path: str) -> httpx.URL:
    if not _same_origin(url, origin) or url.raw_path.split(b"?", 1)[0] != path.encode() or url.fragment:
        raise LoginUnavailable()
    return url


class _InternalAuthTransport(httpx.AsyncBaseTransport):
    """Keep HTTPS cookie scoping while connecting over the private overlays."""

    def __init__(self, routes: dict[httpx.URL, httpx.URL], client_ip: str):
        self.routes = routes
        self.client_ip = client_ip
        self.transport = httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for origin, upstream in self.routes.items():
            if _same_origin(request.url, origin):
                break
        else:
            raise LoginUnavailable()
        headers = request.headers.copy()
        headers["X-Forwarded-Host"] = origin.netloc.decode()
        headers["X-Forwarded-Proto"] = origin.scheme
        headers["X-Forwarded-For"] = self.client_ip
        forwarded = httpx.Request(
            request.method, upstream.copy_with(raw_path=request.url.raw_path),
            headers=headers, stream=request.stream, extensions=request.extensions,
        )
        return await self.transport.handle_async_request(forwarded)

    async def aclose(self) -> None:
        await self.transport.aclose()


def _redirect(response: httpx.Response) -> httpx.URL:
    if response.status_code in {401, 403}:
        raise LoginDenied()
    target = response.headers.get("location")
    if response.status_code not in {302, 303} or not target:
        raise LoginUnavailable()
    return response.url.join(target)


async def _complete_flow(client: httpx.AsyncClient, flow_page: httpx.URL,
                         identifier: str, password: str) -> httpx.URL:
    executor = flow_page.join(EXECUTOR).copy_set_param("query", flow_page.query.decode())
    response = await client.get(executor)
    submitted = False
    for _ in range(8):
        if response.is_redirect:
            target = _redirect(response)
        else:
            if response.status_code in {401, 403}:
                raise LoginDenied()
            if not response.is_success and response.status_code != 400:
                raise LoginUnavailable()
            data = response.json()
            if not isinstance(data, dict):
                raise LoginUnavailable()
            stage = data.get("component")
            if data.get("response_errors") or data.get("non_field_errors") or stage == "ak-stage-access-denied":
                raise LoginDenied()
            if not response.is_success or not stage or stage == "ak-stage-flow-error":
                raise LoginUnavailable()
            if stage == "ak-stage-identification":
                if submitted:
                    raise LoginDenied()
                if data.get("captcha_stage") or data.get("password_fields") is not True:
                    raise HostedLoginRequired()
                submitted = True
                form = {"component": stage, "uid_field": identifier, "password": password}
            elif stage == "ak-stage-user-login" and submitted:
                form = {"component": stage, "remember_me": False}
            elif stage == "xak-flow-redirect" and isinstance(data.get("to"), str):
                target = response.url.join(data["to"])
                form = None
            else:
                raise HostedLoginRequired()
            if form is not None:
                headers = {
                    "Origin": f"{flow_page.scheme}://{flow_page.netloc.decode()}",
                    "Referer": str(flow_page),
                }
                csrf = client.cookies.get("authentik_csrf") or client.cookies.get("csrftoken")
                if csrf:
                    headers["X-authentik-CSRF"] = csrf
                response = await client.post(executor, json=form, headers=headers)
                continue

        if target.path == EXECUTOR:
            _check_target(target, flow_page, EXECUTOR)
            # Keep the original OAuth flow context for any stage-to-stage redirect.
            response = await client.get(executor)
        elif submitted:
            return _check_target(target, flow_page, AUTHORIZE)
        else:
            raise LoginUnavailable()
    raise LoginUnavailable()


async def password_cookie(*, portal_url: str, authentik_url: str, authentik_internal_url: str,
                          outpost_auth_url: str, client_ip: str, user_agent: str,
                          identifier: str, password: str) -> Cookie:
    portal = httpx.URL(portal_url)
    identity = httpx.URL(authentik_url)
    if portal.scheme != "https" or identity.scheme != "https" or _same_origin(portal, identity):
        raise LoginUnavailable()
    routes = {
        portal: httpx.URL(outpost_auth_url).copy_with(path="/", query=None),
        identity: httpx.URL(authentik_internal_url),
    }
    headers = {"User-Agent": user_agent} if user_agent.isascii() and 0 < len(user_agent) <= 512 else {}
    async with httpx.AsyncClient(
        transport=_InternalAuthTransport(routes, client_ip), headers=headers, timeout=5,
    ) as client:
        start = portal.join(OUTPOST_START).copy_set_param("rd", str(portal.join("/")))
        response = await client.get(start)
        authorize = _check_target(_redirect(response), identity, AUTHORIZE)
        response = await client.get(authorize)
        flow_page = _check_target(_redirect(response), identity, LOGIN_PAGE)
        resume = await _complete_flow(client, flow_page, identifier, password)
        response = await client.get(resume)
        callback = _redirect(response)
        if _same_origin(callback, identity) and callback.path.startswith("/if/flow/"):
            raise HostedLoginRequired()
        _check_target(callback, portal, OUTPOST_CALLBACK)
        if callback.params.get("error"):
            raise LoginDenied()
        state = authorize.params.get("state")
        if not callback.params.get("code") or not state or callback.params.get("state") != state:
            raise LoginUnavailable()
        response = await client.get(callback)
        _check_target(_redirect(response), portal, "/")
        # Only accept the outpost cookie minted by this callback for Fred.
        for cookie in response.cookies.jar:
            if (cookie.domain.lstrip(".") == portal.host and cookie.path == "/" and cookie.secure
                    and OUTPOST_COOKIE_NAME.fullmatch(cookie.name)
                    and cookie.value and not cookie.is_expired()):
                return cookie
    raise LoginUnavailable()


async def logout_redirect(*, portal_url: str, authentik_url: str,
                          outpost_auth_url: str, cookie_header: str | None) -> str:
    portal = httpx.URL(portal_url)
    identity = httpx.URL(authentik_url)
    sign_out = httpx.URL(outpost_auth_url).copy_with(path=OUTPOST_SIGN_OUT, query=None)
    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
        response = await client.get(sign_out, headers={
            "Cookie": cookie_header or "",
            "Host": portal.netloc.decode(),
            "X-Forwarded-Host": portal.netloc.decode(),
            "X-Forwarded-Proto": portal.scheme,
        })
    target = _redirect(response)
    if _same_origin(target, portal) and target.path == OUTPOST_START:
        # With an expired session the outpost attempts to log in again.
        return str(portal.join("/"))

    _check_target(target, identity, END_SESSION)
    # Authentik 2026.8 skips end-session when the browser has an unfinished flow.
    # Its cancel route clears that plan before continuing to the provider's logout.
    return str(identity.join(CANCEL_FLOW).copy_set_param("next", target.raw_path.decode()))
