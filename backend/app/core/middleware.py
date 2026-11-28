"""HTTP middleware: request id + access log.

Pure ASGI (not BaseHTTPMiddleware) so it does not break streaming responses
or contextvars propagation.
"""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class BodySizeLimitMiddleware:
    """Reject request bodies over `max_bytes` before they are buffered or spooled.

    Checks Content-Length up front and counts streamed bytes (chunked uploads),
    so an oversized upload cannot fill memory or the temp directory.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "file_too_large",
                    "message": "Request body too large.",
                    "details": {"max_bytes": self.max_bytes},
                }
            }  # fmt: skip
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"connection", b"close")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not response_started:
                await self._reject(send)


class _BodyTooLargeError(Exception):
    pass


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((REQUEST_ID_HEADER.encode(), request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            path = scope.get("path", "")
            if not path.startswith("/health"):  # keep probes out of the log
                logger.info(
                    "%s %s %s %.1fms",
                    scope.get("method"),
                    path,
                    status_code,
                    duration_ms,
                    extra={"status": status_code, "duration_ms": duration_ms},
                )
            request_id_var.reset(token)


# ---------------------------------------------------------------------------
# Local request guard (ADR-016)
# ---------------------------------------------------------------------------
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Sent with every response: no MIME sniffing of downloads, never framed
# (clickjacking of the review/submit screen), no Referer leaking job URLs.
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"referrer-policy", b"no-referrer"),
)


def host_name(host_header: str) -> str:
    """The host part of a Host header, lowercased, without the port.

    `[::1]:8000` -> `::1`, `localhost:8000` -> `localhost`, `example.com` -> `example.com`.
    """
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 literal
        end = host.find("]")
        return host[1:end] if end > 0 else host
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def origin_host_port(origin: str) -> tuple[str, str] | None:
    """(scheme, host[:port]) of an Origin header, or None if it is not a web origin."""
    for scheme in ("http://", "https://"):
        if origin.startswith(scheme):
            rest = origin[len(scheme) :]
            if not rest or "/" in rest:
                return None
            return scheme[:-3], rest.lower()
    return None


class LocalRequestGuardMiddleware:
    """Protects an API that trusts every request from its own machine.

    * **Host allowlist** (DNS rebinding): a page on `evil.example` that re-resolves
      its name to 127.0.0.1 still sends `Host: evil.example`, so the request is
      refused before it reaches a route. `"*"` disables the check (only allowed
      with AUTH_MODE=api_key; see config).
    * **Cross-site writes** (CSRF): a browser on another site can send "simple"
      POSTs (forms, multipart uploads) to localhost without a CORS preflight.
      State-changing requests that carry an `Origin` must come from a configured
      frontend origin or from the API's own origin (Swagger UI); `Origin: null`
      and `Sec-Fetch-Site: cross-site` without an allowed origin are refused.
      Requests without either header (curl, scripts, server-to-server) pass:
      a browser always sends `Origin` on a cross-origin POST.
    """

    def __init__(
        self, app: ASGIApp, *, allowed_hosts: list[str], allowed_origins: list[str]
    ) -> None:
        self.app = app
        self.any_host = "*" in allowed_hosts
        self.allowed_hosts = frozenset(h.strip().lower().strip("[]") for h in allowed_hosts)
        self.allowed_origins = frozenset(o.rstrip("/").lower() for o in allowed_origins)

    async def _reject(self, send: Send, status: int, code: str, message: str) -> None:
        body = json.dumps({"error": {"code": code, "message": message, "details": None}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _origin_allowed(self, origin: str, host_header: str) -> bool:
        if origin.rstrip("/").lower() in self.allowed_origins:
            return True
        parsed = origin_host_port(origin)
        # Same origin as the API itself (e.g. the Swagger UI it serves).
        return parsed is not None and parsed[1] == host_header.strip().lower()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host_header = headers.get("host", "")
        if not self.any_host and host_name(host_header) not in self.allowed_hosts:
            logger.warning("refused request for host %r", host_header[:100])
            await self._reject(
                send, 400, "host_not_allowed",
                "This host name is not allowed. Use http://localhost or http://127.0.0.1 "
                "(or add it to ALLOWED_HOSTS).",
            )  # fmt: skip
            return
        if scope.get("method", "GET").upper() not in SAFE_METHODS:
            origin = headers.get("origin")
            fetch_site = headers.get("sec-fetch-site", "").lower()
            if origin is not None:
                allowed = origin != "null" and self._origin_allowed(origin, host_header)
            else:
                allowed = fetch_site != "cross-site"
            if not allowed:
                logger.warning("refused cross-site %s %s", scope.get("method"), scope.get("path"))
                await self._reject(
                    send, 403, "cross_site_request",
                    "Requests that change data must come from the app's own frontend "
                    "(CORS_ORIGINS).",
                )  # fmt: skip
                return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {bytes(k).lower() for k, _ in headers}
                headers.extend(h for h in SECURITY_HEADERS if h[0] not in present)
            await send(message)

        await self.app(scope, receive, send_with_headers)
