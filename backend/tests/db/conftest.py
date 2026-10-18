"""Fixtures for the database-backed suite.

These tests run the real ASGI app against a real Postgres, migrated with
Alembic. They are skipped unless TEST_DATABASE_URL names a database the suite
may drop and recreate, e.g.

    TEST_DATABASE_URL=postgresql+asyncpg://insighteye:insighteye@localhost:5433/blocked_exit_test

Every test starts from an empty, freshly migrated schema.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]

DB_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    for item in items:
        if DB_DIR in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.db)


TABLES = (
    "alert",
    "blockage_event",
    "camera",
    "revoked_token",
    "workspace_member",
    "app_user",
    "workspace",
)


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _recreate_database() -> None:
    dsn = _dsn(TEST_DATABASE_URL)
    base, _, name = dsn.rpartition("/")
    conn = await asyncpg.connect(f"{base}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    import asyncio

    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    asyncio.run(_recreate_database())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def db(monkeypatch):
    """Point the app's session factory at the test database, on an empty schema.

    NullPool: pytest-asyncio gives each test its own event loop, and a pooled
    asyncpg connection cannot cross loops.
    """
    from app.core import database

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    conn = await asyncpg.connect(_dsn(TEST_DATABASE_URL))
    try:
        await conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()

    monkeypatch.setattr(database, "SessionFactory", factory)
    yield factory
    await engine.dispose()


@pytest.fixture
async def sql(db):
    """A raw asyncpg connection, for arranging rows the API cannot create."""
    conn = await asyncpg.connect(_dsn(TEST_DATABASE_URL))
    yield conn
    await conn.close()


@pytest.fixture
async def client(db):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver/api/v1"
    ) as client:
        yield client


PASSWORD = "Correct-Horse-9"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login(
    client: httpx.AsyncClient, username: str, password: str = PASSWORD
) -> str:
    response = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
async def superadmin(client) -> str:
    """Bootstrap the deployment; returns the superadmin's access token."""
    response = await client.post(
        "/auth/signup",
        json={"username": "root", "email": "root@example.com", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


@pytest.fixture
def make_user(client, superadmin):
    """Create an account via the superadmin API and return its access token."""

    async def _make(
        username: str,
        *,
        role: str = "user",
        workspace_id: int | None = None,
        workspace_role: str = "member",
    ) -> str:
        payload = {
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
            "role": role,
            "workspace_role": workspace_role,
        }
        if workspace_id is not None:
            payload["workspace_id"] = workspace_id
        response = await client.post(
            "/auth/users", json=payload, headers=bearer(superadmin)
        )
        assert response.status_code == 201, response.text
        return await login(client, username)

    return _make
