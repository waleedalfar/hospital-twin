"""The simulation world: clock, random streams, hospitals, event output and walking (PROMPT.md §5).

Time inside SimPy is in sim minutes since `epoch`. One tick is one sim minute. Everything the outside world
sees goes through `emit`, which collects events for the current tick.
"""

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import simpy

from twin.common.ws import Appearance, Location, Move, MoveEvent, SimEvent
from twin.sim.config import HEADSCARF_SHARE, SIM_START
from twin.sim.entities import MovePlan, Patient, PatientProfile, Person, Place
from twin.sim.hospital import HospitalState
from twin.sim.layout_model import Layout
from twin.sim.pathing import Router, stream, timeline

if TYPE_CHECKING:
    from twin.sim.scenarios import Scenario
    from twin.sim.vehicles import Vehicle

SimGen = Generator[simpy.Event, Any, Any]


class Waiter(Protocol):
    """Anything that can wait and be interrupted: a person or a vehicle."""

    kick: simpy.Event | None
    kick_cause: tuple[str, str] | None


@dataclass
class Emitted:
    hospital_id: str | None
    event: SimEvent


@dataclass
class PoolState:
    """Synthea patients available to arrive; a patient who is present cannot arrive again."""

    profiles: list[PatientProfile]
    present: set[str] = field(default_factory=set)


class World:
    def __init__(self, layout: Layout, profiles: list[PatientProfile], seed: int, epoch: datetime) -> None:
        if not profiles:
            raise ValueError("The patient pool is empty. Run `make seed` to load Synthea patients.")
        self.layout = layout
        self.seed = seed
        self.epoch = epoch
        self.env = simpy.Environment()
        self.router = Router(layout)
        self.pool = PoolState(profiles=sorted(profiles, key=lambda p: p.id))
        self.hospitals: dict[str, HospitalState] = {h.id: HospitalState(id=h.id, name=h.name, layout=layout, env=self.env) for h in layout.hospitals}
        self.outbox: list[Emitted] = []
        self._counters: dict[str, int] = {}
        self._streams: dict[tuple[str, ...], Any] = {}
        self.vehicles: dict[str, Vehicle] = {}
        self.staff: dict[str, Person] = {}
        self.scenarios: dict[str, Scenario] = {}

    # ---- time and randomness --------------------------------------------------------------------------

    @property
    def now(self) -> float:
        return float(self.env.now)

    def time(self, minutes: float | None = None) -> datetime:
        return self.epoch + timedelta(minutes=self.now if minutes is None else minutes)

    def minutes(self, when: datetime) -> float:
        return (when - self.epoch).total_seconds() / 60.0

    def local_hour(self, minutes: float | None = None) -> int:
        from twin.sim.config import LOCAL_TZ

        return self.time(minutes).astimezone(LOCAL_TZ).hour

    def rng(self, *names: str) -> Any:
        """The random stream for `names`, created on first use. `random.Random` has no precise stubs for the
        methods used here, so it is typed loosely."""
        if names not in self._streams:
            self._streams[names] = stream(self.seed, *names)
        return self._streams[names]

    def next_id(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}-{n}"

    def next_number(self, name: str) -> int:
        n = self._counters.get(name, 0) + 1
        self._counters[name] = n
        return n

    def appearance(self, entity_id: str) -> Appearance:
        r = stream(self.seed, "appearance", entity_id)
        return Appearance(
            skin=r.randrange(5),
            hair=r.randrange(5),
            headscarf=r.random() < HEADSCARF_SHARE,
            top=r.randrange(7),
        )

    # ---- output ---------------------------------------------------------------------------------------

    def emit(self, hospital_id: str | None, event: SimEvent) -> None:
        self.outbox.append(Emitted(hospital_id, event))

    def drain(self) -> list[Emitted]:
        out, self.outbox = self.outbox, []
        return out

    # ---- people and places ----------------------------------------------------------------------------

    def node_of(self, hospital: HospitalState, place: Place) -> str:
        layout = self.layout
        if place.bed is not None:
            return layout.spots_by_id[layout.beds_by_id[place.bed].spot].node
        if place.spot is not None:
            if place.spot in layout.seats_by_id:
                return layout.seats_by_id[place.spot].node
            return layout.spots_by_id[place.spot].node
        if place.vehicle is not None:
            slot = hospital.slots_used.get(place.vehicle)
            if slot is not None:
                return layout.spots_by_id[next(s.spot for s in layout.outside.ambulance_slots if s.id == slot)].node
            if place.vehicle.startswith("HELI-"):
                return layout.spots_by_id[layout.roof.helipad_spot].node
            return layout.spots_by_id[layout.outside.curb_spot].node
        raise ValueError(f"Place {place} has no waypoint")

    def location(self, place: Place) -> Location:
        return Location(floor=place.floor, room=place.room, bed=place.bed, spot=place.spot, vehicle=place.vehicle)

    def curb(self) -> Place:
        spot = self.layout.spots_by_id[self.layout.outside.curb_spot]
        return Place(floor=spot.floor, room=spot.room, spot=spot.id)

    def walk(self, hospital: HospitalState, person: Person, dest: Place, *, start: Place | None = None) -> SimGen:
        """Walk `person` to `dest`. The person's place becomes `dest` at once (it is reserved); the walk
        itself is described by `person.move` until arrival."""
        origin = start if start is not None else person.place
        path = self.router.path(self.node_of(hospital, origin), self.node_of(hospital, dest))
        nodes, times = timeline(self.router, path, self.now, hospital.elevator)
        yield from self.follow(hospital, person, origin, dest, MovePlan(nodes, times))

    def follow(self, hospital: HospitalState, person: Person, origin: Place, dest: Place, plan: MovePlan) -> SimGen:
        """Walk along an already planned route (used to keep an escort and a patient together)."""
        person.place = dest
        person.move = plan
        self.emit(
            hospital.id,
            MoveEvent.model_validate(
                {
                    "time": self.time(),
                    "entity_id": person.id,
                    "from": self.location(origin),
                    "to": self.location(dest),
                    "path": plan.path,
                    "times": [self.time(t) for t in plan.times],
                    "depart": self.time(plan.times[0]),
                    "arrive": self.time(plan.arrive),
                }
            ),
        )
        yield self.env.timeout(max(0.0, plan.arrive - self.now))
        if person.move is plan:
            person.move = None

    def move_model(self, plan: MovePlan | None) -> Move | None:
        if plan is None or plan.arrive <= self.now:
            return None
        return Move(
            path=plan.path,
            times=[self.time(t) for t in plan.times],
            depart=self.time(plan.times[0]),
            arrive=self.time(plan.arrive),
        )

    # ---- waiting with interruption --------------------------------------------------------------------

    def kick(self, person: Waiter, cause: str, detail: str = "") -> bool:
        """Interrupt whatever `person` is waiting for. Returns False if they are not waiting."""
        if person.kick is None or person.kick.triggered:
            return False
        person.kick_cause = (cause, detail)
        person.kick.succeed()
        return True

    def wait(self, person: Waiter, event: simpy.Event) -> SimGen:
        """Wait for `event` unless `person` is kicked first. Returns True if `event` happened."""
        person.kick = self.env.event()
        result = yield self.env.any_of([event, person.kick])
        kicked = person.kick in result
        person.kick = None
        return event in result and not kicked

    def wait_for(self, person: Waiter, minutes: float) -> SimGen:
        done = yield from self.wait(person, self.env.timeout(max(0.0, minutes)))
        return done

    def staff_by_id(self, staff_id: str) -> Person | None:
        return self.staff.get(staff_id)

    def patient(self, patient_id: str) -> tuple[HospitalState, Patient] | None:
        for hospital in self.hospitals.values():
            person = hospital.people.get(patient_id)
            if isinstance(person, Patient):
                return hospital, person
        return None


def default_epoch(warmup: timedelta) -> datetime:
    return SIM_START - warmup
