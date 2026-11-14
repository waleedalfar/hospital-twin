"""asyncpg connection pool."""

import asyncpg
from asyncpg.pool import PoolConnectionProxy

type Pool = asyncpg.Pool[asyncpg.Record]
# A plain connection or one borrowed from a pool; both work everywhere a connection is needed.
type Conn = asyncpg.Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record]

ACQUIRE_TIMEOUT_S = 3.0


async def create_pool(dsn: str, min_size: int = 1, max_size: int = 10) -> Pool:
    """Open a connection pool to the database at `dsn`."""
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, timeout=ACQUIRE_TIMEOUT_S)
