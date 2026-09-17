"""HTTP surface: auth, error mapping, health, and the zone-editor endpoints.

Runs the real ASGI app in-process. The database dependency is overridden, so
these need no Postgres — the routes exercised here either do not touch it or
are stopped by the auth guard before they would.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.exceptions import NotFoundError
from app.main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


# -- health ---------------------------------------------------------------
async def test_health_is_public_and_names_the_build(client: httpx.AsyncClient):
    """Liveness must answer without a token, or the orchestrator kills a
    healthy container because its own probe cannot log in."""
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["env"]


# -- the bearer-token guard -------------------------------------------------
# Full round-trips (signup/login/a real token accepted) need a database and
# belong in an integration suite run against real Postgres; see
# tests/test_auth.py for the DB-free parts (hashing, token encode/decode,
# revocation bookkeeping) and the plan's tenancy verification steps for the
# rest. What is testable here, with no database, is that the guard actually
# guards: a request with nothing, or something unusable, is rejected before
# any route logic runs.
async def test_a_protected_route_rejects_a_missing_token(client: httpx.AsyncClient):
    response = await client.get("/api/v1/monitoring/status")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_a_protected_route_rejects_a_malformed_token(client: httpx.AsyncClient):
    response = await client.get(
        "/api/v1/monitoring/status", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_a_protected_route_rejects_a_well_formed_but_invalid_token(
    client: httpx.AsyncClient,
):
    """Right shape (three dot-separated segments), wrong signature."""
    response = await client.get(
        "/api/v1/monitoring/status",
        headers={"Authorization": "Bearer aaaa.bbbb.cccc"},
    )
    assert response.status_code == 401


# -- error mapping --------------------------------------------------------
async def test_domain_errors_become_their_http_status(client: httpx.AsyncClient):
    async def missing():
        raise NotFoundError("Camera 999 not found")

    app.router.get("/__test_not_found")(missing)
    try:
        response = await client.get("/__test_not_found")
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__test_not_found"
        ]

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "not_found"
    assert body["message"] == "Camera 999 not found"


async def test_unhandled_errors_do_not_leak_internals():
    """A stack trace or a connection string must never reach the client."""

    async def boom():
        raise RuntimeError("connection string: postgres://user:hunter2@db/x")

    app.router.get("/__test_boom")(boom)
    # raise_app_exceptions=False makes the transport return the handler's
    # response instead of re-raising, which is what a real server does.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/__test_boom")
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__test_boom"
        ]

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "internal_error"
    assert body["message"] == "An unexpected error occurred."
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text


# -- the zone editor ------------------------------------------------------
async def test_the_editor_page_is_served(client: httpx.AsyncClient):
    response = await client.get("/ui/zone-editor.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_the_editor_page_is_self_contained(client: httpx.AsyncClient):
    """No CDN, no build step — it has to work on an air-gapped site network."""
    body = (await client.get("/ui/zone-editor.html")).text

    assert "http://" not in body.replace("http://localhost", "")
    assert "https://" not in body
    assert "<script" in body and "src=" not in body.split("<script")[1][:200]


async def test_the_editor_posts_pixels_with_the_frame_size(client: httpx.AsyncClient):
    """The contract that keeps the client free of conversion maths."""
    body = (await client.get("/ui/zone-editor.html")).text

    assert "frame_width" in body and "frame_height" in body
    assert "door-polygon" in body


async def test_root_redirects_somewhere_useful(client: httpx.AsyncClient):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code in (307, 302)
    assert response.headers["location"] in (
        "/docs",
        "/ui/zone-editor.html",
        "/api/v1/health",
    )
