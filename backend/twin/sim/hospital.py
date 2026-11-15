"""State of one hospital: its beds, seats, spots, queues and the people inside."""

from collections import deque
from dataclasses import dataclass, field

import simpy

from twin.common.ws import BedStateName, HospitalStatus
from twin.sim.entities import Patient, Person, Place, Staff
from twin.sim.layout_model import Layout
from twin.sim.pathing import ElevatorSchedule
from twin.sim.pools import SlotPool

BED_UNITS = ("ER", "WARD", "REC", "ICU")
# Spots that several people may pass through at once; everything else holds one person.
SHARED_SPOT_KINDS = frozenset({"curb", "unload", "helipad"})


@dataclass
class BedSlot:
    id: str
    unit: str
    state: BedStateName = "open"
    patient_id: str | None = None


@dataclass
class Counters:
    arrived: int = 0
    discharged: int = 0
    transferred_out: int = 0


@dataclass
class HospitalState:
    id: str
    name: str
    layout: Layout
    env: simpy.Environment
    status: HospitalStatus = "open"
    status_until: float | None = None
    beds: dict[str, BedSlot] = field(default_factory=dict)
    pools: dict[str, SlotPool] = field(default_factory=dict)
    holders: dict[str, str] = field(default_factory=dict)
    people: dict[str, Person] = field(default_factory=dict)
    counters: Counters = field(default_factory=Counters)
    elevator: ElevatorSchedule = field(default_factory=ElevatorSchedule)
    er_waits: deque[tuple[float, float]] = field(default_factory=deque)
    status_changed: simpy.Event | None = None
    slots_used: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for bed in self.layout.beds:
            self.beds[bed.id] = BedSlot(id=bed.id, unit=bed.unit)
        for unit in BED_UNITS:
            self.pools[unit] = SlotPool(self.env, [b.id for b in self.layout.beds if b.unit == unit])
        triage = [s.id for s in self.layout.seats if s.kind == "triage"]
        self.pools["TRIAGE"] = SlotPool(self.env, triage)
        self.pools["OR"] = SlotPool(self.env, [s.id for s in self.layout.spots if s.kind == "table" and s.room == "OR"])
        self.status_changed = self.env.event()

    # ---- places ---------------------------------------------------------------------------------------

    def place_of_bed(self, bed_id: str) -> Place:
        bed = self.layout.beds_by_id[bed_id]
        return Place(floor=bed.floor, room=bed.room, bed=bed_id)

    def place_of_spot(self, spot_id: str) -> Place:
        if spot_id in self.layout.seats_by_id:
            seat = self.layout.seats_by_id[spot_id]
            return Place(floor=seat.floor, room=seat.room, spot=spot_id)
        spot = self.layout.spots_by_id[spot_id]
        return Place(floor=spot.floor, room=spot.room, spot=spot_id)

    def pool_for_spot(self, spot_id: str) -> SlotPool | None:
        """Triage seats and the operating table are handed out by a queue, not claimed directly."""
        if spot_id in self.layout.seats_by_id and self.layout.seats_by_id[spot_id].kind == "triage":
            return self.pools["TRIAGE"]
        spot = self.layout.spots_by_id.get(spot_id)
        if spot is not None and spot.kind == "table" and spot.room == "OR":
            return self.pools["OR"]
        return None

    def is_shared(self, spot_id: str) -> bool:
        spot = self.layout.spots_by_id.get(spot_id)
        return spot is not None and spot.kind in SHARED_SPOT_KINDS

    def claim(self, spot_id: str, person_id: str) -> bool:
        """Reserve a seat or spot for `person_id`. Shared spots always succeed and are not recorded."""
        if self.is_shared(spot_id):
            return True
        if spot_id in self.holders:
            return self.holders[spot_id] == person_id
        self.holders[spot_id] = person_id
        return True

    def release_place(self, place: Place, person_id: str) -> None:
        if place.spot is not None and self.holders.get(place.spot) == person_id:
            del self.holders[place.spot]

    def first_free(self, spot_ids: list[str]) -> str | None:
        return next((s for s in spot_ids if s not in self.holders), None)

    def spots_where(self, *, room: str | None = None, kinds: tuple[str, ...] = (), rooms: tuple[str, ...] = ()) -> list[str]:
        found = [
            s.id for s in self.layout.spots if (room is None or s.room == room) and (not kinds or s.kind in kinds) and (not rooms or s.room in rooms)
        ]
        return found

    def seats_where(self, kind: str) -> list[str]:
        return [s.id for s in self.layout.seats if s.kind == kind]

    # ---- beds -----------------------------------------------------------------------------------------

    def unit_rooms(self, unit: str) -> tuple[str, ...]:
        return tuple(r.id for r in self.layout.rooms.values() if r.unit == unit)

    def patients(self) -> list[Patient]:
        return [p for p in self.people.values() if isinstance(p, Patient)]

    def staff(self) -> list[Staff]:
        return [p for p in self.people.values() if isinstance(p, Staff)]

    def bedded(self, unit: str | None = None) -> list[Patient]:
        return [p for p in self.patients() if p.place.bed is not None and (unit is None or self.beds[p.place.bed].unit == unit)]
