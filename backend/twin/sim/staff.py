"""Staff behaviour (PROMPT.md §5.5). Nurses and doctors work in their unit and walk to bedsides for tasks,
take breaks in the staff lounge and, for some, go to the prayer room at set times. Surgeons go to the OR when
an operation starts. EMTs belong to ambulances (see vehicles.py)."""

from datetime import timedelta

from twin.common.ws import DespawnEvent, EntityKind, SpawnEvent, StaffEvent
from twin.sim import config as c
from twin.sim.config import LOCAL_TZ
from twin.sim.entities import Patient, Place, Staff
from twin.sim.hospital import HospitalState
from twin.sim.snapshot import entity_model
from twin.sim.world import SimGen, World

ROLE_PREFIX: dict[str, str] = {"nurse": "N", "doctor": "D", "surgeon": "S", "emt": "E"}
PRAYER_WINDOW_MIN = 45.0
NEVER = 1e12


def new_staff(world: World, hospital: HospitalState, kind: EntityKind, unit: str, place: Place) -> Staff:
    staff_id = world.next_id(ROLE_PREFIX[kind])
    rng = world.rng("staff", staff_id)
    staff = Staff(
        id=staff_id,
        kind=kind,
        hospital_id=hospital.id,
        place=place,
        appearance=world.appearance(staff_id),
        unit=unit,
        home_hospital=hospital.id,
        prays=rng.random() < c.PRAYING_SHARE,
        last_break=world.now - rng.uniform(0, 60 * c.BREAK_EVERY_H),
    )
    world.staff[staff_id] = staff
    return staff


def enter(world: World, hospital: HospitalState, staff: Staff, reason: str) -> None:
    staff.hospital_id = hospital.id
    staff.on_duty = True
    hospital.people[staff.id] = staff
    world.emit(hospital.id, SpawnEvent(time=world.time(), entity=entity_model(world, staff)))
    world.emit(hospital.id, StaffEvent(time=world.time(), entity_id=staff.id, change="on_duty", reason=reason))
    world.env.process(staff_loop(world, hospital, staff))


def unit_spots(hospital: HospitalState, unit: str) -> list[str]:
    """Where a staffer of `unit` waits between tasks: unit work stations first, then free bedsides."""
    rooms = hospital.unit_rooms(unit)
    stations = hospital.spots_where(rooms=rooms, kinds=("station",))
    if unit == "TRIAGE":
        stations = [s for s in stations if s.startswith("TRIAGE")]
    bedsides = hospital.spots_where(rooms=rooms, kinds=("bedside",))
    return stations + bedsides


def idle_spots(hospital: HospitalState, staff: Staff) -> list[str]:
    if staff.kind == "surgeon":
        return hospital.seats_where("lounge") + hospital.seats_where("desk")
    lounge = hospital.seats_where("lounge") + hospital.spots_where(room="STAFF", kinds=("standing",))
    return unit_spots(hospital, staff.unit or "") + lounge + hospital.seats_where("desk")


def go(world: World, hospital: HospitalState, staff: Staff, spot_id: str) -> SimGen:
    """Walk to `spot_id` (claimed first) and give up the previous spot."""
    if staff.place.spot == spot_id:
        return
    if not hospital.claim(spot_id, staff.id):
        return
    old = staff.place
    hospital.release_place(old, staff.id)
    yield from world.walk(hospital, staff, hospital.place_of_spot(spot_id), start=old)


def go_home(world: World, hospital: HospitalState, staff: Staff) -> SimGen:
    """Return to a free work station (or lounge/desk for surgeons). A bedside is only a fallback, so
    staff do not stand at a bed after a task while a station is free."""
    current = staff.place.spot
    home = idle_spots(hospital, staff)
    spots = hospital.layout.spots_by_id

    def bedside(spot_id: str) -> bool:
        return spot_id in spots and spots[spot_id].kind == "bedside"

    if current is not None and current in home and not bedside(current):
        return
    target = hospital.first_free([s for s in home if s != current and not bedside(s)])
    if target is None and (current is None or current not in home):
        target = hospital.first_free([s for s in home if s != current])
    if target is not None:
        yield from go(world, hospital, staff, target)


def prayer_due(world: World, staff: Staff) -> tuple[int, int] | None:
    if not staff.prays:
        return None
    now_local = world.time().astimezone(LOCAL_TZ)
    for hour, minute in c.PRAYER_TIMES_LOCAL:
        start = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        key = (now_local.toordinal(), hour * 60 + minute)
        if start <= now_local < start + timedelta(minutes=PRAYER_WINDOW_MIN) and key not in staff.prayed:
            return key
    return None


def break_due(world: World, hospital: HospitalState, staff: Staff) -> bool:
    if world.now - staff.last_break < 60 * c.BREAK_EVERY_H or staff.kind == "surgeon":
        return False
    covering = [
        s for s in hospital.staff() if s.unit == staff.unit and s.kind == staff.kind and s.id != staff.id and s.task not in ("break", "prayer")
    ]
    return bool(covering)


def timed_stay(world: World, hospital: HospitalState, staff: Staff, spot: str, task: str, minutes: float) -> SimGen:
    yield from go(world, hospital, staff, spot)
    staff.task = task
    yield from world.wait_for(staff, minutes)
    staff.task = None


def staff_loop(world: World, hospital: HospitalState, staff: Staff) -> SimGen:
    rng = world.rng("staff-loop", staff.id)
    visit = 0
    while staff.on_duty:
        if staff.dispatch is not None:
            # Sent to a high-risk patient: go to the bedside and stay a few minutes.
            patient_id, staff.dispatch = staff.dispatch, None
            target = hospital.people.get(patient_id)
            bedside = bedside_of(hospital, target.place.bed) if isinstance(target, Patient) else None
            if bedside is not None:
                yield from timed_stay(world, hospital, staff, bedside, "responding", rng.uniform(*c.ALERT_RESPONSE_MIN))
            elif isinstance(target, Patient) and target.place.bed is not None and world.now < staff.dispatch_until:
                # Someone is already at the bedside: wait a little and try again.
                staff.dispatch = patient_id
                yield from world.wait_for(staff, 2.0)
            continue
        if staff.kind == "surgeon" and staff.assignment == "OR":
            spot = hospital.first_free(["OR-ws-1", "OR-ws-2", "OR-ws-3", "OR-ws-4"])
            if spot is not None:
                yield from go(world, hospital, staff, spot)
            staff.task = "surgery"
            yield from world.wait_for(staff, NEVER)
            staff.task = None
            continue
        yield from go_home(world, hospital, staff)
        if not staff.on_duty:
            break
        prayer = prayer_due(world, staff)
        spot = hospital.first_free(hospital.spots_where(room="PRAYER", kinds=("prayer",))) if prayer else None
        if prayer is not None and spot is not None:
            staff.prayed.add(prayer)
            yield from timed_stay(world, hospital, staff, spot, "prayer", c.PRAYER_MIN)
            continue
        lounge = hospital.first_free(hospital.seats_where("lounge") + hospital.spots_where(room="STAFF", kinds=("standing",)))
        if break_due(world, hospital, staff) and lounge is not None:
            staff.last_break = world.now
            yield from timed_stay(world, hospital, staff, lounge, "break", c.BREAK_MIN)
            continue
        if staff.kind == "surgeon":
            yield from world.wait_for(staff, 60.0)
            continue
        gap = c.DOCTOR_ROUND_GAP_MIN if staff.kind == "doctor" else c.NURSE_TASK_GAP_MIN
        done = yield from world.wait_for(staff, rng.uniform(*gap))
        if not done or not staff.on_duty or staff.unit == "TRIAGE":
            continue
        patients = sorted(hospital.bedded(staff.unit), key=lambda p: p.id)
        if not patients:
            continue
        if staff.kind == "doctor":
            for patient in patients:
                if staff.dispatch is not None:
                    break  # sent to a high-risk patient: the loop answers that first
                bedside = bedside_of(hospital, patient.place.bed)
                if bedside is not None and staff.on_duty:
                    yield from timed_stay(world, hospital, staff, bedside, "rounds", rng.uniform(*c.DOCTOR_VISIT_MIN))
        else:
            patient = patients[visit % len(patients)]
            visit += 1
            bedside = bedside_of(hospital, patient.place.bed)
            if bedside is not None:
                task = "vitals" if visit % 2 else "meds"
                yield from timed_stay(world, hospital, staff, bedside, task, rng.uniform(*c.NURSE_TASK_MIN))
    yield from go_off_duty(world, hospital, staff)


def bedside_of(hospital: HospitalState, bed_id: str | None) -> str | None:
    if bed_id is None:
        return None
    spot = hospital.layout.beds_by_id[bed_id].spot
    return spot if spot not in hospital.holders else None


def go_off_duty(world: World, hospital: HospitalState, staff: Staff) -> SimGen:
    old = staff.place
    hospital.release_place(old, staff.id)
    staff.task = None
    yield from world.walk(hospital, staff, world.curb(), start=old)
    del hospital.people[staff.id]
    staff.hospital_id = None
    world.emit(hospital.id, DespawnEvent(time=world.time(), entity_id=staff.id, reason="off_duty"))
    if staff.on_duty:
        # Called back while walking out (the shortage ended): come straight back in.
        staff.place = world.curb()
        enter(world, hospital, staff, "returned")


def send_off_duty(world: World, hospital: HospitalState, staff: Staff, reason: str) -> None:
    staff.on_duty = False
    world.emit(hospital.id, StaffEvent(time=world.time(), entity_id=staff.id, change="off_duty", reason=reason))
    world.kick(staff, "off_duty")


def call_surgeons(world: World, hospital: HospitalState, to_or: bool) -> None:
    for staff in sorted((s for s in hospital.staff() if s.kind == "surgeon"), key=lambda s: s.id):
        staff.assignment = "OR" if to_or else None
        world.kick(staff, "or")


def build_staff(world: World, hospital: HospitalState) -> None:
    """Create the hospital's staff at the start of the run, each already at a free work spot."""
    profile = c.PROFILES[hospital.id]
    plan: list[tuple[EntityKind, str]] = []
    for unit, count in profile.nurses.items():
        plan += [("nurse", unit)] * count
    for unit, count in profile.doctors.items():
        plan += [("doctor", unit)] * count
    plan += [("surgeon", "OR")] * profile.surgeons
    for kind, unit in plan:
        staff = new_staff(world, hospital, kind, unit, world.curb())
        spot = hospital.first_free(idle_spots(hospital, staff))
        if spot is None:
            raise RuntimeError(f"No free spot for {staff.id} in {hospital.id}")
        hospital.claim(spot, staff.id)
        staff.place = hospital.place_of_spot(spot)
        enter(world, hospital, staff, "shift start")


def call_in(world: World, hospital: HospitalState, unit: str, count: int, reason: str) -> list[str]:
    """Bring extra nurses into `unit`; they walk in from the street."""
    added = []
    for _ in range(count):
        staff = new_staff(world, hospital, "nurse", unit, world.curb())
        enter(world, hospital, staff, reason)
        added.append(staff.id)
    return added
