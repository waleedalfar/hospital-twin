"""Shared test setup.

Integration tests use the real TimescaleDB from `infra/docker-compose.test.yml`. Each test gets its own
freshly created database, so tests never see each other's data.
"""

import os
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

DEFAULT_TEST_DATABASE_URL = "postgresql://twin:twin@localhost:5434/twin_test"
NOT_RUN_OUTCOMES = ("skipped", "xfailed", "xpassed", "deselected")


def test_server_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


@pytest.fixture
async def empty_db_url() -> AsyncIterator[str]:
    """URL of a brand-new, empty database on the test server. Dropped after the test."""
    server_url = test_server_url()
    name = f"twin_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(server_url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        yield with_database(server_url, name)
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run if any test did not actually run (CLAUDE.md §2: zero skipped tests)."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    not_run = {outcome: len(reporter.stats.get(outcome, [])) for outcome in NOT_RUN_OUTCOMES}
    total = sum(not_run.values())
    if total and exitstatus == pytest.ExitCode.OK:
        reporter.write_line(f"FAILED: {total} test(s) did not run: {not_run}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
