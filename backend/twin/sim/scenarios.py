"""Scenarios (PROMPT.md §5.6). Each one writes an event, shows in the UI and can be stopped."""

from dataclasses import dataclass, field
from typing import Literal

from twin.common.ws import ScenarioEvent, ScenarioInfo, ScenarioName
from twin.sim import config as c
from twin.sim.entities import Staff
from twin.sim.vehicles import snap_to_roads
from twin.sim.world import SimGen, World

ScenarioStatus = Literal["started", "stopped", "ended"]


class ScenarioError(Exception):
    """A scenario request is invalid (unknown hospital, unknown id, already stopped)."""


@dataclass
class Scenario:
    id: str
    name: ScenarioName
    hospital_id: str | None
    started: float
    ends: float | None
    params: dict[str, str | float | int]
    active: bool = True
    off_duty: list[str] = field(default_factory=list)

    def info(self, world: World) -> ScenarioInfo:
        return ScenarioInfo(
            id=self.id,
            name=self.name,
            hospital_id=self.hospital_id,
            started=world.time(self.started),
            ends=None if self.ends is None else world.time(self.ends),
        )


def active(world: World, name: ScenarioName, hospital_id: str) -> bool:
    return any(s.active and s.name == name and s.hospital_id in (None, hospital_id) for s in world.scenarios.values())


def flu_active(world: World, hospital_id: str) -> bool:
    return active(world, "flu_surge", hospital_id)


def demand_multiplier(world: World, hospital_id: str) -> float:
    return c.FLU_MULTIPLIER if flu_active(world, hospital_id) else 1.0


def nearest_hospital(world: World, lat: float, lon: float) -> str:
    from twin.sim.vehicles import hospital_point, km

    return min((h.id for h in world.layout.hospitals), key=lambda h: (km((lat, lon), hospital_point(world, h)), h))


def emit(world: World, scenario: Scenario, status: ScenarioStatus) -> None:
    world.emit(
        scenario.hospital_id,
        ScenarioEvent(
            time=world.time(),
            scenario_id=scenario.id,
            name=scenario.name,
            status=status,
            hospital_id=scenario.hospital_id,
            params=scenario.params,
        ),
    )


def start(world: World, name: ScenarioName, hospital_id: str | None, lat: float | None, lon: float | None) -> Scenario:
    from twin.sim.vehicles import set_hospital_status

    if hospital_id is not None and hospital_id not in world.hospitals:
        raise ScenarioError(f"Unknown hospital {hospital_id}")
    if name in ("staff_shortage", "hospital_offline") and hospital_id is None:
        raise ScenarioError(f"{name} needs a hospital_id")
    params: dict[str, str | float | int] = {}
    ends: float | None = None
    if name == "flu_surge":
        ends = world.now + c.FLU_DURATION_MIN
        params = {"multiplier": c.FLU_MULTIPLIER, "duration_min": c.FLU_DURATION_MIN}
    elif name == "staff_shortage":
        ends = world.now + c.SHORTAGE_DURATION_MIN
        params = {"share": c.SHORTAGE_SHARE, "duration_min": c.SHORTAGE_DURATION_MIN}
    elif name == "mass_casualty":
        if lat is None or lon is None:
            raise ScenarioError("mass_casualty needs the incident location (lat, lon)")
        hospital_id = nearest_hospital(world, lat, lon)
        ends = world.now + c.MASS_CASUALTY_WINDOW_MIN
        params = {
            "lat": lat,
            "lon": lon,
            "count": c.MASS_CASUALTY_COUNT,
            "window_min": c.MASS_CASUALTY_WINDOW_MIN,
        }
    scenario = Scenario(world.next_id("SC"), name, hospital_id, world.now, ends, params)
    world.scenarios[scenario.id] = scenario
    emit(world, scenario, "started")
    if name == "staff_shortage" and hospital_id is not None:
        shortage(world, scenario, hospital_id)
    elif name == "hospital_offline" and hospital_id is not None:
        set_hospital_status(world, world.hospitals[hospital_id], "offline", None, f"scenario {scenario.id}")
    elif name == "mass_casualty" and lat is not None and lon is not None:
        world.env.process(mass_casualty(world, scenario, snap_to_roads(world, lat, lon)))
    if ends is not None:
        world.env.process(end_later(world, scenario))
    return scenario


def shortage(world: World, scenario: Scenario, hospital_id: str) -> None:
    from twin.sim.staff import send_off_duty

    hospital = world.hospitals[hospital_id]
    nurses = sorted((s for s in hospital.staff() if s.kind == "nurse" and s.on_duty), key=lambda s: s.id)
    count = round(len(nurses) * c.SHORTAGE_SHARE)
    rng = world.rng("shortage", scenario.id)
    for nurse in sorted(rng.sample(nurses, count), key=lambda s: s.id):
        scenario.off_duty.append(nurse.id)
        send_off_duty(world, hospital, nurse, f"scenario {scenario.id}")


def mass_casualty(world: World, scenario: Scenario, scene: tuple[float, float]) -> SimGen:
    from twin.sim.vehicles import helicopter_run, run_call

    rng = world.rng("mass-casualty", scenario.id)
    gap = c.MASS_CASUALTY_WINDOW_MIN / c.MASS_CASUALTY_COUNT
    world.env.process(helicopter_run(world, scene))
    for _ in range(c.MASS_CASUALTY_COUNT):
        if not scenario.active or scenario.hospital_id is None:
            return
        esi = int(rng.choices((1, 2, 3, 4), weights=(0.15, 0.35, 0.35, 0.15))[0])
        world.env.process(run_call(world, scenario.hospital_id, scene, complaint="trauma", forced=scenario.hospital_id, esi=esi))
        yield world.env.timeout(gap)


def end_later(world: World, scenario: Scenario) -> SimGen:
    yield world.env.timeout((scenario.ends or world.now) - world.now)
    if scenario.active:
        finish(world, scenario, "ended")


def stop(world: World, scenario_id: str) -> Scenario:
    scenario = world.scenarios.get(scenario_id)
    if scenario is None:
        raise ScenarioError(f"Unknown scenario {scenario_id}")
    if not scenario.active:
        raise ScenarioError(f"Scenario {scenario_id} is not running")
    finish(world, scenario, "stopped")
    return scenario


def finish(world: World, scenario: Scenario, status: ScenarioStatus) -> None:
    from twin.sim.staff import enter
    from twin.sim.vehicles import set_hospital_status

    scenario.active = False
    scenario.ends = world.now
    if scenario.name == "staff_shortage" and scenario.hospital_id is not None:
        hospital = world.hospitals[scenario.hospital_id]
        for staff_id in scenario.off_duty:
            staff = world.staff_by_id(staff_id)
            if not isinstance(staff, Staff):
                continue
            if staff.hospital_id is None:
                staff.place = world.curb()
                enter(world, hospital, staff, f"scenario {scenario.id} {status}")
            else:
                staff.on_duty = True
    if scenario.name == "hospital_offline" and scenario.hospital_id is not None:
        hospital = world.hospitals[scenario.hospital_id]
        if hospital.status == "offline":
            set_hospital_status(world, hospital, "open", None, f"scenario {scenario.id} {status}")
    emit(world, scenario, status)
