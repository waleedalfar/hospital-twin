"""Shared request helpers."""

from fastapi import HTTPException, Request, status

from twin.api.runtime import SimRuntime
from twin.db.pool import Pool


def runtime(request: Request) -> SimRuntime:
    rt: SimRuntime | None = getattr(request.app.state, "runtime", None)
    if rt is None or not rt.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The simulation is not running yet")
    return rt


def pool(request: Request) -> Pool:
    p: Pool = request.app.state.pool
    return p


def known_hospital(rt: SimRuntime, hospital_id: str) -> None:
    if hospital_id not in rt.sim.world.hospitals:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown hospital {hospital_id}")
