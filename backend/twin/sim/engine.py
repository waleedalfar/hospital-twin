"""The simulation as one object: build it, advance it a tick at a time, steer it (§5)."""

from datetime import datetime, timedelta

from twin.common.ws import ActionName, NetworkMessage, ScenarioName, SnapshotMessage
from twin.ml.inference import InferenceEngine
from twin.sim import actions, nurses, scenarios
from twin.sim.arrivals import walk_ins
from twin.sim.config import DEFAULT_WARMUP, SIM_START, TICK_MIN
from twin.sim.entities import PatientProfile
from twin.sim.invariants import check
from twin.sim.layout_model import Layout
from twin.sim.monitoring import monitor
from twin.sim.snapshot import hospital_snapshot, network_message
from twin.sim.staff import build_staff
from twin.sim.vehicles import build_vehicles, calls
from twin.sim.world import Emitted, World


class Simulation:
    """Three hospitals and the city. Sim time 0 is `SIM_START - warmup`; the warm-up fills the hospitals so
    that the visible run at SIM_START starts from a realistic state."""

    def __init__(
        self,
        layout: Layout,
        profiles: list[PatientProfile],
        seed: int,
        warmup: timedelta = DEFAULT_WARMUP,
        *,
        debug: bool = False,
    ) -> None:
        self.world = World(layout, profiles, seed, SIM_START - warmup)
        self.debug = debug
        self.ml: InferenceEngine | None = None
        world = self.world
        for hospital_id in sorted(world.hospitals):
            build_staff(world, world.hospitals[hospital_id])
        build_vehicles(world)
        for hospital_id in sorted(world.hospitals):
            world.env.process(walk_ins(world, world.hospitals[hospital_id]))
            world.env.process(calls(world, hospital_id))
        world.env.process(monitor(world))

    @property
    def now(self) -> datetime:
        return self.world.time()

    @property
    def visible_start(self) -> datetime:
        return SIM_START

    def tick(self) -> list[Emitted]:
        """Advance one sim minute and return everything that happened in it."""
        world = self.world
        world.env.run(until=world.now + TICK_MIN)
        if self.debug:
            check(world)
        nurses.assign_nurses(world)
        emitted = world.drain()
        if self.ml is not None:
            self.ml.after_tick(emitted)
            emitted.extend(world.drain())  # risk scores and alerts produced by the models
        return emitted

    def run_until(self, when: datetime) -> list[Emitted]:
        out: list[Emitted] = []
        while self.world.time() < when:
            out.extend(self.tick())
        return out

    def start_scenario(self, name: ScenarioName, hospital_id: str | None, lat: float | None = None, lon: float | None = None) -> scenarios.Scenario:
        return scenarios.start(self.world, name, hospital_id, lat, lon)

    def stop_scenario(self, scenario_id: str) -> scenarios.Scenario:
        return scenarios.stop(self.world, scenario_id)

    def apply_action(self, action: ActionName, params: dict[str, str | float | int | list[str]]) -> str:
        return actions.apply(self.world, action, params)

    def snapshot(self, hospital_id: str, speed: int, paused: bool, frozen: bool) -> SnapshotMessage:
        return hospital_snapshot(self.world, hospital_id, speed, paused, frozen)

    def network(self, speed: int, paused: bool, frozen: bool) -> NetworkMessage:
        return network_message(self.world, speed, paused, frozen)

    def attach_ml(self, engine: InferenceEngine) -> None:
        """Score patients and forecast demand as the simulation runs (PROMPT.md §7.4)."""
        self.ml = engine

    def check_invariants(self) -> None:
        check(self.world)
