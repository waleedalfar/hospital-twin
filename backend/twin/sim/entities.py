"""Simulation entities: people and vehicles, and where they are."""

from dataclasses import dataclass, field
from typing import Literal

import simpy

from twin.common.ws import Appearance, ArrivalMode, Complaint, EntityKind, Risk, Vitals

PatientPhase = Literal[
    "waiting_triage",
    "triage",
    "waiting_er",
    "er",
    "surgery_wait",
    "surgery",
    "recovery",
    "inpatient",
    "escalate",
    "relocate",
    "discharge",
    "transfer",
    "gone",
]


@dataclass(frozen=True)
class Place:
    """Where an entity is or is heading. Exactly one of bed, spot (a seat or work spot) or vehicle is set,
    except for the curb, which is a shared spot."""

    floor: int | None
    room: str | None
    bed: str | None = None
    spot: str | None = None
    vehicle: str | None = None


@dataclass
class MovePlan:
    path: list[str]
    times: list[float]

    @property
    def arrive(self) -> float:
        return self.times[-1]


@dataclass(frozen=True)
class PatientProfile:
    """A Synthea patient from the `patients` table (§4.3). Only these fields are used by the simulation."""

    id: str
    age: int
    sex: str
    comorbidity_count: int
    conditions: tuple[str, ...]


@dataclass
class Physiology:
    """Hidden state. The latent severity `s` never leaves the simulation (§5.4)."""

    s: float
    mu: float
    respiratory: bool
    episode_until: float = -1.0
    episode_drift: float = 0.0
    cooldown_until: float = -1.0
    last_vitals_at: float = -1e9


@dataclass
class Person:
    id: str
    kind: EntityKind
    hospital_id: str | None
    place: Place
    appearance: Appearance
    move: MovePlan | None = None
    task: str | None = None
    unit: str | None = None
    kick: simpy.Event | None = None
    kick_cause: tuple[str, str] | None = None


@dataclass
class Patient(Person):
    profile: PatientProfile | None = None
    mode: ArrivalMode = "walk_in"
    esi: int = 3
    complaint: Complaint = "other"
    encounter_id: int = 0
    arrived_at: float = 0.0
    admitted_at: float | None = None
    phase: PatientPhase = "waiting_triage"
    disposition: str | None = None
    target_unit: str | None = None
    los_end: float | None = None
    expedited: bool = False
    physiology: Physiology | None = None
    vitals: Vitals | None = None
    visitor_id: str | None = None
    reserved_bed: str | None = None
    er_bed_at: float | None = None
    risk: Risk | None = None


@dataclass
class Staff(Person):
    home_hospital: str = ""
    prays: bool = False
    on_duty: bool = True
    last_break: float = 0.0
    prayed: set[tuple[int, int]] = field(default_factory=set)
    assignment: str | None = None
    vehicle_id: str | None = None


@dataclass
class Visitor(Person):
    patient_id: str = ""
    leave_at: float = 0.0
