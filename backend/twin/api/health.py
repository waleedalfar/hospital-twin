"""`GET /health`: reports whether the API can reach the database and what it finds there."""

import logging

import asyncpg
from fastapi import APIRouter, Request, Response, status

from twin.common.logging import redact_dsn
from twin.common.schemas import HealthResponse
from twin.db.pool import ACQUIRE_TIMEOUT_S, Pool

logger = logging.getLogger(__name__)
router = APIRouter()

DB_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError)


async def check_database(pool: Pool) -> HealthResponse:
    """Query the database for the TimescaleDB version and the number of applied migrations."""
    try:
        async with pool.acquire(timeout=ACQUIRE_TIMEOUT_S) as conn:
            version = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            migrations = await conn.fetchval("SELECT count(*) FROM schema_migrations")
    except DB_ERRORS as error:
        logger.exception("Health check could not read the database")
        detail = redact_dsn(f"{type(error).__name__}: {error}")
        return HealthResponse(status="degraded", db="error", error=detail)
    if version is None:
        return HealthResponse(
            status="degraded",
            db="error",
            migrations_applied=int(migrations),
            error="TimescaleDB extension is not installed",
        )
    return HealthResponse(
        status="ok", db="ok", timescaledb_version=str(version), migrations_applied=int(migrations)
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    pool: Pool = request.app.state.pool
    result = await check_database(pool)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
