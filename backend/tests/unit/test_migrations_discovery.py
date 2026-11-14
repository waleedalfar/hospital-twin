from pathlib import Path

import pytest

from twin.db.migrate import MIGRATIONS_DIR, Migration, MigrationError, discover_migrations


def write(directory: Path, name: str, sql: str = "SELECT 1;") -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_migrations_are_sorted_by_version(tmp_path: Path) -> None:
    write(tmp_path, "0010_later.sql")
    write(tmp_path, "0002_second.sql")
    write(tmp_path, "0001_first.sql")
    found = discover_migrations(tmp_path)
    assert [(m.version, m.name) for m in found] == [(1, "first"), (2, "second"), (10, "later")]


def test_non_sql_files_are_ignored(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql")
    write(tmp_path, "notes.txt")
    assert [m.version for m in discover_migrations(tmp_path)] == [1]


@pytest.mark.parametrize("name", ["first.sql", "1_first.sql", "0001-First.sql", "0001_First.sql"])
def test_bad_file_names_are_rejected(tmp_path: Path, name: str) -> None:
    write(tmp_path, name)
    with pytest.raises(MigrationError, match="Bad migration file name"):
        discover_migrations(tmp_path)


def test_empty_migration_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "  \n")
    with pytest.raises(MigrationError, match="is empty"):
        discover_migrations(tmp_path)


def test_duplicate_versions_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql")
    write(tmp_path, "0001_other.sql")
    with pytest.raises(MigrationError, match="Duplicate migration versions"):
        discover_migrations(tmp_path)


def test_checksum_changes_with_content() -> None:
    assert Migration(1, "a", "SELECT 1;").checksum != Migration(1, "a", "SELECT 2;").checksum
    assert Migration(1, "a", "SELECT 1;").checksum == Migration(2, "b", "SELECT 1;").checksum


def test_real_migrations_are_valid_and_contiguous() -> None:
    found = discover_migrations(MIGRATIONS_DIR)
    assert found, "at least one migration must exist"
    assert [m.version for m in found] == list(range(1, len(found) + 1))
