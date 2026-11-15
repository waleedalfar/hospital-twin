"""Turns simulation state into WebSocket messages (PROMPT.md §6.1). Nothing hidden (the latent severity)
is ever copied into these models."""

from twin.common.ws import (
    BedInfo,
    Entity,
    HospitalRef,
    Kpis,
    NetworkHospital,
    NetworkMessage,
    NetworkVehicle,
    Pose,
    RoutePoint,
    ScenarioInfo,
    SnapshotMessage,
    VehicleAtHospital,
)
from twin.sim.entities import Patient, Person, Visitor
from twin.sim.hospital import BED_UNITS, HospitalState
from twin.sim.world import World

ER_WAIT_WINDOW_MIN = 60.0


def pose_of(world: World, person: Person) -> Pose:
    if person.move is not None and person.move.arrive > world.now:
        return "walking"
    if person.place.bed is not None:
        return "lying"
    spot = person.place.spot
    if spot is not None and spot in world.layout.seats_by_id:
        return "seated"
    if spot is not None and world.layout.spots_by_id[spot].kind == "table":
        return "lying"
    return "standing"


def entity_model(world: World, person: Person) -> Entity:
    vitals = person.vitals if isinstance(person, Patient) else None
    return Entity(
        id=person.id,
        kind=person.kind,
        location=world.location(person.place),
        appearance=person.appearance,
        pose=pose_of(world, person),
        move=world.move_model(person.move),
        task=person.task,
        unit=person.unit,
        risk=person.risk if isinstance(person, Patient) else None,
        expected_discharge_h=person.expected_discharge_h if isinstance(person, Patient) else None,
        vitals=vitals,
    )


def kpis(world: World, hospital: HospitalState) -> Kpis:
    """Live KPIs. `er_wait_min` averages the arrival-to-ER-bay wait of patients who got a bay in the last
    hour together with the time already waited by patients still waiting, so it rises during a surge."""
    while hospital.er_waits and hospital.er_waits[0][0] < world.now - ER_WAIT_WINDOW_MIN:
        hospital.er_waits.popleft()
    waits = [w for _, w in hospital.er_waits]
    waiting_patients = [p for p in hospital.patients() if p.phase in ("waiting_triage", "triage", "waiting_er")]
    waits += [world.now - p.arrived_at for p in waiting_patients]
    census = sum(1 for bed in hospital.beds.values() if bed.state == "occupied")
    return Kpis(
        census=census,
        capacity=sum(1 for b in hospital.beds.values() if b.unit in BED_UNITS),
        er_wait_min=round(sum(waits) / len(waits), 1) if waits else 0.0,
        waiting=len(waiting_patients),
        alerts=sum(1 for p in hospital.patients() if p.risk is not None and p.risk.level == "high"),
    )


def scenario_infos(world: World) -> list[ScenarioInfo]:
    return [s.info(world) for s in world.scenarios.values() if s.active]


def hospital_snapshot(world: World, hospital_id: str, speed: int, paused: bool, frozen: bool) -> SnapshotMessage:
    hospital = world.hospitals[hospital_id]
    people = sorted(hospital.people.values(), key=lambda p: p.id)
    return SnapshotMessage(
        sim_time=world.time(),
        speed=speed,
        paused=paused,
        frozen=frozen,
        hospital=HospitalRef(id=hospital.id, name=hospital.name, status=hospital.status),
        entities=[entity_model(world, p) for p in people],
        beds=[BedInfo(id=b.id, patient_id=b.patient_id, state=b.state) for b in hospital.beds.values()],
        vehicles=[
            VehicleAtHospital(id=v.id, kind=v.kind, status=v.status, slot=hospital.slots_used.get(v.id))
            for v in world.vehicles.values()
            if v.at_hospital == hospital.id
        ],
        scenarios=[s for s in scenario_infos(world) if s.hospital_id in (None, hospital_id)],
        kpis=kpis(world, hospital),
    )


def network_message(world: World, speed: int, paused: bool, frozen: bool) -> NetworkMessage:
    hospitals = []
    for layout_h in world.layout.hospitals:
        state = world.hospitals[layout_h.id]
        hospitals.append(
            NetworkHospital(
                id=layout_h.id,
                name=layout_h.name,
                lat=layout_h.lat,
                lon=layout_h.lon,
                status=state.status,
                status_until=None if state.status_until is None else world.time(state.status_until),
                kpis=kpis(world, state),
            )
        )
    vehicles = []
    for v in world.vehicles.values():
        lat, lon = v.position(world.now)
        vehicles.append(
            NetworkVehicle(
                id=v.id,
                kind=v.kind,
                home=v.home,
                status=v.status,
                destination=v.destination,
                patient_id=v.patient.id if v.patient is not None else None,
                lat=lat,
                lon=lon,
                route=[RoutePoint(lat=a, lon=b, t=world.time(t)) for a, b, t in v.route],
            )
        )
    return NetworkMessage(
        sim_time=world.time(),
        speed=speed,
        paused=paused,
        frozen=frozen,
        hospitals=hospitals,
        vehicles=vehicles,
        scenarios=scenario_infos(world),
    )


def visitor_count(hospital: HospitalState) -> int:
    return sum(1 for p in hospital.people.values() if isinstance(p, Visitor))
