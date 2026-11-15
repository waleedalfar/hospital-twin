"""Patient record, vitals and risk history (§6.2)."""

import json
from datetime import timedelta
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from twin.api.deps import pool, runtime
from twin.api.runtime import SimRuntime
from twin.common.api_models import (
    Encounter,
    PatientDetail,
    RiskReading,
    RiskSeries,
    VitalsPoint,
    VitalsReading,
    VitalsSeries,
    parse_window,
)
from twin.db.pool import Pool

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]
DbPool = Annotated[Pool, Depends(pool)]
Window = Annotated[str, Query(description="How far back from the current sim time, e.g. 6h")]


def window_or_422(text: str) -> timedelta:
    try:
        return parse_window(text)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


async def require_patient(db: Pool, patient_id: str) -> None:
    async with db.acquire() as conn:
        if await conn.fetchval("SELECT 1 FROM patients WHERE id = $1", patient_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown patient {patient_id}")


@router.get("/patients/{patient_id}")
async def patient(patient_id: str, rt: Runtime, db: DbPool) -> PatientDetail:
    now = rt.sim.now
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, synthea_id, age, sex, conditions, comorbidity_count FROM patients WHERE id = $1",
            patient_id,
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown patient {patient_id}")
        encounter = await conn.fetchrow(
            "SELECT id, hospital_id, arrived_at, mode, esi, disposition, ended_at FROM encounters "
            "WHERE patient_id = $1 AND arrived_at <= $2 ORDER BY arrived_at DESC LIMIT 1",
            patient_id,
            now,
        )
        vitals = await conn.fetchrow(
            "SELECT time, hr, spo2, sbp, dbp, temp, rr FROM vitals WHERE patient_id = $1 AND time <= $2 ORDER BY time DESC LIMIT 1",
            patient_id,
            now,
        )
        risk = await conn.fetchrow(
            "SELECT time, score, level, model_version, top_factors FROM risk_scores WHERE patient_id = $1 AND time <= $2 ORDER BY time DESC LIMIT 1",
            patient_id,
            now,
        )
    located = rt.sim.world.patient(patient_id)
    return PatientDetail(
        id=row["id"],
        fhir_id=f"Patient/{row['synthea_id']}",
        age=row["age"],
        sex=row["sex"],
        conditions=list(row["conditions"]),
        comorbidity_count=row["comorbidity_count"],
        hospital_id=located[0].id if located else None,
        location=rt.sim.world.location(located[1].place) if located else None,
        encounter=Encounter(**dict(encounter)) if encounter is not None else None,
        vitals=VitalsReading(**dict(vitals)) if vitals is not None else None,
        risk=risk_reading(risk) if risk is not None else None,
    )


def risk_reading(row: asyncpg.Record) -> RiskReading:
    data = dict(row)
    factors = data["top_factors"]
    data["top_factors"] = json.loads(factors) if isinstance(factors, str) else factors
    return RiskReading(**data)


@router.get("/patients/{patient_id}/vitals")
async def patient_vitals(patient_id: str, rt: Runtime, db: DbPool, window: Window = "6h") -> VitalsSeries:
    """Five-minute averages from the `vitals_5m` continuous aggregate."""
    delta = window_or_422(window)
    await require_patient(db, patient_id)
    now = rt.sim.now
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT bucket AS time, hr, spo2, sbp, dbp, temp, rr, samples::int AS samples FROM vitals_5m "
            "WHERE patient_id = $1 AND bucket > $2 AND bucket <= $3 ORDER BY bucket",
            patient_id,
            now - delta,
            now,
        )
    return VitalsSeries(patient_id=patient_id, window=window, points=[VitalsPoint(**dict(r)) for r in rows])


@router.get("/patients/{patient_id}/risk")
async def patient_risk(patient_id: str, rt: Runtime, db: DbPool, window: Window = "6h") -> RiskSeries:
    delta = window_or_422(window)
    await require_patient(db, patient_id)
    now = rt.sim.now
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT time, score, level, model_version, top_factors FROM risk_scores WHERE patient_id = $1 AND time > $2 AND time <= $3 ORDER BY time",
            patient_id,
            now - delta,
            now,
        )
    return RiskSeries(patient_id=patient_id, window=window, points=[risk_reading(r) for r in rows])
