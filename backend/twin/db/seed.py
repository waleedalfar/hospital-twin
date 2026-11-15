"""`make seed`: generate Synthea patients and load them into the `patients` table (PROMPT.md §4.3)."""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import asyncpg

from twin.common.config import get_settings
from twin.common.logging import configure_logging
from twin.db import synthea
from twin.db.fhir import PatientRecord, parse_bundle
from twin.db.migrate import connect_with_retry

logger = logging.getLogger(__name__)

# Ages are as of the simulation start date (§5.1).
AS_OF = date(2026, 11, 14)
BATCH = 200
# Synthea writes these next to the patient bundles when their exporters are on; they hold no patient.
NON_PATIENT_PREFIXES = ("hospitalInformation", "practitionerInformation")


@dataclass(frozen=True)
class SeedResult:
    files: int
    loaded: int
    deceased: int


def patient_id(index: int) -> str:
    """Twin patient id for the patient at 0-based position `index`: P-0001, P-0002, ..."""
    return f"P-{index + 1:04d}"


def read_records(fhir_dir: Path, as_of: date = AS_OF) -> tuple[list[PatientRecord], int, int]:
    """Parse every patient bundle in `fhir_dir`. Returns (living patients sorted by Synthea id, number of
    files read, number of deceased patients left out)."""
    files = sorted(path for path in fhir_dir.glob("*.json") if not path.name.startswith(NON_PATIENT_PREFIXES))
    records: list[PatientRecord] = []
    deceased = 0
    for path in files:
        record = parse_bundle(json.loads(path.read_text(encoding="utf-8")), as_of)
        if record is None:
            deceased += 1
        else:
            records.append(record)
    records.sort(key=lambda record: record.synthea_id)
    return records, len(files), deceased


async def load_records(conn: asyncpg.Connection, records: list[PatientRecord]) -> int:
    """Make the `patients` table hold exactly `records`. Ids are assigned by sorted Synthea id, so the
    same Synthea output always gives the same P-numbers."""
    rows = [(patient_id(i), r.synthea_id, json.dumps(r.fhir), r.age, r.sex, r.comorbidity_count, r.conditions) for i, r in enumerate(records)]
    async with conn.transaction():
        # Clear rows whose Synthea id would collide with a different P-number (a changed patient set).
        await conn.execute(
            "DELETE FROM patients WHERE NOT (id || '/' || synthea_id = ANY($1::text[]))",
            [f"{row[0]}/{row[1]}" for row in rows],
        )
        for start in range(0, len(rows), BATCH):
            await conn.executemany(
                """
                INSERT INTO patients (id, synthea_id, fhir, age, sex, comorbidity_count, conditions)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE
                SET fhir = EXCLUDED.fhir, age = EXCLUDED.age, sex = EXCLUDED.sex,
                    comorbidity_count = EXCLUDED.comorbidity_count, conditions = EXCLUDED.conditions
                """,
                rows[start : start + BATCH],
            )
    return len(rows)


async def seed_from_directory(dsn: str, fhir_dir: Path) -> SeedResult:
    records, files, deceased = read_records(fhir_dir)
    conn = await connect_with_retry(dsn)
    try:
        loaded = await load_records(conn, records)
    finally:
        await conn.close()
    return SeedResult(files=files, loaded=loaded, deceased=deceased)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Synthea patients and load them")
    parser.add_argument("--regenerate", action="store_true", help="run Synthea again even if output exists")
    parser.add_argument("--data-dir", type=Path, default=synthea.DATA_DIR)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    data_dir: Path = args.data_dir
    population, seed = settings.synthea_population, settings.synthea_seed

    if args.regenerate or not synthea.is_generated(data_dir, population, seed):
        jar = synthea.ensure_jar(data_dir / synthea.JAR_NAME)
        java = synthea.find_java(settings.synthea_java)
        synthea.generate(java, jar, data_dir, population, seed)
    else:
        logger.info("Reusing Synthea output in %s (same version, seed and population)", data_dir)

    result = asyncio.run(seed_from_directory(settings.database_url.get_secret_value(), data_dir / "fhir"))
    print(f"Synthea patients loaded: {result.loaded} ({result.files} bundles read, {result.deceased} deceased patients left out)")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
