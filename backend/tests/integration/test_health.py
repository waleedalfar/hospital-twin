"""`GET /health` against a real TimescaleDB database."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
from pydantic import SecretStr

from twin.api.app import APP_TITLE, create_app
from twin.common.config import Settings
from twin.common.schemas import HealthResponse
from twin.db import migrate
from twin.db.migrate import MIGRATIONS_DIR, discover_migrations


@asynccontextmanager
async def running_client(dsn: str) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(_env_file=None, database_url=SecretStr(dsn))
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_health_reports_database_state(empty_db_url: str) -> None:
    await migrate.run(empty_db_url)
    async with running_client(empty_db_url) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = HealthResponse.model_validate(response.json())
    assert body.status == "ok"
    assert body.db == "ok"
    assert body.migrations_applied == len(discover_migrations(MIGRATIONS_DIR))
    assert body.error is None

    conn = await asyncpg.connect(empty_db_url)
    try:
        version = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
    finally:
        await conn.close()
    assert body.timescaledb_version == version


async def test_health_is_degraded_when_migrations_have_not_run(empty_db_url: str) -> None:
    async with running_client(empty_db_url) as client:
        response = await client.get("/health")
    assert response.status_code == 503
    body = HealthResponse.model_validate(response.json())
    assert body.status == "degraded"
    assert body.db == "error"
    assert body.error is not None
    assert "schema_migrations" in body.error


async def test_health_is_degraded_without_timescaledb(empty_db_url: str) -> None:
    await migrate.run(empty_db_url)
    conn = await asyncpg.connect(empty_db_url)
    try:
        await conn.execute("DROP EXTENSION timescaledb CASCADE")
    finally:
        await conn.close()
    async with running_client(empty_db_url) as client:
        response = await client.get("/health")
    assert response.status_code == 503
    body = HealthResponse.model_validate(response.json())
    assert body.db == "error"
    assert body.error == "TimescaleDB extension is not installed"
    assert body.migrations_applied == len(discover_migrations(MIGRATIONS_DIR))


async def test_health_is_degraded_when_the_database_goes_away(empty_db_url: str) -> None:
    await migrate.run(empty_db_url)
    database = empty_db_url.rsplit("/", 1)[1]
    admin_url = empty_db_url.rsplit("/", 1)[0] + "/postgres"
    async with running_client(empty_db_url) as client:
        assert (await client.get("/health")).status_code == 200
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        finally:
            await admin.close()
        response = await client.get("/health")
    assert response.status_code == 503
    body = HealthResponse.model_validate(response.json())
    assert body.status == "degraded"
    assert body.error is not None
    assert "twin:twin@" not in body.error


def test_asgi_entry_point_builds_the_app() -> None:
    from twin.api.main import app

    assert app.title == APP_TITLE
    assert "/health" in app.openapi()["paths"]
