"""The simulation writing to Tiger Data and the API reading it back (PROMPT.md §4, §6)."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import asyncpg
import httpx
import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from tests.sim_helpers import make_profiles, make_sim
from twin.api.app import create_app
from twin.api.hub import Hub
from twin.api.runtime import ControlError, SimRuntime
from twin.common.config import Settings
from twin.db.pool import create_pool
from twin.db.sim_writer import SimWriter, reset_run
from twin.sim.entities import PatientProfile


async def seed_patients(dsn: str, n: int = 600) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.executemany(
            "INSERT INTO patients (id, synthea_id, fhir, age, sex, comorbidity_count, conditions) "
            "VALUES ($1, $2, '{}'::jsonb, $3, $4, $5, $6)",
            [
                (p.id, f"syn-{p.id}", p.age, p.sex, p.comorbidity_count, list(p.conditions))
                for p in make_profiles(n)
            ],
        )
    finally:
        await conn.close()


async def test_writer_stores_a_seeded_hour_and_counts_match(
    db: asyncpg.Connection, migrated_db_url: str
) -> None:
    await seed_patients(migrated_db_url)
    sim = make_sim(5, 6)
    writer = SimWriter(sim.world)
    writer.add_all_staff()
    emitted = []
    for _ in range(6 * 60):
        batch = sim.tick()
        emitted += batch
        writer.add(batch)
    await writer.flush(db)
    by_kind: dict[str, int] = {}
    for item in emitted:
        by_kind[item.event.kind] = by_kind.get(item.event.kind, 0) + 1
    assert await db.fetchval("SELECT count(*) FROM vitals") == by_kind["vitals"]
    rows = {r["kind"]: r["n"] for r in await db.fetch("SELECT kind, count(*) AS n FROM events GROUP BY kind")}
    assert rows == {k: v for k, v in by_kind.items() if k != "vitals"}
    assert await db.fetchval("SELECT count(*) FROM encounters") == by_kind["arrival"]
    assert await db.fetchval("SELECT count(*) FROM staff") == len(sim.world.staff)
    # bed snapshots: every 5 sim minutes, one row per bed per hospital (87 beds)
    snapshots = await db.fetchval("SELECT count(DISTINCT time) FROM bed_state")
    assert snapshots == 6 * 60 // 5
    assert await db.fetchval("SELECT count(*) FROM bed_state") == snapshots * 87
    done = await db.fetchval("SELECT count(*) FROM encounters WHERE ended_at IS NOT NULL")
    assert done >= by_kind["discharge"]
    assert await db.fetchval("SELECT count(*) FROM encounters WHERE disposition IS NOT NULL") > 0
    assert await db.fetchval("SELECT count(*) FROM encounters WHERE ended_at < arrived_at") == 0


async def test_er_wait_aggregate_matches_the_sim_after_refresh(
    db: asyncpg.Connection, migrated_db_url: str
) -> None:
    await seed_patients(migrated_db_url)
    sim = make_sim(5, 6)
    writer = SimWriter(sim.world)
    waits: list[float] = []
    for _ in range(6 * 60):
        batch = sim.tick()
        writer.add(batch)
        waits += [i.event.wait_min for i in batch if i.event.kind == "er_admit"]
    await writer.flush(db)
    await db.execute("CALL refresh_continuous_aggregate('er_wait_15m', NULL, NULL)")
    total = await db.fetchval("SELECT sum(patients) FROM er_wait_15m")
    assert total == len(waits)
    avg = await db.fetchval("SELECT sum(avg_wait_min * patients) / sum(patients) FROM er_wait_15m")
    assert avg == pytest.approx(sum(waits) / len(waits), rel=1e-3)


async def test_reset_run_clears_run_data_but_keeps_patients_and_building(
    db: asyncpg.Connection, migrated_db_url: str
) -> None:
    await seed_patients(migrated_db_url)
    sim = make_sim(5, 2)
    writer = SimWriter(sim.world)
    for _ in range(120):
        writer.add(sim.tick())
    await writer.flush(db)
    await db.execute("UPDATE hospitals SET status = 'offline'")
    assert await db.fetchval("SELECT count(*) FROM vitals") > 0
    await reset_run(db)
    for table in ("vitals", "events", "bed_state", "encounters", "staff", "audit_log"):
        assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0  # noqa: S608
    assert await db.fetchval("SELECT count(*) FROM patients") == 600
    assert await db.fetchval("SELECT count(*) FROM beds") == 87
    assert await db.fetchval("SELECT count(DISTINCT status) FROM hospitals") == 1


@asynccontextmanager
async def running_app(dsn: str) -> AsyncIterator[tuple[httpx.AsyncClient, SimRuntime]]:
    settings = Settings(
        _env_file=None, database_url=SecretStr(dsn), sim_warmup_hours=6, sim_autostart=False, sim_seed=5
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, app.state.runtime


async def test_api_serves_state_patients_kpis_and_sim_control(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with running_app(migrated_db_url) as (client, rt):
        for _ in range(30):
            await rt.step()
        health = (await client.get("/health")).json()
        assert health["status"] == "ok" and health["sim"] == "running"
        hospitals = (await client.get("/hospitals")).json()
        assert [h["id"] for h in hospitals] == ["mercy", "stlukes", "desert"]
        state = (await client.get("/hospitals/mercy/state")).json()
        assert state["type"] == "snapshot" and state["hospital"]["id"] == "mercy"
        assert (await client.get("/hospitals/nope/state")).status_code == 404

        patient = next(e for e in state["entities"] if e["kind"] == "patient" and e["location"]["bed"])
        detail = (await client.get(f"/patients/{patient['id']}")).json()
        assert detail["id"] == patient["id"]
        assert detail["fhir_id"] == f"Patient/syn-{patient['id']}"
        assert detail["location"]["bed"] == patient["location"]["bed"]
        assert detail["hospital_id"] == "mercy"
        assert detail["encounter"]["hospital_id"] == "mercy"
        assert detail["vitals"]["hr"] > 0
        assert "severity" not in json.dumps(detail).lower()

        series = (await client.get(f"/patients/{patient['id']}/vitals?window=6h")).json()
        assert series["points"] and series["window"] == "6h"
        assert all(p["samples"] >= 1 for p in series["points"])
        assert (await client.get(f"/patients/{patient['id']}/risk?window=90m")).json()["points"] == []
        assert (await client.get("/patients/P-9999")).status_code == 404
        assert (await client.get("/patients/P-9999/vitals")).status_code == 404
        assert (await client.get(f"/patients/{patient['id']}/vitals?window=forever")).status_code == 422
        assert (await client.get(f"/patients/{patient['id']}/vitals?window=0h")).status_code == 422

        kpis = (await client.get("/kpis/mercy")).json()
        assert {o["unit"] for o in kpis["occupancy"]} == {"ER", "WARD", "REC", "ICU"}
        assert (await client.get("/kpis/nope")).status_code == 404

        assert (await client.post("/sim/speed", json={"speed": 8})).json()["speed"] == 8
        assert (await client.post("/sim/speed", json={"speed": 3})).status_code == 422
        assert (await client.post("/sim/pause", json={"paused": True})).json()["paused"] is True
        assert (await client.get("/health")).json()["sim"] == "paused"
        assert (await client.post("/sim/freeze", json={"frozen": True})).json()["frozen"] is True
        assert (await client.get("/health")).json()["sim"] == "frozen"
        assert (await client.get("/sim")).json()["ready"] is True

        made = await client.post("/scenario", json={"name": "flu_surge", "hospital_id": "mercy"})
        assert made.status_code == 201
        scenario_id = made.json()["id"]
        assert (await client.post("/scenario", json={"name": "mass_casualty"})).status_code == 422
        assert [s["id"] for s in (await client.get("/scenario")).json()] == [scenario_id]
        assert (await client.delete(f"/scenario/{scenario_id}")).status_code == 200
        assert (await client.delete(f"/scenario/{scenario_id}")).status_code == 409
        assert (await client.delete("/scenario/SC-99")).status_code == 404

        audit = [r["action"] for r in await _audit(migrated_db_url)]
        assert audit[:1] == ["sim_start"]
        assert {"sim_speed", "sim_pause", "sim_freeze", "scenario_start", "scenario_stop"} <= set(audit)


async def _audit(dsn: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch("SELECT action, actor, payload FROM audit_log ORDER BY time, action")
    finally:
        await conn.close()


async def test_endpoints_refuse_until_the_sim_is_ready_and_health_reports_an_empty_pool(
    empty_db_url: str,
) -> None:
    from twin.db import migrate

    await migrate.migrate_and_sync(empty_db_url)
    settings = Settings(_env_file=None, database_url=SecretStr(empty_db_url))
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        health = await client.get("/health")
        assert health.status_code == 503
        assert "make seed" in health.json()["sim_error"]
        assert (await client.get("/hospitals")).status_code == 503
        assert (await client.post("/sim/pause", json={"paused": True})).status_code == 503


async def test_runtime_applies_actions_with_audit_and_rejects_bad_speed(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with running_app(migrated_db_url) as (_, rt):
        await rt.apply_action(
            "call_in_staff", {"hospital_id": "mercy", "unit": "ICU", "count": 1}, actor="agent:test"
        )
        with pytest.raises(ControlError):
            await rt.set_speed(5)
        with pytest.raises(ControlError):
            SimRuntime(rt.sim, rt.pool, Hub(), speed=2)
        rows = await _audit(migrated_db_url)
        applied = [r for r in rows if r["action"] == "action_applied"]
        assert len(applied) == 1 and applied[0]["actor"] == "agent:test"
        assert "ICU" in applied[0]["payload"]
        assert await rt.pool.fetchval("SELECT count(*) FROM events WHERE kind = 'action'") == 1


def test_websocket_streams_snapshot_then_events_and_resyncs(migrated_db_url: str) -> None:
    asyncio.run(seed_patients(migrated_db_url))
    settings = Settings(
        _env_file=None, database_url=SecretStr(migrated_db_url), sim_warmup_hours=6, sim_seed=5, sim_speed=8
    )
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/ws?hospital=mercy") as ws:
            snap = json.loads(ws.receive_text())
            assert snap["v"] == 1 and snap["type"] == "snapshot" and snap["hospital"]["id"] == "mercy"
            assert snap["speed"] == 8
            first = json.loads(ws.receive_text())
            second = json.loads(ws.receive_text())
            assert first["type"] == second["type"] == "events"
            assert second["sim_time"] > first["sim_time"]
            assert {"kpis", "events", "paused", "speed"} <= set(first)
            assert snap["sim_time"] < first["sim_time"]
        with client.websocket_connect("/ws?hospital=mercy") as again:  # reconnect: fresh snapshot
            assert json.loads(again.receive_text())["type"] == "snapshot"
        with client.websocket_connect("/ws/network") as net:
            n = json.loads(net.receive_text())
            assert n["type"] == "network" and len(n["hospitals"]) == 3
            assert n["vehicles"]
            assert json.loads(net.receive_text())["type"] == "network"
        with client.websocket_connect("/ws?hospital=nope") as bad:
            assert json.loads(bad.receive_text())["type"] == "error"
        with client.websocket_connect("/ws") as missing:
            assert json.loads(missing.receive_text())["type"] == "error"


def test_websocket_refuses_when_the_pool_is_empty(empty_db_url: str) -> None:
    from twin.db import migrate

    asyncio.run(migrate.migrate_and_sync(empty_db_url))
    with TestClient(create_app(Settings(_env_file=None, database_url=SecretStr(empty_db_url)))) as client:
        for path in ("/ws?hospital=mercy", "/ws/network"):
            with client.websocket_connect(path) as ws:
                assert "not running" in json.loads(ws.receive_text())["message"]


async def test_hub_disconnects_slow_clients() -> None:
    from twin.api.hub import QUEUE_LIMIT

    hub = Hub()
    slow = hub.subscribe("mercy")
    fast = hub.subscribe("mercy")
    assert hub.count("mercy") == 2 and hub.has_hospital_clients("mercy") and not hub.has_network_clients()
    for i in range(QUEUE_LIMIT):
        hub.publish_hospital("mercy", str(i))
        fast.queue.get_nowait()
    hub.publish_hospital("mercy", "overflow")
    assert hub.count("mercy") == 1
    assert slow.queue.qsize() == QUEUE_LIMIT
    drained = [slow.queue.get_nowait() for _ in range(QUEUE_LIMIT)]
    assert drained[-1] is None
    hub.publish_network("x")
    pool = await create_pool("postgresql://twin:twin@localhost:5434/twin_test")
    await pool.close()


def test_profile_type_is_importable() -> None:
    assert PatientProfile("P-1", 30, "male", 0, ()).age == 30
    assert timedelta(hours=1) > timedelta(0)


async def ticks_in(rt: SimRuntime, seconds: float) -> int:
    before = rt.ticks
    await asyncio.sleep(seconds)
    return rt.ticks - before


async def test_tick_loop_runs_at_each_speed_and_stops_on_pause_and_freeze(migrated_db_url: str) -> None:
    """§5.1: 1x = one tick per real second, 4x, 8x, pause, freeze."""
    await seed_patients(migrated_db_url)
    async with running_app(migrated_db_url) as (client, rt):
        rt.start()
        await asyncio.sleep(0.2)
        one = await ticks_in(rt, 3.0)
        assert 2 <= one <= 4
        await client.post("/sim/speed", json={"speed": 4})
        four = await ticks_in(rt, 2.0)
        assert 6 <= four <= 10
        await client.post("/sim/speed", json={"speed": 8})
        eight = await ticks_in(rt, 2.0)
        assert 12 <= eight <= 18
        await client.post("/sim/pause", json={"paused": True})
        await asyncio.sleep(0.3)
        assert await ticks_in(rt, 1.5) == 0
        await client.post("/sim/pause", json={"paused": False})
        assert await ticks_in(rt, 1.5) > 5
        await client.post("/sim/freeze", json={"frozen": True})
        await asyncio.sleep(0.3)
        frozen_time = rt.sim.now
        assert await ticks_in(rt, 1.5) == 0
        assert rt.sim.now == frozen_time
        await client.post("/sim/freeze", json={"frozen": False})
        assert await ticks_in(rt, 1.5) > 5
        written = await rt.pool.fetchval("SELECT count(DISTINCT time) FROM bed_state")
        assert written > 6 * 60 // 5
