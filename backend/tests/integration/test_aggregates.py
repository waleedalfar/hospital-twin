"""Continuous aggregates return the right numbers for a seeded dataset after a manual refresh (§4.2)."""

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

T0 = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)  # sim start: 08:00 in Phoenix


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def refresh(db: asyncpg.Connection, view: str) -> int:
    """Refresh the whole aggregate and return how many rows are now materialized on disk."""
    await db.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
    table = await db.fetchval(
        "SELECT format('%I.%I', materialization_hypertable_schema, materialization_hypertable_name) "
        "FROM timescaledb_information.continuous_aggregates WHERE view_name = $1",
        view,
    )
    return int(await db.fetchval(f"SELECT count(*) FROM {table}"))  # noqa: S608 - name from the catalog


async def add_events(db: asyncpg.Connection, rows: list[tuple[datetime, str, str, str]]) -> None:
    await db.executemany(
        "INSERT INTO events (time, hospital_id, kind, entity_id, payload) VALUES ($1, $2, $3, 'P-0001', $4::jsonb)",
        rows,
    )


async def test_occupancy_15m(db: asyncpg.Connection) -> None:
    snapshots = [
        # bucket 15:00, three snapshots. ICU-1 always occupied, ICU-2 twice, ICU-3 never. WARD-1 always.
        (at(0), "ICU-1", "mercy", "P-0001", "occupied"),
        (at(0), "ICU-2", "mercy", "P-0002", "occupied"),
        (at(0), "ICU-3", "mercy", None, "open"),
        (at(0), "WARD-1", "mercy", "P-0003", "occupied"),
        (at(5), "ICU-1", "mercy", "P-0001", "occupied"),
        (at(5), "ICU-2", "mercy", "P-0002", "occupied"),
        (at(5), "ICU-3", "mercy", None, "cleaning"),
        (at(5), "WARD-1", "mercy", "P-0003", "occupied"),
        (at(10), "ICU-1", "mercy", "P-0001", "occupied"),
        (at(10), "ICU-2", "mercy", None, "open"),
        (at(10), "ICU-3", "mercy", None, "blocked"),
        (at(10), "WARD-1", "mercy", "P-0003", "occupied"),
        # bucket 15:15, one snapshot
        (at(15), "ICU-1", "mercy", "P-0001", "occupied"),
        (at(15), "ICU-2", "mercy", None, "open"),
        # another hospital, bucket 15:00
        (at(0), "ICU-1", "stlukes", "P-0004", "occupied"),
    ]
    await db.executemany(
        "INSERT INTO bed_state (time, bed_id, hospital_id, patient_id, state) VALUES ($1, $2, $3, $4, $5)",
        snapshots,
    )
    assert await refresh(db, "occupancy_15m") == 4
    rows = await db.fetch("SELECT bucket, hospital_id, unit, occupied_avg, beds, snapshots FROM occupancy_15m ORDER BY 1, 2, 3")
    got = {(r["bucket"], r["hospital_id"], r["unit"]): (r["occupied_avg"], r["beds"], r["snapshots"]) for r in rows}
    assert got == {
        (at(0), "mercy", "ICU"): (pytest.approx(5 / 3), 3, 3),
        (at(0), "mercy", "WARD"): (1.0, 1, 3),
        (at(0), "stlukes", "ICU"): (1.0, 1, 1),
        (at(15), "mercy", "ICU"): (1.0, 2, 1),
    }


async def test_er_wait_15m(db: asyncpg.Connection) -> None:
    rows = [(at(i), "mercy", "er_admit", f'{{"wait_min": {wait}}}') for i, wait in enumerate((10, 20, 30, 40, 100))]
    rows.append((at(20), "mercy", "er_admit", '{"wait_min": 7}'))
    rows.append((at(3), "desert", "er_admit", '{"wait_min": 55.5}'))
    rows.append((at(4), "mercy", "arrival", '{"wait_min": 9999, "mode": "walk_in"}'))  # not an ER admit
    await add_events(db, rows)
    assert await refresh(db, "er_wait_15m") == 3
    got = {
        (r["bucket"], r["hospital_id"]): (r["avg_wait_min"], r["p90_wait_min"], r["patients"]) for r in await db.fetch("SELECT * FROM er_wait_15m")
    }
    assert got == {
        (at(0), "mercy"): (40.0, pytest.approx(76.0), 5),  # p90 of 10,20,30,40,100 = 40 + 0.6 * 60
        (at(15), "mercy"): (7.0, 7.0, 1),
        (at(0), "desert"): (55.5, 55.5, 1),
    }


async def test_arrivals_hourly(db: asyncpg.Connection) -> None:
    rows = [(at(m), "mercy", "arrival", '{"mode": "walk_in"}') for m in (1, 20, 59)]
    rows += [(at(m), "mercy", "arrival", '{"mode": "ambulance"}') for m in (5, 30)]
    rows += [
        (at(65), "mercy", "arrival", '{"mode": "air"}'),
        (at(70), "mercy", "arrival", '{"mode": "walk_in"}'),
    ]
    rows += [(at(10), "stlukes", "arrival", '{"mode": "ambulance"}')]
    rows += [(at(10), "mercy", "discharge", '{"mode": "walk_in"}')]  # not an arrival
    await add_events(db, rows)
    assert await refresh(db, "arrivals_hourly") == 5
    got = {(r["bucket"], r["hospital_id"], r["mode"]): r["arrivals"] for r in await db.fetch("SELECT * FROM arrivals_hourly")}
    assert got == {
        (at(0), "mercy", "walk_in"): 3,
        (at(0), "mercy", "ambulance"): 2,
        (at(60), "mercy", "air"): 1,
        (at(60), "mercy", "walk_in"): 1,
        (at(0), "stlukes", "ambulance"): 1,
    }


async def test_alerts_hourly(db: asyncpg.Connection) -> None:
    rows = [(at(m), "mercy", "alert", '{"level": "high"}') for m in (2, 3, 50)]
    rows += [
        (at(4), "mercy", "alert", '{"level": "medium"}'),
        (at(61), "desert", "alert", '{"level": "high"}'),
    ]
    await add_events(db, rows)
    assert await refresh(db, "alerts_hourly") == 3
    got = {(r["bucket"], r["hospital_id"], r["level"]): r["alerts"] for r in await db.fetch("SELECT * FROM alerts_hourly")}
    assert got == {(at(0), "mercy", "high"): 3, (at(0), "mercy", "medium"): 1, (at(60), "desert", "high"): 1}


async def test_vitals_5m(db: asyncpg.Connection) -> None:
    rows = [
        (at(0), "P-0001", "mercy", 80.0, 98.0, 120.0, 80.0, 37.0, 16.0),
        (at(4), "P-0001", "mercy", 100.0, 94.0, 110.0, 70.0, 38.0, 20.0),
        (at(5), "P-0001", "mercy", 120.0, 90.0, 100.0, 60.0, 39.0, 24.0),
        (at(1), "P-0002", "mercy", 60.0, 99.0, 130.0, 85.0, 36.5, 12.0),
    ]
    await db.executemany(
        "INSERT INTO vitals (time, patient_id, hospital_id, hr, spo2, sbp, dbp, temp, rr) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        rows,
    )
    assert await refresh(db, "vitals_5m") == 3
    got = {
        (r["bucket"], r["patient_id"]): (
            r["hr"],
            r["spo2"],
            r["sbp"],
            r["dbp"],
            r["temp"],
            r["rr"],
            r["samples"],
        )
        for r in await db.fetch("SELECT * FROM vitals_5m")
    }
    assert got == {
        (at(0), "P-0001"): (90.0, 96.0, 115.0, 75.0, 37.5, 18.0, 2),
        (at(5), "P-0001"): (120.0, 90.0, 100.0, 60.0, 39.0, 24.0, 1),
        (at(0), "P-0002"): (60.0, 99.0, 130.0, 85.0, 36.5, 12.0, 1),
    }


async def test_unrefreshed_rows_are_still_visible(db: asyncpg.Connection) -> None:
    """Real-time aggregation: a reader sees new data before any refresh runs."""
    await add_events(db, [(at(1), "mercy", "arrival", '{"mode": "walk_in"}')])
    assert await db.fetchval("SELECT arrivals FROM arrivals_hourly WHERE hospital_id = 'mercy'") == 1


async def test_refresh_policy_materializes_sim_time_ahead_of_the_wall_clock(db: asyncpg.Connection) -> None:
    """The sim runs faster than real time, so its timestamps are in the future. The policy must still
    materialize them."""
    future = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=30)
    await add_events(db, [(future + timedelta(minutes=m), "mercy", "arrival", '{"mode": "air"}') for m in (1, 2)])
    job = await db.fetchrow(
        """
        SELECT j.job_id,
               format('%I.%I', ca.materialization_hypertable_schema, ca.materialization_hypertable_name)
        FROM timescaledb_information.jobs j
        JOIN timescaledb_information.continuous_aggregates ca
          ON ca.materialization_hypertable_name = j.hypertable_name
        WHERE ca.view_name = 'arrivals_hourly'
        """
    )
    assert job is not None
    job_id, table = job["job_id"], job["format"]
    assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0  # noqa: S608 - name from the catalog
    await db.execute(f"CALL run_job({int(job_id)})")
    assert await db.fetchval(f"SELECT count(*) FROM {table}") == 1  # noqa: S608 - name from the catalog
    row = await db.fetchrow("SELECT bucket, arrivals FROM arrivals_hourly WHERE mode = 'air'")
    assert row is not None
    assert (row["bucket"], row["arrivals"]) == (future, 2)
