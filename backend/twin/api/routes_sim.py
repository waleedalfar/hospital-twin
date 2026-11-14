"""Simulation control and scenarios (§5.1, §5.6)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from twin.api.deps import runtime
from twin.api.runtime import ControlError, SimRuntime
from twin.common.api_models import FreezeRequest, PauseRequest, ScenarioRequest, SimState, SpeedRequest
from twin.common.ws import ScenarioInfo
from twin.sim.scenarios import ScenarioError

router = APIRouter()
Runtime = Annotated[SimRuntime, Depends(runtime)]


def state(rt: SimRuntime) -> SimState:
    return SimState(sim_time=rt.sim.now, speed=rt.speed, paused=rt.paused, frozen=rt.frozen, ready=rt.ready)


@router.get("/sim")
async def get_sim(rt: Runtime) -> SimState:
    return state(rt)


@router.post("/sim/speed")
async def set_speed(body: SpeedRequest, rt: Runtime) -> SimState:
    try:
        await rt.set_speed(body.speed)
    except ControlError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return state(rt)


@router.post("/sim/pause")
async def set_pause(body: PauseRequest, rt: Runtime) -> SimState:
    await rt.set_paused(body.paused)
    return state(rt)


@router.post("/sim/freeze")
async def set_freeze(body: FreezeRequest, rt: Runtime) -> SimState:
    await rt.set_frozen(body.frozen)
    return state(rt)


@router.post("/scenario", status_code=status.HTTP_201_CREATED)
async def start_scenario(body: ScenarioRequest, rt: Runtime) -> ScenarioInfo:
    try:
        scenario = await rt.start_scenario(body.name, body.hospital_id, body.lat, body.lon)
    except ScenarioError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return scenario.info(rt.sim.world)


@router.get("/scenario")
async def list_scenarios(rt: Runtime) -> list[ScenarioInfo]:
    return [s.info(rt.sim.world) for s in rt.sim.world.scenarios.values() if s.active]


@router.delete("/scenario/{scenario_id}")
async def stop_scenario(scenario_id: str, rt: Runtime) -> ScenarioInfo:
    try:
        scenario = await rt.stop_scenario(scenario_id)
    except ScenarioError as error:
        code = status.HTTP_404_NOT_FOUND if "Unknown" in str(error) else status.HTTP_409_CONFLICT
        raise HTTPException(code, str(error)) from error
    return scenario.info(rt.sim.world)
