"""The schema from PROMPT.md §4.1-4.2 on a real, freshly migrated TimescaleDB."""

import asyncpg
import pytest

HYPERTABLES = {
    "vitals",
    "events",
    "bed_state",
    "risk_scores",
    "forecasts",
    "agent_recs",
    "audit_log",
    "drift",
}
REFERENCE_TABLES = {"hospitals", "units", "rooms", "beds", "staff", "patients", "encounters"}
AGGREGATES = {"occupancy_15m", "er_wait_15m", "arrivals_hourly", "alerts_hourly", "vitals_5m"}

EXPECTED_COLUMNS = {
    "hospitals": {"id", "name", "lat", "lon", "status"},
    "beds": {"bed_id", "hospital_id", "room_id", "unit", "floor", "x", "z", "rotation"},
    "staff": {"id", "hospital_id", "role", "unit", "name_code"},
    "patients": {"id", "synthea_id", "fhir", "age", "sex", "comorbidity_count", "conditions"},
    "encounters": {"id", "patient_id", "hospital_id", "arrived_at", "mode", "esi", "disposition", "ended_at"},
    "vitals": {"time", "patient_id", "hospital_id", "hr", "spo2", "sbp", "dbp", "temp", "rr"},
    "events": {"time", "hospital_id", "kind", "entity_id", "payload"},
    "bed_state": {"time", "bed_id", "hospital_id", "patient_id", "state"},
    "risk_scores": {"time", "patient_id", "hospital_id", "model_version", "score", "level", "top_factors"},
    "forecasts": {"time", "hospital_id", "model_version", "horizon_h", "metric", "value"},
    "agent_recs": {"time", "id", "hospital_id", "source", "payload", "status"},
    "audit_log": {"time", "actor", "action", "payload"},
    "drift": {"time", "hospital_id", "feature", "psi"},
}


async def test_tables_have_the_spec_columns(db: asyncpg.Connection) -> None:
    rows = await db.fetch("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
    columns: dict[str, set[str]] = {}
    for row in rows:
        columns.setdefault(row["table_name"], set()).add(row["column_name"])
    assert set(columns) >= REFERENCE_TABLES | HYPERTABLES
    for table, expected in EXPECTED_COLUMNS.items():
        assert columns[table] == expected, table


async def test_time_series_tables_are_hypertables_on_time(db: asyncpg.Connection) -> None:
    rows = await db.fetch(
        """
        SELECT h.hypertable_name, d.column_name, d.column_type::text AS column_type, d.time_interval
        FROM timescaledb_information.hypertables h
        JOIN timescaledb_information.dimensions d USING (hypertable_schema, hypertable_name)
        WHERE h.hypertable_schema = 'public'
        """
    )
    assert {row["hypertable_name"] for row in rows} == HYPERTABLES
    for row in rows:
        assert row["column_name"] == "time"
        assert row["column_type"] == "timestamp with time zone"
        assert row["time_interval"].days == 1


async def test_latent_severity_is_not_a_column_anywhere(db: asyncpg.Connection) -> None:
    """§5.4: the latent severity is never written to the DB."""
    names = await db.fetch("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public'")
    for row in names:
        assert "severity" not in row["column_name"]
        assert "latent" not in row["column_name"]


async def test_indexes_for_patient_and_hospital_lookups(db: asyncpg.Connection) -> None:
    rows = await db.fetch("SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    defs: dict[str, list[str]] = {}
    for row in rows:
        defs.setdefault(row["tablename"], []).append(row["indexdef"])
    for table in ("vitals", "risk_scores"):
        assert any('(patient_id, "time" DESC)' in d for d in defs[table]), table
    for table in ("vitals", "events", "bed_state", "risk_scores", "agent_recs"):
        assert any('(hospital_id, "time" DESC)' in d for d in defs[table]), table


async def test_continuous_aggregates_exist_with_refresh_policies(db: asyncpg.Connection) -> None:
    views = await db.fetch("SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates")
    assert {row["view_name"] for row in views} == AGGREGATES
    assert not any(row["materialized_only"] for row in views)  # readers also see not-yet-refreshed rows
    jobs = await db.fetch(
        """
        SELECT ca.view_name, j.schedule_interval
        FROM timescaledb_information.jobs j
        JOIN timescaledb_information.continuous_aggregates ca
          ON ca.materialization_hypertable_name = j.hypertable_name
        WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
        """
    )
    assert {row["view_name"] for row in jobs} == AGGREGATES
    assert all(row["schedule_interval"].total_seconds() == 60 for row in jobs)


async def test_compression_policy_on_vitals_and_events(db: asyncpg.Connection) -> None:
    jobs = await db.fetch(
        """
        SELECT hypertable_name, config ->> 'compress_after' AS compress_after
        FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression'
        """
    )
    assert {row["hypertable_name"]: row["compress_after"] for row in jobs} == {
        "vitals": "1 day",
        "events": "1 day",
    }
    settings = await db.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE compression_enabled")
    assert {"vitals", "events"} <= {row["hypertable_name"] for row in settings}


async def test_compression_policy_compresses_old_chunks_and_data_stays_readable(
    db: asyncpg.Connection,
) -> None:
    await db.execute(
        """
        INSERT INTO vitals (time, patient_id, hospital_id, hr, spo2, sbp, dbp, temp, rr)
        SELECT now() - INTERVAL '3 days' + (i || ' minutes')::interval,
               'P-0001', 'mercy', 80 + i, 97, 120, 80, 37, 16
        FROM generate_series(0, 9) AS i
        """
    )
    job_id = await db.fetchval(
        "SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression' AND hypertable_name = 'vitals'"
    )
    await db.execute(f"CALL run_job({int(job_id)})")
    compressed = await db.fetchval("SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'vitals' AND is_compressed")
    assert compressed >= 1
    assert await db.fetchval("SELECT count(*) FROM vitals") == 10
    assert await db.fetchval("SELECT avg(hr) FROM vitals") == 84.5


async def test_constraints_reject_invalid_rows(db: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute("INSERT INTO bed_state (time, bed_id, hospital_id, patient_id, state) VALUES (now(), 'ICU-1', 'mercy', NULL, 'on fire')")
    with pytest.raises(asyncpg.CheckViolationError):  # occupied needs a patient
        await db.execute("INSERT INTO bed_state (time, bed_id, hospital_id, patient_id, state) VALUES (now(), 'ICU-1', 'mercy', NULL, 'occupied')")
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            "INSERT INTO risk_scores (time, patient_id, hospital_id, model_version, score, level) "
            "VALUES (now(), 'P-0001', 'mercy', 'v1', 1.5, 'high')"
        )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await db.execute("INSERT INTO encounters (patient_id, hospital_id, arrived_at, mode, esi) VALUES ('P-9999', 'mercy', now(), 'walk_in', 3)")
