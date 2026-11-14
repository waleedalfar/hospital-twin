"""asyncpg connection pool."""

import asyncpg

type Pool = asyncpg.Pool[asyncpg.Record]

ACQUIRE_TIMEOUT_S = 3.0


async def create_pool(dsn: str, min_size: int = 1, max_size: int = 10) -> Pool:
    """Open a connection pool to the database at `dsn`."""
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, timeout=ACQUIRE_TIMEOUT_S)
