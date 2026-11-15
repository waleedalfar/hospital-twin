"""Governance: drift, fairness, audit log and the model card (PROMPT.md §6.2, §8)."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from twin.api.deps import pool, runtime
from twin.api.runtime import SimRuntime
from twin.common.api_models import AuditEntry, DriftCell, DriftReport, FairnessReport
from twin.common.config import REPO_ROOT
from twin.db.pool import Pool
from twin.ml.governance import PSI_ALERT, RESPIRATORY_FEATURES

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]
DbPool = Annotated[Pool, Depends(pool)]
MODEL_CARD = REPO_ROOT / "docs" / "model_card.md"


@router.get("/governance/drift")
async def drift(rt: Runtime, db: DbPool) -> DriftReport:
    """The latest PSI of every feature at every hospital against the training distribution."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (hospital_id, feature) hospital_id, feature, psi, time FROM drift
            WHERE time <= $1 ORDER BY hospital_id, feature, time DESC
            """,
            rt.sim.now,
        )
    cells = [
        DriftCell(
            hospital_id=r["hospital_id"],
            feature=r["feature"],
            psi=r["psi"],
            alert=r["psi"] > PSI_ALERT,
            time=r["time"],
        )
        for r in rows
    ]
    return DriftReport(threshold=PSI_ALERT, respiratory_features=list(RESPIRATORY_FEATURES), cells=cells)


@router.get("/governance/fairness")
async def fairness(rt: Runtime, hospital: str | None = None) -> FairnessReport:
    """AUROC and calibration by age band and sex on the most recent labeled window; network-wide, or for one hospital."""
    ml = rt.sim.ml
    if hospital is not None and hospital not in rt.sim.world.hospitals:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown hospital {hospital}")
    report: dict[str, Any] | None = (ml.latest_fairness if hospital is None else ml.latest_fairness_by_hospital.get(hospital)) if ml else None
    if report is None:
        return FairnessReport(
            available=False,
            reason="No model is scoring yet" if ml is None else "The first report comes after one sim hour",
        )
    return FairnessReport(available=True, **report)


@router.get("/governance/audit")
async def audit(
    rt: Runtime,
    db: DbPool,
    actor: str | None = None,
    action: str | None = None,
    exclude: Annotated[str | None, Query(description="Comma-separated actions to leave out")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEntry]:
    excluded = [e for e in (exclude or "").split(",") if e]
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, actor, action, payload FROM audit_log
            WHERE time <= $1 AND ($2::text IS NULL OR actor = $2) AND ($3::text IS NULL OR action = $3)
              AND NOT (action = ANY($4::text[]))
            ORDER BY time DESC LIMIT $5
            """,
            rt.sim.now,
            actor,
            action,
            excluded,
            limit,
        )
    return [
        AuditEntry(
            time=r["time"],
            actor=r["actor"],
            action=r["action"],
            payload=json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
        )
        for r in rows
    ]


@router.get("/governance/model-card", response_class=PlainTextResponse)
async def model_card() -> str:
    """The model card as Markdown text (written by `make train`)."""
    if not MODEL_CARD.is_file():
        return "No model card yet. Run `make train`."
    return MODEL_CARD.read_text(encoding="utf-8")
