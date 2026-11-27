"""App wiring without a database: auth, errors, middleware, OpenAPI."""

import re
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError

KEY = "k" * 40


async def test_liveness(make_app, client_for):
    async with client_for(make_app()) as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_no_auth_mode_acts_as_owner(make_app, client_for):
    async with client_for(make_app()) as c:
        r = await c.get("/api/v1/system/info")
    assert r.status_code == 200
    assert r.json()["user"] == "owner" and r.json()["auth_mode"] == "none"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 401),
        ({"X-API-Key": "wrong"}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"X-API-Key": KEY}, 200),
        ({"Authorization": f"Bearer {KEY}"}, 200),
    ],
)
async def test_api_key_mode(make_app, client_for, headers, expected):
    app = make_app(auth_mode="api_key", api_key=KEY)
    async with client_for(app) as c:
        r = await c.get("/api/v1/system/info", headers=headers)
        health = await c.get("/health")
    assert r.status_code == expected
    if expected == 401:
        assert r.json()["error"]["code"] == "unauthorized"
    assert health.status_code == 200  # probes stay open


async def test_every_v1_operation_requires_auth(make_app, client_for):
    """Behavioural guard: no /api/v1 operation in the spec is reachable without the key."""
    app = make_app(auth_mode="api_key", api_key=KEY)
    ops = [
        (method, re.sub(r"\{[^}]+\}", "x", path))
        for path, item in app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in item
    ]
    assert len(ops) >= 6
    async with client_for(app) as c:
        for method, path in ops:
            r = await c.request(method.upper(), path, json={})
            assert r.status_code == 401, (method, path, r.status_code)


async def test_unknown_route_uses_error_envelope(make_app, client_for):
    async with client_for(make_app()) as c:
        r = await c.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Not Found", "details": None}}


async def test_domain_and_unhandled_errors(make_app, client_for):
    app = make_app()

    @app.get("/boom/conflict")
    async def conflict():
        raise ConflictError("taken", {"id": 1})

    @app.get("/boom/crash")
    async def crash():
        raise RuntimeError("secret internals")

    async with client_for(app) as c:
        r1 = await c.get("/boom/conflict")
        r2 = await c.get("/boom/crash")
    assert r1.status_code == 409
    assert r1.json()["error"] == {"code": "conflict", "message": "taken", "details": {"id": 1}}
    assert r2.status_code == 500
    assert "secret" not in r2.text


@pytest.mark.parametrize(
    ("sqlstate", "status", "code"),
    [("23505", 409, "conflict"), ("23503", 409, "conflict"), ("23514", 422, "validation_error")],
)
async def test_integrity_errors_mapped(make_app, client_for, sqlstate, status, code):
    app = make_app()
    orig = SimpleNamespace(sqlstate=sqlstate, constraint_name="ck_x")

    @app.get("/boom/db")
    async def db():
        raise IntegrityError("stmt", {}, orig)  # type: ignore[arg-type]

    async with client_for(app) as c:
        r = await c.get("/boom/db")
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["details"] == {"constraint": "ck_x"}


async def test_request_id_echoed_or_generated(make_app, client_for):
    async with client_for(make_app()) as c:
        given = await c.get("/health", headers={"X-Request-ID": "abc-123"})
        bad = await c.get("/health", headers={"X-Request-ID": "has spaces\nand newline"})
    assert given.headers["x-request-id"] == "abc-123"
    assert bad.headers["x-request-id"] != "has spaces\nand newline"
    assert len(bad.headers["x-request-id"]) == 32


async def test_cors_allows_only_configured_origins(make_app, client_for):
    app = make_app(cors_origins=["http://localhost:3000"])
    pre = {"Access-Control-Request-Method": "PATCH"}
    async with client_for(app) as c:
        ok = await c.options("/api/v1/settings", headers={"Origin": "http://localhost:3000", **pre})
        bad = await c.options("/api/v1/settings", headers={"Origin": "http://evil.test", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


async def test_openapi_is_versioned_and_documents_auth(make_app, client_for):
    async with client_for(make_app()) as c:
        spec = (await c.get("/api/v1/openapi.json")).json()
        assert (await c.get("/openapi.json")).status_code == 404
    assert spec["info"]["title"] == "AI Job Hunter API"
    assert "/api/v1/settings" in spec["paths"] and "/health/ready" in spec["paths"]
    assert {"ApiKeyHeader", "BearerToken"} <= set(spec["components"]["securitySchemes"])
    assert "ErrorResponse" in spec["components"]["schemas"]


async def test_docs_can_be_disabled(make_app, client_for):
    async with client_for(make_app(docs_enabled=False)) as c:
        assert (await c.get("/api/v1/openapi.json")).status_code == 404
        assert (await c.get("/api/v1/docs")).status_code == 404
