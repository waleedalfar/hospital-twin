"""WebSocket message schema, version 1 (PROMPT.md §6.1).

These models are the single definition of what the browser receives. `shared/ws_schema.json` is generated
from them and the frontend types are generated from that file.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal[1] = 1

EntityKind = Literal["patient", "visitor", "nurse", "doctor", "surgeon", "emt"]
Pose = Literal["lying", "seated", "standing", "walking"]
BedStateName = Literal["occupied", "cleaning", "open", "blocked"]
HospitalStatus = Literal["open", "diverting", "offline"]
ArrivalMode = Literal["walk_in", "ambulance", "air"]
Complaint = Literal["respiratory", "cardiac", "trauma", "gi", "neuro", "infection", "other"]
RiskLevel = Literal["low", "medium", "high"]
VehicleKind = Literal["ambulance", "helicopter"]
VehicleStatus = Literal[
    "at_base", "to_scene", "on_scene", "to_hospital", "unloading", "returning", "transferring"
]
ScenarioName = Literal["flu_surge", "mass_casualty", "staff_shortage", "hospital_offline"]
ActionName = Literal["divert_ambulances", "expedite_discharge", "move_patient", "call_in_staff", "hold_bed"]


class Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Location(Msg):
    """Where an entity is. In a building: floor and room, plus the bed, seat or spot it holds (seat ids are
    given in `spot`). In a vehicle: `vehicle` is set and the rest may be empty."""

    floor: int | None
    room: str | None
    bed: str | None = None
    spot: str | None = None
    vehicle: str | None = None


class Appearance(Msg):
    skin: int = Field(ge=0, le=4)
    hair: int = Field(ge=0, le=4)
    headscarf: bool
    top: int = Field(default=0, ge=0, le=6)


class Vitals(Msg):
    hr: float
    spo2: float
    sbp: float
    dbp: float
    temp: float
    rr: float


class Risk(Msg):
    score: float = Field(ge=0, le=1)
    level: RiskLevel
    top_factors: list[tuple[str, float]]
    model_version: str


class Move(Msg):
    """A walk along the waypoint graph. `times[i]` is when the walker reaches `path[i]`; a pause between two
    nodes (waiting for the elevator) shows as two equal positions with different times."""

    path: list[str]
    times: list[datetime]
    depart: datetime
    arrive: datetime


class Entity(Msg):
    id: str
    kind: EntityKind
    location: Location
    appearance: Appearance
    pose: Pose
    move: Move | None = None
    task: str | None = None
    unit: str | None = None
    risk: Risk | None = None
    vitals: Vitals | None = None


class BedInfo(Msg):
    id: str
    patient_id: str | None
    state: BedStateName


class VehicleAtHospital(Msg):
    """A vehicle on this hospital's grounds: an ambulance in a bay slot or the helicopter on the roof."""

    id: str
    kind: VehicleKind
    status: VehicleStatus
    slot: str | None


class ScenarioInfo(Msg):
    id: str
    name: ScenarioName
    hospital_id: str | None
    started: datetime
    ends: datetime | None


class Kpis(Msg):
    census: int
    capacity: int
    er_wait_min: float
    waiting: int
    alerts: int


class HospitalRef(Msg):
    id: str
    name: str
    status: HospitalStatus


# ---- events -------------------------------------------------------------------------------------------


class Ev(Msg):
    time: datetime


class MoveEvent(Ev):
    kind: Literal["move"] = "move"
    entity_id: str
    from_: Location = Field(alias="from")
    to: Location
    path: list[str]
    times: list[datetime]
    depart: datetime
    arrive: datetime

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, serialize_by_alias=True)


class SpawnEvent(Ev):
    kind: Literal["spawn"] = "spawn"
    entity: Entity


DespawnReason = Literal["discharged", "transferred", "left", "off_duty", "boarded_vehicle"]


class DespawnEvent(Ev):
    kind: Literal["despawn"] = "despawn"
    entity_id: str
    reason: DespawnReason


class VitalsEvent(Ev):
    kind: Literal["vitals"] = "vitals"
    patient_id: str
    vitals: Vitals


class RiskEvent(Ev):
    kind: Literal["risk"] = "risk"
    patient_id: str
    score: float
    level: RiskLevel
    top_factors: list[tuple[str, float]]
    model_version: str


class BedEvent(Ev):
    kind: Literal["bed"] = "bed"
    bed_id: str
    patient_id: str | None
    state: BedStateName


class ArrivalEvent(Ev):
    kind: Literal["arrival"] = "arrival"
    patient_id: str
    mode: ArrivalMode
    esi: int
    complaint: Complaint
    encounter_id: int


class TriageEvent(Ev):
    kind: Literal["triage"] = "triage"
    patient_id: str
    esi: int


class ErAdmitEvent(Ev):
    kind: Literal["er_admit"] = "er_admit"
    patient_id: str
    bed_id: str
    wait_min: float


class AdmitEvent(Ev):
    kind: Literal["admit"] = "admit"
    patient_id: str
    unit: str
    bed_id: str


class SurgeryEvent(Ev):
    kind: Literal["surgery"] = "surgery"
    patient_id: str
    phase: Literal["start", "end"]


class DischargeEvent(Ev):
    kind: Literal["discharge"] = "discharge"
    patient_id: str
    los_h: float
    expedited: bool


class TransferEvent(Ev):
    kind: Literal["transfer"] = "transfer"
    patient_id: str
    to_hospital: str
    vehicle_id: str


class CriticalEvent(Ev):
    """Escalation to ICU or a rapid response. These are the deterioration model's labels (§5.4)."""

    kind: Literal["critical"] = "critical"
    patient_id: str
    unit: str
    response: Literal["icu_transfer", "rapid_response"]


class AlertEvent(Ev):
    kind: Literal["alert"] = "alert"
    patient_id: str
    level: RiskLevel
    score: float


class StaffEvent(Ev):
    kind: Literal["staff"] = "staff"
    entity_id: str
    change: Literal["on_duty", "off_duty"]
    reason: str


class AmbulanceEvent(Ev):
    kind: Literal["ambulance"] = "ambulance"
    vehicle_id: str
    vehicle_kind: VehicleKind
    status: VehicleStatus
    slot: str | None
    destination: str | None
    patient_id: str | None


class HospitalStatusEvent(Ev):
    kind: Literal["hospital_status"] = "hospital_status"
    status: HospitalStatus
    until: datetime | None
    reason: str


class ScenarioEvent(Ev):
    kind: Literal["scenario"] = "scenario"
    scenario_id: str
    name: ScenarioName
    status: Literal["started", "stopped", "ended"]
    hospital_id: str | None
    params: dict[str, str | float | int]


class ActionEvent(Ev):
    kind: Literal["action"] = "action"
    action: ActionName
    params: dict[str, str | float | int | list[str]]
    result: str


SimEvent = Annotated[
    MoveEvent
    | SpawnEvent
    | DespawnEvent
    | VitalsEvent
    | RiskEvent
    | BedEvent
    | ArrivalEvent
    | TriageEvent
    | ErAdmitEvent
    | AdmitEvent
    | SurgeryEvent
    | DischargeEvent
    | TransferEvent
    | CriticalEvent
    | AlertEvent
    | StaffEvent
    | AmbulanceEvent
    | HospitalStatusEvent
    | ScenarioEvent
    | ActionEvent,
    Field(discriminator="kind"),
]


# ---- messages -----------------------------------------------------------------------------------------


class SimControl(Msg):
    sim_time: datetime
    speed: int
    paused: bool
    frozen: bool


class SnapshotMessage(SimControl):
    v: Literal[1] = SCHEMA_VERSION
    type: Literal["snapshot"] = "snapshot"
    hospital: HospitalRef
    entities: list[Entity]
    beds: list[BedInfo]
    vehicles: list[VehicleAtHospital]
    scenarios: list[ScenarioInfo]
    kpis: Kpis


class EventsMessage(SimControl):
    v: Literal[1] = SCHEMA_VERSION
    type: Literal["events"] = "events"
    events: list[SimEvent]
    kpis: Kpis


class RoutePoint(Msg):
    lat: float
    lon: float
    t: datetime


class NetworkVehicle(Msg):
    id: str
    kind: VehicleKind
    home: str
    status: VehicleStatus
    destination: str | None
    patient_id: str | None
    lat: float
    lon: float
    route: list[RoutePoint]


class NetworkHospital(Msg):
    id: str
    name: str
    lat: float
    lon: float
    status: HospitalStatus
    status_until: datetime | None
    kpis: Kpis


class NetworkMessage(SimControl):
    v: Literal[1] = SCHEMA_VERSION
    type: Literal["network"] = "network"
    hospitals: list[NetworkHospital]
    vehicles: list[NetworkVehicle]
    scenarios: list[ScenarioInfo]


class ErrorMessage(Msg):
    v: Literal[1] = SCHEMA_VERSION
    type: Literal["error"] = "error"
    message: str


ServerMessage = Annotated[
    SnapshotMessage | EventsMessage | NetworkMessage | ErrorMessage, Field(discriminator="type")
]
