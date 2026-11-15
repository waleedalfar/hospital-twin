"""Models and forecasts (PROMPT.md §6.2, §7)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from twin.api.deps import known_hospital, pool, runtime
from twin.api.runtime import SimRuntime
from twin.common.api_models import ForecastReport, ModelsResponse
from twin.db.pool import Pool
from twin.ml.forecast import MAX_HOURS_UNTIL_FULL
from twin.ml.registry import list_models

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]
DbPool = Annotated[Pool, Depends(pool)]


@router.get("/models")
async def models(request: Request) -> ModelsResponse:
    """Trained model versions with their metrics, and the versions the simulation is scoring with."""
    rt: SimRuntime | None = getattr(request.app.state, "runtime", None)
    ml = rt.sim.ml if rt is not None else None
    return ModelsResponse(
        active_deterioration=ml.model.version if ml else None,
        active_arrivals=ml.arrivals_model.version if ml and ml.arrivals_model else None,
        error=getattr(request.app.state, "ml_error", None),
        models=list_models(),
    )


@router.get("/forecast/{hospital_id}")
async def forecast(hospital_id: str, rt: Runtime, db: DbPool) -> ForecastReport:
    """Latest stored forecast: arrivals for the next 6 hours and hours until each unit is full."""
    known_hospital(rt, hospital_id)
    now = rt.sim.now
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (metric, horizon_h) metric, horizon_h, value, time, model_version
            FROM forecasts WHERE hospital_id = $1 AND time <= $2
            ORDER BY metric, horizon_h, time DESC
            """,
            hospital_id,
            now,
        )
    arrivals = sorted((r["horizon_h"], r["value"]) for r in rows if r["metric"] == "arrivals")
    until_full: dict[str, float | None] = {}
    for r in rows:
        if r["metric"].startswith("hours_until_full:"):
            until_full[r["metric"].split(":", 1)[1]] = r["value"] if r["value"] <= MAX_HOURS_UNTIL_FULL else None
    return ForecastReport(
        hospital_id=hospital_id,
        as_of=max((r["time"] for r in rows), default=None),
        model_version=rows[0]["model_version"] if rows else None,
        arrivals=[{"hours_ahead": h, "expected": v} for h, v in arrivals],
        hours_until_full=until_full,
    )
