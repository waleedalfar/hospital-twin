"""Hospitals, their live state and KPIs from the continuous aggregates (§6.2)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from twin.api.deps import known_hospital, pool, runtime
from twin.api.runtime import SimRuntime
from twin.common.api_models import ErWait, HospitalSummary, KpiReport, UnitOccupancy
from twin.db.pool import Pool
from twin.sim.snapshot import kpis

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]
DbPool = Annotated[Pool, Depends(pool)]


@router.get("/hospitals")
async def hospitals(rt: Runtime) -> list[HospitalSummary]:
    world = rt.sim.world
    return [
        HospitalSummary(
            id=h.id,
            name=h.name,
            lat=h.lat,
            lon=h.lon,
            status=world.hospitals[h.id].status,
            kpis=kpis(world, world.hospitals[h.id]),
        )
        for h in world.layout.hospitals
    ]


@router.get("/hospitals/{hospital_id}/state")
async def hospital_state(hospital_id: str, rt: Runtime) -> Response:
    """The same snapshot a WebSocket client receives on connect."""
    known_hospital(rt, hospital_id)
    return Response(rt.snapshot_json(hospital_id), media_type="application/json")


@router.get("/kpis/{hospital_id}")
async def hospital_kpis(hospital_id: str, rt: Runtime, db: DbPool) -> KpiReport:
    known_hospital(rt, hospital_id)
    now = rt.sim.now
    async with db.acquire() as conn:
        occupancy = await conn.fetch(
            """
            SELECT DISTINCT ON (unit) unit, bucket, occupied_avg, beds
            FROM occupancy_15m WHERE hospital_id = $1 AND bucket <= $2
            ORDER BY unit, bucket DESC
            """,
            hospital_id,
            now,
        )
        er_wait = await conn.fetchrow(
            """
            SELECT bucket, avg_wait_min, p90_wait_min, patients FROM er_wait_15m
            WHERE hospital_id = $1 AND bucket <= $2 ORDER BY bucket DESC LIMIT 1
            """,
            hospital_id,
            now,
        )
        arrivals = await conn.fetch(
            "SELECT mode, sum(arrivals)::int AS n FROM arrivals_hourly "
            "WHERE hospital_id = $1 AND bucket > $2::timestamptz - INTERVAL '1 hour' "
            "AND bucket <= $2::timestamptz GROUP BY mode",
            hospital_id,
            now,
        )
        alerts = await conn.fetch(
            "SELECT level, sum(alerts)::int AS n FROM alerts_hourly "
            "WHERE hospital_id = $1 AND bucket > $2::timestamptz - INTERVAL '1 hour' "
            "AND bucket <= $2::timestamptz GROUP BY level",
            hospital_id,
            now,
        )
    return KpiReport(
        hospital_id=hospital_id,
        as_of=now,
        occupancy=[UnitOccupancy(**dict(row)) for row in occupancy],
        er_wait=ErWait(**dict(er_wait)) if er_wait is not None else None,
        arrivals_last_hour={row["mode"]: row["n"] for row in arrivals},
        alerts_last_hour={row["level"]: row["n"] for row in alerts},
    )
