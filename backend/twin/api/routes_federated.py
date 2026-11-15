"""Federated training and the live model switch (PROMPT.md §6.2, §7.6)."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from twin.api.deps import runtime
from twin.api.federated import FederatedError, FederatedService
from twin.api.runtime import SimRuntime
from twin.common.ws import FederatedMessage
from twin.ml.fed_model import FED_VERSION, FederatedMlp
from twin.ml.model import MODELS_DIR, DeteriorationModel, RiskModel
from twin.ml.train import MODEL_VERSION

logger = logging.getLogger(__name__)
router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]


class FederatedStatus(BaseModel):
    state: FederatedMessage
    result: dict[str, Any] | None
    available: bool


class ActiveModelRequest(BaseModel):
    version: str


class ActiveModelResponse(BaseModel):
    active_deterioration: str
    previous: str


def service_of(request: Request) -> FederatedService:
    service: FederatedService | None = getattr(request.app.state, "federated", None)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The simulation is not running")
    return service


@router.get("/federated")
async def federated_status(request: Request) -> FederatedStatus:
    """The current run's progress and the saved three-way comparison, if a run has finished."""
    service = service_of(request)
    return FederatedStatus(state=service.state, result=service.result(MODEL_VERSION), available=(MODELS_DIR / FED_VERSION / "weights.npz").is_file())


@router.post("/federated/run", status_code=status.HTTP_202_ACCEPTED)
async def federated_run(request: Request) -> FederatedMessage:
    """Start federated training in the background; progress arrives as `federated` WebSocket messages."""
    try:
        return await service_of(request).start()
    except FederatedError as error:
        raise HTTPException(error.status, str(error)) from error


@router.post("/models/active")
async def set_active_model(body: ActiveModelRequest, rt: Runtime) -> ActiveModelResponse:
    """Choose which deterioration model scores patients: the central LightGBM or the federated MLP. Audited."""
    ml = rt.sim.ml
    if ml is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No models are loaded. Run `make train`.")
    loaders: dict[str, Any] = {MODEL_VERSION: DeteriorationModel.load, FED_VERSION: FederatedMlp.load}
    if body.version not in loaders:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown model {body.version}; choose one of {sorted(loaders)}")
    try:
        model: RiskModel = loaders[body.version](body.version)
    except FileNotFoundError as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{body.version} has not been trained yet ({'run make fed-train' if body.version == FED_VERSION else 'run make train'})",
        ) from error
    previous = ml.model.version
    ml.model = model
    ml.score_all()  # rescore now, so every score on screen carries the new version
    await rt.publish_now()
    await rt.audit("model_switch", {"from": previous, "to": body.version})
    logger.info("Live deterioration model: %s -> %s", previous, body.version)
    return ActiveModelResponse(active_deterioration=body.version, previous=previous)
