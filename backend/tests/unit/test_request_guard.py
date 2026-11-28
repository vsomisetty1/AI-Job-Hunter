"""Local request guard (ADR-016): Host allowlist and cross-site write protection.

The API trusts every request from this machine (AUTH_MODE=none), so a web page
on another site must not be able to reach it through the user's browser.
"""

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.middleware import host_name, origin_host_port

FRONTEND = "http://localhost:3000"


def client(app, host: str = "127.0.0.1:8000") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url=f"http://{host}",
    )


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("localhost:8000", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("[::1]:8000", "::1"),
        ("LOCALHOST", "localhost"),
        ("evil.example:8000", "evil.example"),
        ("", ""),
    ],
)
def test_host_name(header, expected):
    assert host_name(header) == expected


def test_origin_parsing():
    assert origin_host_port("http://localhost:3000") == ("http", "localhost:3000")
    assert origin_host_port("https://a.test") == ("https", "a.test")
    assert origin_host_port("null") is None
    assert origin_host_port("file://x") is None
    assert origin_host_port("http://a.test/path") is None


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "localhost"])
async def test_loopback_hosts_are_served(make_app, host):
    async with client(make_app(), host) as c:
        r = await c.get("/api/v1/system/info")
    assert r.status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "rebind.attacker.test:8000", "192.168.1.20:8000"])
async def test_dns_rebinding_hosts_are_refused(make_app, host):
    """A rebinding page reaches 127.0.0.1 with its own name in the Host header."""
    async with client(make_app(), host) as c:
        r = await c.get("/api/v1/resumes")
        probe = await c.get("/health")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "host_not_allowed"
    assert probe.status_code == 400  # nothing is answered for a foreign name


async def test_extra_allowed_host(make_app):
    app = make_app(allowed_hosts=["localhost", "127.0.0.1", "jobs.lan"])
    async with client(app, "jobs.lan:8000") as c:
        assert (await c.get("/health")).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},  # sandboxed iframe, file:// page
        {"Origin": "http://localhost:3001"},  # another local app
        {"Sec-Fetch-Site": "cross-site"},  # browser hid the origin
        {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    ],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/discovery/runs"),
        ("POST", "/api/v1/resumes"),
        ("PATCH", "/api/v1/settings"),
        ("DELETE", "/api/v1/packages/00000000-0000-0000-0000-000000000000"),
        ("PUT", "/api/v1/insights/recommendations/x/state"),
    ],
)
async def test_cross_site_writes_are_refused(make_app, method, path, headers):
    async with client(make_app(cors_origins=[FRONTEND])) as c:
        r = await c.request(method, path, headers=headers, content=b"x")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_site_request"


async def test_cross_site_reads_are_left_to_cors(make_app):
    """A GET cannot change anything, and CORS keeps its response unreadable."""
    async with client(make_app(cors_origins=[FRONTEND])) as c:
        r = await c.get("/api/v1/system/info", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": FRONTEND, "Sec-Fetch-Site": "same-site"},  # the app's own frontend
        {"Origin": FRONTEND + "/"},
        {"Origin": "http://127.0.0.1:8000"},  # Swagger UI served by the API itself
        {},  # curl, scripts
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},  # typed into the address bar / bookmark
    ],
)
async def test_allowed_writes_reach_the_route(make_app, headers):
    app = make_app(cors_origins=[FRONTEND])

    async def echo() -> dict[str, bool]:
        return {"reached": True}

    app.add_api_route("/echo", echo, methods=["POST", "DELETE"])
    async with client(app) as c:
        r = await c.post("/echo", headers=headers)
        d = await c.delete("/echo", headers=headers)
    assert r.status_code == 200 and r.json() == {"reached": True}
    assert d.status_code == 200


async def test_guard_applies_in_api_key_mode_too(make_app):
    app = make_app(auth_mode="api_key", api_key="k" * 40, cors_origins=[FRONTEND])
    async with client(app) as c:
        r = await c.post(
            "/api/v1/discovery/runs",
            headers={"Origin": "https://evil.example", "X-API-Key": "k" * 40},
        )
    assert r.status_code == 403


def make(**kw) -> Settings:
    kw.setdefault("database_url", "postgresql://u:p@localhost/db")
    return Settings(_env_file=None, **kw)


def test_wildcard_hosts_need_api_key():
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        make(allowed_hosts=["*"])
    assert make(allowed_hosts=["*"], auth_mode="api_key", api_key="k" * 32).allowed_hosts == ["*"]


def test_allowed_hosts_from_comma_string(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost, jobs.lan,")
    assert make().allowed_hosts == ["localhost", "jobs.lan"]


def test_empty_allowed_hosts_refused():
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        make(allowed_hosts=[])


def test_container_flag_allows_wildcard_bind_without_auth():
    """Inside the container image only; Compose publishes the port on 127.0.0.1."""
    with pytest.raises(ValidationError, match="AUTH_MODE=none"):
        make(backend_host="0.0.0.0")
    s = make(backend_host="0.0.0.0", container_loopback_only=True)
    assert s.auth_mode == "none" and s.allowed_hosts == ["localhost", "127.0.0.1", "::1"]


async def test_security_headers_on_every_response(make_app):
    async with client(make_app()) as c:
        for r in (await c.get("/health"), await c.get("/api/v1/nope")):
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["x-frame-options"] == "DENY"
            assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
            assert r.headers["referrer-policy"] == "no-referrer"


async def test_security_headers_do_not_duplicate_a_routes_own(make_app):
    app = make_app()

    async def framed():
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("x", headers={"X-Frame-Options": "SAMEORIGIN"})

    app.add_api_route("/own", framed)
    async with client(app) as c:
        r = await c.get("/own")
    assert r.headers.get_list("x-frame-options") == ["SAMEORIGIN"]
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
