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


def with_sim(result: HealthResponse, request: Request) -> HealthResponse:
    """Add the simulation's state. A simulation that could not start makes the service degraded."""
    runtime = getattr(request.app.state, "runtime", None)
    error = getattr(request.app.state, "sim_error", None)
    if runtime is None:
        if error is None:
            return result
        return result.model_copy(update={"status": "degraded", "sim_error": error})
    if not runtime.ready:
        sim = "starting"
    elif runtime.frozen:
        sim = "frozen"
    elif runtime.paused:
        sim = "paused"
    else:
        sim = "running"
    ml = runtime.sim.ml
    ml_state = (
        "ready" if ml is not None else ("missing" if getattr(request.app.state, "ml_error", None) else "off")
    )
    return result.model_copy(
        update={
            "sim": sim,
            "sim_time": runtime.sim.now,
            "ml": ml_state,
            "ml_version": ml.model.version if ml else None,
        }
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    pool: Pool = request.app.state.pool
    result = with_sim(await check_database(pool), request)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
