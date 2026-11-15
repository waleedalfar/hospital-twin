"""SQL migration runner.

Files in `migrations/` are named `NNNN_name.sql`, applied in numeric order, each in one transaction, and
recorded in `schema_migrations`. Running it again applies nothing. Editing an applied file is an error.
"""

import asyncio
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from twin.common.config import get_settings
from twin.common.logging import configure_logging
from twin.db.reference import ReferenceCounts, sync_reference
from twin.sim.layout_model import load_layout

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_FILE_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
CONNECT_ATTEMPTS = 30
CONNECT_DELAY_S = 1.0

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer PRIMARY KEY,
    name       text NOT NULL,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    """A migration file is invalid or conflicts with what the database has recorded."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Read every migration file in `directory`, sorted by version."""
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME.match(path.name)
        if match is None:
            raise MigrationError(f"Bad migration file name {path.name!r}; expected NNNN_name.sql")
        sql = path.read_text(encoding="utf-8")
        if not sql.strip():
            raise MigrationError(f"Migration {path.name} is empty")
        migrations.append(Migration(version=int(match["version"]), name=match["name"], sql=sql))
    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    duplicates = sorted({version for version in versions if versions.count(version) > 1})
    if duplicates:
        raise MigrationError(f"Duplicate migration versions: {duplicates}")
    return migrations


async def apply_migrations(conn: asyncpg.Connection, migrations: list[Migration]) -> list[Migration]:
    """Apply the migrations that the database has not recorded yet. Returns the ones applied."""
    await conn.execute(_CREATE_TRACKING_TABLE)
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    recorded: dict[int, str] = {row["version"]: row["checksum"] for row in rows}
    applied: list[Migration] = []
    for migration in migrations:
        known_checksum = recorded.get(migration.version)
        if known_checksum is not None:
            if known_checksum != migration.checksum:
                raise MigrationError(f"Migration {migration.version:04d}_{migration.name} was changed after it was applied")
            continue
        async with conn.transaction():
            await conn.execute(migration.sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES ($1, $2, $3)",
                migration.version,
                migration.name,
                migration.checksum,
            )
        logger.info("Applied migration %04d_%s", migration.version, migration.name)
        applied.append(migration)
    return applied


async def connect_with_retry(dsn: str, attempts: int = CONNECT_ATTEMPTS, delay_s: float = CONNECT_DELAY_S) -> asyncpg.Connection:
    """Connect to the database, waiting for it to accept connections (it may still be starting)."""
    for attempt in range(1, attempts + 1):
        try:
            return await asyncpg.connect(dsn)
        except (OSError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError) as error:
            if attempt == attempts:
                raise
            logger.info("Database not ready (attempt %d/%d): %s", attempt, attempts, error)
            await asyncio.sleep(delay_s)
    raise MigrationError("attempts must be at least 1")


async def run(dsn: str, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Connect to `dsn` and apply all pending migrations from `directory`."""
    migrations = discover_migrations(directory)
    conn = await connect_with_retry(dsn)
    try:
        return await apply_migrations(conn, migrations)
    finally:
        await conn.close()


async def migrate_and_sync(dsn: str) -> tuple[list[Migration], ReferenceCounts]:
    """Apply pending migrations, then copy the building from shared/layout.json into the reference tables."""
    migrations = discover_migrations()
    conn = await connect_with_retry(dsn)
    try:
        applied = await apply_migrations(conn, migrations)
        counts = await sync_reference(conn, load_layout())
    finally:
        await conn.close()
    return applied, counts


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    applied, counts = asyncio.run(migrate_and_sync(settings.database_url.get_secret_value()))
    logger.info("Migrations complete: %d applied in this run", len(applied))
    logger.info(
        "Reference data synced from layout.json: %d hospitals, %d units, %d rooms, %d beds",
        counts.hospitals,
        counts.units,
        counts.rooms,
        counts.beds,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
