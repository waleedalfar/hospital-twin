"""Operations agent recommendations (PROMPT.md §6.2, §9)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from twin.agent.ask import AskRefusedError, AskResponse, AskService
from twin.agent.service import AgentService, RecError
from twin.api.deps import runtime
from twin.api.runtime import SimRuntime
from twin.common.api_models import ApproveResponse
from twin.common.ws import AgentRecModel

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]


def agent_of(rt: SimRuntime) -> AgentService:
    if rt.agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The operations agent is turned off (AGENT_ENABLED)")
    return rt.agent


@router.get("/agent/recs")
async def list_recs(
    rt: Runtime,
    hospital: str | None = None,
    state: Annotated[str | None, Query(alias="status", pattern="^(pending|approved|dismissed|expired)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AgentRecModel]:
    return await agent_of(rt).list(hospital, state, limit)


@router.post("/agent/recs/{rec_id}/approve")
async def approve(rec_id: str, rt: Runtime) -> ApproveResponse:
    """Apply the recommendation to the simulation and write the audit log."""
    try:
        rec, result = await agent_of(rt).approve(rec_id)
    except RecError as error:
        raise HTTPException(error.status, str(error)) from error
    return ApproveResponse(rec=rec, result=result)


@router.post("/agent/recs/{rec_id}/dismiss")
async def dismiss(rec_id: str, rt: Runtime) -> AgentRecModel:
    try:
        return await agent_of(rt).dismiss(rec_id)
    except RecError as error:
        raise HTTPException(error.status, str(error)) from error


class AskRequest(BaseModel):
    question: str = Field(max_length=2000)
    hospital_id: str


@router.post("/agent/ask")
async def ask(body: AskRequest, request: Request) -> AskResponse:
    """Answer a spoken or typed question with the read-only tools: Gemini when configured, the intent parser otherwise."""
    service: AskService | None = getattr(request.app.state, "ask", None)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The simulation is not running")
    try:
        return await service.ask(body.question, body.hospital_id)
    except AskRefusedError as error:
        raise HTTPException(error.status, str(error)) from error
