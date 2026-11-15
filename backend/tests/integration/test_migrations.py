"""Migrations against a real, empty TimescaleDB database."""

import logging
from pathlib import Path

import asyncpg
import pytest

from twin.common.config import get_settings
from twin.db import migrate
from twin.db.migrate import MIGRATIONS_DIR, MigrationError, discover_migrations


async def fetch_versions(dsn: str) -> list[int]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        return [row["version"] for row in rows]
    finally:
        await conn.close()


async def test_migrations_apply_on_an_empty_database(empty_db_url: str) -> None:
    expected = [m.version for m in discover_migrations(MIGRATIONS_DIR)]
    applied = await migrate.run(empty_db_url)
    assert [m.version for m in applied] == expected
    assert await fetch_versions(empty_db_url) == expected

    conn = await asyncpg.connect(empty_db_url)
    try:
        version = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
    finally:
        await conn.close()
    assert version is not None
    assert version.startswith("2.")


async def test_running_again_applies_nothing(empty_db_url: str) -> None:
    await migrate.run(empty_db_url)
    before = await fetch_versions(empty_db_url)
    assert await migrate.run(empty_db_url) == []
    assert await fetch_versions(empty_db_url) == before


async def test_only_new_migrations_are_applied(empty_db_url: str, tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int);", encoding="utf-8")
    assert [m.name for m in await migrate.run(empty_db_url, tmp_path)] == ["a"]
    (tmp_path / "0002_b.sql").write_text("CREATE TABLE b (id int);", encoding="utf-8")
    assert [m.name for m in await migrate.run(empty_db_url, tmp_path)] == ["b"]
    assert await fetch_versions(empty_db_url) == [1, 2]


async def test_failed_migration_rolls_back_and_is_not_recorded(empty_db_url: str, tmp_path: Path) -> None:
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE ok (id int);", encoding="utf-8")
    (tmp_path / "0002_broken.sql").write_text("CREATE TABLE half_done (id int); SELECT * FROM table_that_does_not_exist;", encoding="utf-8")
    with pytest.raises(asyncpg.UndefinedTableError):
        await migrate.run(empty_db_url, tmp_path)
    assert await fetch_versions(empty_db_url) == [1]
    conn = await asyncpg.connect(empty_db_url)
    try:
        assert await conn.fetchval("SELECT to_regclass('public.half_done')") is None
        assert await conn.fetchval("SELECT to_regclass('public.ok')") == "ok"
    finally:
        await conn.close()


async def test_editing_an_applied_migration_is_an_error(empty_db_url: str, tmp_path: Path) -> None:
    path = tmp_path / "0001_a.sql"
    path.write_text("CREATE TABLE a (id int);", encoding="utf-8")
    await migrate.run(empty_db_url, tmp_path)
    path.write_text("CREATE TABLE a (id bigint);", encoding="utf-8")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        await migrate.run(empty_db_url, tmp_path)


async def test_connect_with_retry_gives_up_on_a_closed_port() -> None:
    with pytest.raises(OSError, match=r"."):
        await migrate.connect_with_retry("postgresql://twin:twin@127.0.0.1:1/none", attempts=2, delay_s=0.01)


async def test_connect_with_retry_rejects_zero_attempts() -> None:
    with pytest.raises(MigrationError, match="at least 1"):
        await migrate.connect_with_retry("postgresql://twin:twin@127.0.0.1:1/none", attempts=0)


def test_main_reads_database_url_from_settings(empty_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    monkeypatch.setenv("DATABASE_URL", empty_db_url)
    get_settings.cache_clear()
    try:
        assert migrate.main() == 0
    finally:
        get_settings.cache_clear()
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in handlers:
            root.addHandler(handler)
        root.setLevel(level)
