"""Nurse alerts (extra X1): list, acknowledge, escalate, and the response-time summary."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from twin.api.deps import known_hospital, pool, runtime
from twin.api.runtime import SimRuntime
from twin.common.api_models import NurseResponseStats
from twin.common.ws import NurseAlertModel
from twin.db.pool import Pool
from twin.sim.nurses import AlertError

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]
DbPool = Annotated[Pool, Depends(pool)]


@router.get("/nurse-alerts")
async def list_alerts(rt: Runtime, hospital: str | None = None, status: str | None = None, limit: int = 50) -> list[NurseAlertModel]:
    """Alerts of the current run, newest first."""
    if hospital is not None:
        known_hospital(rt, hospital)
    alerts = [
        a for a in rt.sim.world.nurse_alerts.values() if (hospital is None or a.hospital_id == hospital) and (status is None or a.status == status)
    ]
    alerts.sort(key=lambda a: (a.created, a.id), reverse=True)
    return [a.model() for a in alerts[: max(1, min(limit, 200))]]


async def answer(rt: SimRuntime, alert_id: str, action: str) -> NurseAlertModel:
    try:
        return (await rt.nurse_response(alert_id, action, "user")).model()
    except AlertError as error:
        raise HTTPException(error.status, str(error)) from error


@router.post("/nurse-alerts/{alert_id}/acknowledge")
async def acknowledge(alert_id: str, rt: Runtime) -> NurseAlertModel:
    return await answer(rt, alert_id, "acknowledge")


@router.post("/nurse-alerts/{alert_id}/escalate")
async def escalate(alert_id: str, rt: Runtime) -> NurseAlertModel:
    return await answer(rt, alert_id, "escalate")


@router.post("/patients/{patient_id}/page-nurse", status_code=201)
async def page_nurse(patient_id: str, rt: Runtime) -> NurseAlertModel:
    """Page the nurse responsible for a patient: the same pop-up and bedside visit as a high-risk alert."""
    try:
        return (await rt.page_nurse(patient_id, "user")).model()
    except AlertError as error:
        raise HTTPException(error.status, str(error)) from error


@router.get("/governance/nurse-response")
async def nurse_response(rt: Runtime, db: DbPool) -> NurseResponseStats:
    """How quickly nurses answer high-risk alerts, from the audit log."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, payload FROM audit_log WHERE action IN ('nurse_alert_acknowledged', 'nurse_alert_escalated') AND time <= $1",
            rt.sim.now,
        )
    seconds = sorted(
        float(p["seconds_to_ack"])
        for p in (json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows)
        if p.get("seconds_to_ack") is not None
    )
    alerts = list(rt.sim.world.nurse_alerts.values())
    return NurseResponseStats(
        raised=len(alerts),
        pending=sum(1 for a in alerts if a.status == "pending"),
        acknowledged=sum(1 for r in rows if r["action"] == "nurse_alert_acknowledged"),
        escalated=sum(1 for r in rows if r["action"] == "nurse_alert_escalated"),
        mean_seconds_to_ack=sum(seconds) / len(seconds) if seconds else None,
        median_seconds_to_ack=seconds[len(seconds) // 2] if seconds else None,
    )
