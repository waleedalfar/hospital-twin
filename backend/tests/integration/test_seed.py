"""Loading Synthea bundles into the patients table."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest

from tests.fhir_fixtures import condition, patient_bundle, write_bundles
from twin.common.config import get_settings
from twin.db import seed, synthea
from twin.db.fhir import FhirError


@pytest.fixture
def clean_process_state() -> Iterator[None]:
    """`main()` configures logging and caches settings; put both back afterwards."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def sample_bundles() -> list[dict[str, object]]:
    return [
        patient_bundle("ccc", gender="male", birth_date="1946-11-14", conditions=[condition("Asthma")]),
        patient_bundle("aaa", birth_date="2000-01-01", conditions=[]),
        patient_bundle("ddd", deceased=True),
        patient_bundle(
            "bbb",
            birth_date="1970-06-30",
            conditions=[
                condition("Essential hypertension (disorder)"),
                condition("Diabetes mellitus type 2 (disorder)"),
            ],
        ),
    ]


def test_patient_ids_are_four_digit_p_numbers() -> None:
    assert [seed.patient_id(i) for i in (0, 8, 411, 2999)] == ["P-0001", "P-0009", "P-0412", "P-3000"]


def test_read_records_sorts_by_synthea_id_and_skips_non_patient_files(tmp_path: Path) -> None:
    directory = write_bundles(tmp_path / "fhir", sample_bundles())
    (directory / "hospitalInformation123.json").write_text(
        '{"resourceType": "Bundle", "entry": []}', encoding="utf-8"
    )
    (directory / "practitionerInformation123.json").write_text("{}", encoding="utf-8")
    records, files, deceased = seed.read_records(directory)
    assert [r.synthea_id for r in records] == ["aaa", "bbb", "ccc"]
    assert (files, deceased) == (4, 1)


def test_read_records_fails_loudly_on_a_broken_bundle(tmp_path: Path) -> None:
    directory = write_bundles(tmp_path / "fhir", sample_bundles())
    (directory / "Broken.json").write_text('{"resourceType": "Bundle", "entry": []}', encoding="utf-8")
    with pytest.raises(FhirError):
        seed.read_records(directory)


async def test_seed_loads_patients_with_fhir_and_extracted_fields(
    migrated_db_url: str, tmp_path: Path
) -> None:
    directory = write_bundles(tmp_path / "fhir", sample_bundles())
    result = await seed.seed_from_directory(migrated_db_url, directory)
    assert (result.files, result.loaded, result.deceased) == (4, 3, 1)
    conn = await asyncpg.connect(migrated_db_url)
    try:
        rows = await conn.fetch(
            "SELECT id, synthea_id, age, sex, comorbidity_count, conditions, fhir FROM patients ORDER BY id"
        )
    finally:
        await conn.close()
    assert [(r["id"], r["synthea_id"], r["age"], r["sex"], r["comorbidity_count"]) for r in rows] == [
        ("P-0001", "aaa", 26, "female", 0),
        ("P-0002", "bbb", 56, "female", 2),
        ("P-0003", "ccc", 80, "male", 1),
    ]
    assert rows[1]["conditions"] == [
        "Diabetes mellitus type 2 (disorder)",
        "Essential hypertension (disorder)",
    ]
    fhir = json.loads(rows[1]["fhir"])
    assert [entry["resource"]["resourceType"] for entry in fhir["entry"]] == [
        "Patient",
        "Condition",
        "Condition",
    ]
    assert fhir["entry"][0]["resource"]["id"] == "bbb"


async def test_seeding_again_is_stable_and_a_changed_set_replaces_the_old_one(
    migrated_db_url: str, tmp_path: Path
) -> None:
    first = write_bundles(tmp_path / "one", sample_bundles())
    await seed.seed_from_directory(migrated_db_url, first)
    again = await seed.seed_from_directory(migrated_db_url, first)
    assert again.loaded == 3

    second = write_bundles(
        tmp_path / "two", [patient_bundle("bbb", birth_date="1970-06-30"), patient_bundle("zzz")]
    )
    await seed.seed_from_directory(migrated_db_url, second)
    conn = await asyncpg.connect(migrated_db_url)
    try:
        rows = await conn.fetch("SELECT id, synthea_id FROM patients ORDER BY id")
    finally:
        await conn.close()
    assert [(r["id"], r["synthea_id"]) for r in rows] == [("P-0001", "bbb"), ("P-0002", "zzz")]


@pytest.mark.usefixtures("clean_process_state")
def test_main_reuses_existing_synthea_output_and_reports_the_count(
    migrated_db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "synthea"
    write_bundles(data_dir / "fhir", sample_bundles())
    (data_dir / synthea.MARKER_NAME).write_text(json.dumps(synthea.marker_for(4, 99)), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    monkeypatch.setenv("SYNTHEA_POPULATION", "4")
    monkeypatch.setenv("SYNTHEA_SEED", "99")
    assert seed.main(["--data-dir", str(data_dir)]) == 0
    assert (
        "Synthea patients loaded: 3 (4 bundles read, 1 deceased patients left out)" in capsys.readouterr().out
    )


@pytest.mark.usefixtures("clean_process_state")
def test_main_generates_when_output_is_missing(
    migrated_db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Runs the full path with a stand-in for the Java binary that writes two bundles; the jar download is
    skipped because a file with the pinned checksum name is checked first."""
    data_dir = tmp_path / "synthea"
    data_dir.mkdir()
    bundles = tmp_path / "prepared"
    write_bundles(bundles, [patient_bundle("p1"), patient_bundle("p2")])
    java = tmp_path / "fake-java"
    java.write_text(
        f'#!/bin/sh\nmkdir -p "{data_dir}/fhir" && cp "{bundles}"/*.json "{data_dir}/fhir/"\n',
        encoding="utf-8",
    )
    java.chmod(0o755)
    jar = data_dir / synthea.JAR_NAME
    jar.write_bytes(b"stand-in jar")
    monkeypatch.setattr(synthea, "JAR_SHA256", synthea.sha256_file(jar))
    monkeypatch.setattr(synthea.ensure_jar, "__defaults__", (synthea.JAR_URL, synthea.sha256_file(jar)))
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    monkeypatch.setenv("SYNTHEA_JAVA", str(java))
    monkeypatch.setenv("SYNTHEA_POPULATION", "2")
    assert seed.main(["--data-dir", str(data_dir)]) == 0
    assert "Synthea patients loaded: 2 (2 bundles read, 0 deceased" in capsys.readouterr().out
    assert synthea.is_generated(data_dir, 2, get_settings().synthea_seed)
