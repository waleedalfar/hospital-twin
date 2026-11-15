"""Ambulances and the helicopter on the city map (PROMPT.md §5.2, §5.6, §5.7).

Ambulances answer calls in their hospital's area, carry the patient to that hospital unless it is diverting
or offline (then to the nearest open one), and carry transfers between hospitals. Routes follow the street
grid: east-west first, then north-south. The helicopter flies straight lines from Mercy's roof.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import simpy

from twin.common.ws import (
    AmbulanceEvent,
    ArrivalMode,
    HospitalStatus,
    HospitalStatusEvent,
    TransferEvent,
    VehicleKind,
    VehicleStatus,
)
from twin.sim import config as c
from twin.sim.entities import MovePlan, Patient, PatientProfile, Place, Staff
from twin.sim.hospital import HospitalState
from twin.sim.pathing import timeline
from twin.sim.pools import SlotPool
from twin.sim.world import SimGen, World

KM_PER_DEG_LAT = 111.0
KM_PER_DEG_LON = 111.0 * math.cos(math.radians(33.45))
HANDOFF_MIN = 1.0


@dataclass
class Vehicle:
    id: str
    kind: VehicleKind
    home: str
    lat: float
    lon: float
    status: VehicleStatus = "at_base"
    route: list[tuple[float, float, float]] = field(default_factory=list)
    destination: str | None = None
    patient: Patient | None = None
    crew: list[Staff] = field(default_factory=list)
    at_hospital: str | None = None
    kick: simpy.Event | None = None
    kick_cause: tuple[str, str] | None = None

    def position(self, now: float) -> tuple[float, float]:
        if not self.route or now >= self.route[-1][2]:
            return (self.route[-1][0], self.route[-1][1]) if self.route else (self.lat, self.lon)
        if now <= self.route[0][2]:
            return self.route[0][0], self.route[0][1]
        for (a_lat, a_lon, a_t), (b_lat, b_lon, b_t) in zip(self.route, self.route[1:], strict=False):
            if a_t <= now <= b_t:
                f = 0.0 if b_t == a_t else (now - a_t) / (b_t - a_t)
                return a_lat + (b_lat - a_lat) * f, a_lon + (b_lon - a_lon) * f
        return self.route[-1][0], self.route[-1][1]


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * KM_PER_DEG_LAT, (a[1] - b[1]) * KM_PER_DEG_LON)


def plan_route(
    kind: VehicleKind, start: tuple[float, float], end: tuple[float, float], t0: float
) -> list[tuple[float, float, float]]:
    if kind == "helicopter":
        flight = max(c.HELICOPTER_MIN_FLIGHT_MIN, km(start, end) / c.HELICOPTER_KM_PER_MIN)
        return [(start[0], start[1], t0), (end[0], end[1], t0 + flight)]
    corner = (start[0], end[1])
    t1 = t0 + km(start, corner) / c.AMBULANCE_KM_PER_MIN
    t2 = t1 + km(corner, end) / c.AMBULANCE_KM_PER_MIN
    return [(start[0], start[1], t0), (corner[0], corner[1], t1), (end[0], end[1], t2)]


def hospital_point(world: World, hospital_id: str) -> tuple[float, float]:
    h = next(h for h in world.layout.hospitals if h.id == hospital_id)
    return h.lat, h.lon


def road_lines(world: World) -> tuple[list[float], list[float]]:
    """The city's streets: one east-west street through each hospital's latitude and one north-south street
    through each hospital's longitude. Ambulances drive east-west first, then north-south, so a trip between
    two street crossings stays on streets."""
    hospitals = world.layout.hospitals
    return sorted({h.lat for h in hospitals}), sorted({h.lon for h in hospitals})


def snap_to_roads(world: World, lat: float, lon: float) -> tuple[float, float]:
    """The street crossing nearest to a point."""
    lats, lons = road_lines(world)
    return min(lats, key=lambda v: abs(v - lat)), min(lons, key=lambda v: abs(v - lon))


def scene_crossings(world: World) -> list[tuple[float, float]]:
    """Street crossings that are not a hospital: where emergencies happen."""
    lats, lons = road_lines(world)
    hospital_points = {(h.lat, h.lon) for h in world.layout.hospitals}
    return [(la, lo) for la in lats for lo in lons if (la, lo) not in hospital_points]


def set_status(world: World, vehicle: Vehicle, status: VehicleStatus) -> None:
    vehicle.status = status
    if vehicle.at_hospital is not None:
        hospital = world.hospitals[vehicle.at_hospital]
        world.emit(
            hospital.id,
            AmbulanceEvent(
                time=world.time(),
                vehicle_id=vehicle.id,
                vehicle_kind=vehicle.kind,
                status=status,
                slot=hospital.slots_used.get(vehicle.id),
                destination=vehicle.destination,
                patient_id=vehicle.patient.id if vehicle.patient else None,
            ),
        )


def drive(world: World, vehicle: Vehicle, end: tuple[float, float], status: VehicleStatus) -> SimGen:
    """Drive to `end`. Returns False if the vehicle was redirected on the way."""
    leave_grounds(world, vehicle)
    start = vehicle.position(world.now)
    vehicle.route = plan_route(vehicle.kind, start, end, world.now)
    vehicle.status = status
    done = yield from world.wait(vehicle, world.env.timeout(vehicle.route[-1][2] - world.now))
    vehicle.lat, vehicle.lon = vehicle.position(world.now)
    return bool(done)


def leave_grounds(world: World, vehicle: Vehicle) -> None:
    if vehicle.at_hospital is None:
        return
    hospital = world.hospitals[vehicle.at_hospital]
    set_status(world, vehicle, "to_scene" if vehicle.patient is None else "transferring")
    hospital.slots_used.pop(vehicle.id, None)
    vehicle.at_hospital = None


def park(world: World, vehicle: Vehicle, hospital: HospitalState, status: VehicleStatus) -> None:
    vehicle.at_hospital = hospital.id
    vehicle.route = []
    vehicle.lat, vehicle.lon = hospital_point(world, hospital.id)
    if vehicle.kind == "ambulance":
        used = set(hospital.slots_used.values())
        slot = next((s.id for s in world.layout.outside.ambulance_slots if s.id not in used), None)
        if slot is not None:
            hospital.slots_used[vehicle.id] = slot
    set_status(world, vehicle, status)


def is_open(world: World, hospital_id: str) -> bool:
    return world.hospitals[hospital_id].status == "open"


def destination_for(world: World, home: str, here: tuple[float, float], forced: str | None = None) -> str:
    """The call's own hospital (or a forced one) if open, else the nearest open hospital, else home."""
    for preferred in (forced, home):
        if preferred is not None and is_open(world, preferred):
            return preferred
    open_ids = [h.id for h in world.layout.hospitals if is_open(world, h.id)]
    if not open_ids:
        return home
    return min(open_ids, key=lambda h: (km(here, hospital_point(world, h)), h))


def drive_to_hospital(world: World, vehicle: Vehicle, home: str, forced: str | None = None) -> SimGen:
    """Drive the patient to a hospital, re-routing if the destination stops taking ambulances."""
    while True:
        here = vehicle.position(world.now)
        vehicle.destination = destination_for(world, home, here, forced)
        arrived = yield from drive(world, vehicle, hospital_point(world, vehicle.destination), "to_hospital")
        if arrived:
            return world.hospitals[vehicle.destination]
        forced = None


def build_vehicles(world: World) -> None:
    from twin.sim.staff import new_staff

    for layout_h in world.layout.hospitals:
        hospital = world.hospitals[layout_h.id]
        ids = []
        for n in range(1, c.PROFILES[hospital.id].ambulances + 1):
            vehicle = Vehicle(
                id=f"AMB-{hospital.id}-{n}",
                kind="ambulance",
                home=hospital.id,
                lat=layout_h.lat,
                lon=layout_h.lon,
            )
            for _ in range(c.EMTS_PER_AMBULANCE):
                emt = new_staff(
                    world, hospital, "emt", "ER", Place(floor=0, room="OUTSIDE", vehicle=vehicle.id)
                )
                emt.hospital_id = None
                emt.vehicle_id = vehicle.id
                vehicle.crew.append(emt)
            world.vehicles[vehicle.id] = vehicle
            park(world, vehicle, hospital, "at_base")
            ids.append(vehicle.id)
        hospital.pools["AMB"] = SlotPool(world.env, ids)
        if layout_h.helipad:
            heli = Vehicle(
                id=f"HELI-{hospital.id}",
                kind="helicopter",
                home=hospital.id,
                lat=layout_h.lat,
                lon=layout_h.lon,
            )
            heli.at_hospital = hospital.id
            world.vehicles[heli.id] = heli


def get_ambulance(world: World, home: str, scene: tuple[float, float], priority: float) -> SimGen:
    """The home hospital's free ambulance, else the nearest free one elsewhere, else wait for home's."""
    hospital = world.hospitals[home]
    taken = hospital.pools["AMB"].try_take() if hospital.pools["AMB"].queue_length == 0 else None
    if taken is None:
        others = sorted(
            (h for h in world.hospitals if h != home), key=lambda h: (km(scene, hospital_point(world, h)), h)
        )
        for other in others:
            taken = world.hospitals[other].pools["AMB"].try_take()
            if taken is not None:
                break
    if taken is None:
        taken = yield hospital.pools["AMB"].request(priority)
    return world.vehicles[str(taken)]


def release_ambulance(world: World, vehicle: Vehicle) -> None:
    world.hospitals[vehicle.home].pools["AMB"].release(vehicle.id)


def make_patient(
    world: World, rng: Any, vehicle: Vehicle, mode: ArrivalMode, complaint: str | None, esi: int | None
) -> tuple[Patient, PatientProfile] | None:
    from twin.sim.patients import draw_complaint, draw_esi, draw_profile

    profile = draw_profile(world, rng)
    if profile is None:
        return None
    world.pool.present.add(profile.id)
    patient = Patient(
        id=profile.id,
        kind="patient",
        hospital_id=None,
        place=Place(floor=None, room=None, vehicle=vehicle.id),
        appearance=world.appearance(profile.id),
        profile=profile,
        mode=mode,
        esi=esi if esi is not None else draw_esi(rng, mode, profile.age),
        complaint=complaint if complaint is not None else draw_complaint(rng),  # type: ignore[arg-type]
    )
    return patient, profile


def run_call(
    world: World,
    home: str,
    scene: tuple[float, float],
    *,
    complaint: str | None = None,
    forced: str | None = None,
    esi: int | None = None,
) -> SimGen:
    """One emergency call: drive to the scene, pick the patient up, deliver, return to base."""
    rng = world.rng("call", home)
    vehicle = yield from get_ambulance(world, home, scene, world.now)
    yield from drive(world, vehicle, scene, "to_scene")
    vehicle.status = "on_scene"
    yield world.env.timeout(rng.uniform(*c.SCENE_MIN))
    made = make_patient(world, rng, vehicle, "ambulance", complaint, esi)
    if made is not None:
        vehicle.patient = made[0]
        hospital = yield from drive_to_hospital(world, vehicle, home, forced)
        yield from deliver(world, vehicle, hospital, "ambulance")
    yield from return_home(world, vehicle)


def return_home(world: World, vehicle: Vehicle) -> SimGen:
    yield world.env.timeout(c.TURNAROUND_MIN)
    vehicle.destination = vehicle.home
    yield from drive(world, vehicle, hospital_point(world, vehicle.home), "returning")
    park(world, vehicle, world.hospitals[vehicle.home], "at_base")
    vehicle.destination = None
    if vehicle.kind == "ambulance":
        release_ambulance(world, vehicle)


def deliver(world: World, vehicle: Vehicle, hospital: HospitalState, mode: ArrivalMode) -> SimGen:
    """Hand the patient over at `hospital`: an EMT wheels them to a free ER bay or the waiting room."""
    from twin.sim.patients import create_patient, journey, start_er, waiting_place

    patient = vehicle.patient
    if patient is None or patient.profile is None:
        raise ValueError(f"{vehicle.id} has no patient to deliver")
    park(world, vehicle, hospital, "unloading")
    vehicle.patient = None
    vehicle.destination = None
    arrival = (
        Place(floor=0, room="OUTSIDE", vehicle=vehicle.id)
        if vehicle.kind == "ambulance"
        else hospital.place_of_spot(world.layout.roof.helipad_spot)
    )
    patient = create_patient(
        world, hospital, patient.profile, mode, patient.esi, patient.complaint, arrival, existing=patient
    )
    want_icu = vehicle.kind == "helicopter" and patient.esi == 1
    bed = hospital.pools["ICU"].try_take() if want_icu else None
    if bed is None:
        bed = hospital.pools["ER"].try_take() if hospital.pools["ER"].queue_length == 0 else None
    dest = hospital.place_of_bed(bed) if bed is not None else waiting_place(world, hospital, patient.id)
    path = world.router.path(world.node_of(hospital, arrival), world.node_of(hospital, dest))
    nodes, times = timeline(world.router, path, world.now, hospital.elevator)
    plan = MovePlan(nodes, times)
    if vehicle.kind == "ambulance" and vehicle.crew:
        world.env.process(escort(world, hospital, vehicle, plan))
    if bed is not None and hospital.beds[bed].unit == "ER":
        world.env.process(chain(start_er(world, hospital, patient, bed, plan=plan), journey(world, patient)))
    elif bed is not None:
        patient.reserved_bed = bed
        patient.phase = "escalate"
        world.env.process(journey(world, patient))
    else:
        world.env.process(
            chain(world.follow(hospital, patient, arrival, dest, plan), journey(world, patient))
        )
    yield world.env.timeout(0)


def chain(*steps: SimGen) -> SimGen:
    for step in steps:
        yield from step


def escort(world: World, hospital: HospitalState, vehicle: Vehicle, plan: MovePlan) -> SimGen:
    """The EMT walks beside the patient, hands over, and walks back to the ambulance."""
    from twin.common.ws import DespawnEvent, SpawnEvent
    from twin.sim.snapshot import entity_model

    emt = vehicle.crew[0]
    home_place = Place(floor=0, room="OUTSIDE", vehicle=vehicle.id)
    emt.place = home_place
    emt.hospital_id = hospital.id
    hospital.people[emt.id] = emt
    world.emit(hospital.id, SpawnEvent(time=world.time(), entity=entity_model(world, emt)))
    back_nodes, back_times = timeline(
        world.router, list(reversed(plan.path)), plan.arrive + HANDOFF_MIN, hospital.elevator
    )
    round_trip = MovePlan([*plan.path, *back_nodes], [*plan.times, *back_times])
    emt.task = "handover"
    yield from world.follow(hospital, emt, home_place, home_place, round_trip)
    emt.task = None
    del hospital.people[emt.id]
    emt.hospital_id = None
    world.emit(hospital.id, DespawnEvent(time=world.time(), entity_id=emt.id, reason="boarded_vehicle"))


def transfer_out(world: World, hospital: HospitalState, patient: Patient) -> SimGen:
    """Move a patient to another hospital by ambulance (§5.3 disposition 'transfer')."""
    from twin.sim.patients import leave, vacate

    request = hospital.pools["AMB"].request(-1.0)
    got = yield from world.wait(patient, request)
    if not got:
        hospital.pools["AMB"].cancel(request)
        return
    vehicle = world.vehicles[str(request.value)]
    set_status(world, vehicle, "unloading")
    old = patient.place
    vacate(world, hospital, patient, old)
    yield from world.walk(hospital, patient, Place(floor=0, room="OUTSIDE", vehicle=vehicle.id), start=old)
    here = hospital_point(world, hospital.id)
    others = sorted(
        (h.id for h in world.layout.hospitals if h.id != hospital.id),
        key=lambda h: (km(here, hospital_point(world, h)), h),
    )
    target = next((h for h in others if is_open(world, h)), others[0])
    leave(world, hospital, patient, "boarded_vehicle")
    hospital.counters.transferred_out += 1
    world.emit(
        hospital.id,
        TransferEvent(time=world.time(), patient_id=patient.id, to_hospital=target, vehicle_id=vehicle.id),
    )
    patient.phase = "gone"
    vehicle.patient = patient
    patient.place = Place(floor=None, room=None, vehicle=vehicle.id)
    world.env.process(carry_transfer(world, vehicle, target))


def carry_transfer(world: World, vehicle: Vehicle, target: str) -> SimGen:
    dest = yield from drive_to_hospital(world, vehicle, target, None)
    yield from deliver(world, vehicle, dest, "ambulance")
    yield from return_home(world, vehicle)


def set_hospital_status(
    world: World, hospital: HospitalState, status: HospitalStatus, until: float | None, reason: str
) -> None:
    hospital.status = status
    hospital.status_until = until
    world.emit(
        hospital.id,
        HospitalStatusEvent(
            time=world.time(),
            status=status,
            until=None if until is None else world.time(until),
            reason=reason,
        ),
    )
    if status != "open":
        for vehicle in world.vehicles.values():
            if vehicle.status == "to_hospital" and vehicle.destination == hospital.id:
                world.kick(vehicle, "reroute")
    if until is not None:
        world.env.process(reopen_later(world, hospital, until))


def reopen_later(world: World, hospital: HospitalState, until: float) -> SimGen:
    yield world.env.timeout(max(0.0, until - world.now))
    if hospital.status_until == until:
        set_hospital_status(world, hospital, "open", None, "diversion ended")


def calls(world: World, hospital_id: str) -> SimGen:
    """Emergency calls in the hospital's area: a non-homogeneous Poisson process by hour of day."""
    from twin.sim.patients import poisson
    from twin.sim.scenarios import demand_multiplier

    rng = world.rng("calls", hospital_id)
    while True:
        rate = c.PROFILES[hospital_id].ambulance_per_h * c.HOURLY_PATTERN[world.local_hour()]
        rate *= demand_multiplier(world, hospital_id)
        for _ in range(poisson(rng, rate / 60.0)):
            crossings = scene_crossings(world)
            scene = crossings[rng.randrange(len(crossings))]
            world.env.process(run_call(world, hospital_id, scene))
        yield world.env.timeout(c.TICK_MIN)


def helicopter_run(world: World, scene: tuple[float, float]) -> SimGen:
    heli = next((v for v in world.vehicles.values() if v.kind == "helicopter"), None)
    if heli is None or heli.status != "at_base":
        return
    hospital = world.hospitals[heli.home]
    set_status(world, heli, "to_scene")
    heli.at_hospital = None
    yield from drive(world, heli, scene, "to_scene")
    heli.status = "on_scene"
    rng = world.rng("helicopter")
    yield world.env.timeout(rng.uniform(*c.SCENE_MIN))
    made = make_patient(world, rng, heli, "air", "trauma", None)
    if made is not None:
        heli.patient = made[0]
        heli.destination = hospital.id
        yield from drive(world, heli, hospital_point(world, hospital.id), "to_hospital")
        yield from deliver(world, heli, hospital, "air")
    set_status(world, heli, "at_base")
