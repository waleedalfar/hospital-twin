"""Patient flow (PROMPT.md §5.3): arrive -> waiting seat -> triage -> ER bay -> disposition (discharge, ward,
ICU, surgery -> recovery -> ward, or transfer). When the needed bed is full the patient waits where they
are (boarding)."""

import math
from typing import Any

from twin.common.ws import (
    AdmitEvent,
    ArrivalEvent,
    ArrivalMode,
    BedEvent,
    Complaint,
    DespawnEvent,
    DespawnReason,
    DischargeEvent,
    ErAdmitEvent,
    SpawnEvent,
    SurgeryEvent,
    TriageEvent,
)
from twin.sim import config as c
from twin.sim.entities import MovePlan, Patient, PatientProfile, Place
from twin.sim.hospital import HospitalState
from twin.sim.physiology import initial_physiology
from twin.sim.snapshot import entity_model
from twin.sim.world import SimGen, World


def lognormal(rng: Any, median: float, sigma: float = c.LOS_SIGMA) -> float:
    return float(median * math.exp(sigma * rng.gauss(0.0, 1.0)))


def poisson(rng: Any, lam: float) -> int:
    """Knuth's method; fine for the small per-minute rates used here."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def draw_profile(world: World, rng: Any) -> PatientProfile | None:
    pool = world.pool
    for _ in range(50):
        profile: PatientProfile = pool.profiles[rng.randrange(len(pool.profiles))]
        if profile.id not in pool.present:
            return profile
    free = [p for p in pool.profiles if p.id not in pool.present]
    return free[rng.randrange(len(free))] if free else None


def draw_esi(rng: Any, mode: ArrivalMode, age: int) -> int:
    esi = int(rng.choices((1, 2, 3, 4, 5), weights=c.ESI_WEIGHTS[mode])[0])
    if age >= 75 and esi > 1 and rng.random() < 0.3:
        esi -= 1
    return esi


def draw_complaint(rng: Any, respiratory_share: float | None = None) -> Complaint:
    if respiratory_share is not None and rng.random() < respiratory_share:
        return "respiratory"
    complaint: Complaint = rng.choices(c.COMPLAINTS, weights=c.COMPLAINT_WEIGHTS)[0]
    return complaint


def create_patient(
    world: World,
    hospital: HospitalState,
    profile: PatientProfile,
    mode: ArrivalMode,
    esi: int,
    complaint: Complaint,
    place: Place,
    existing: Patient | None = None,
) -> Patient:
    """Register an arrival at `hospital`. A transferred patient keeps their entity and hidden state."""
    rng = world.rng("patient", profile.id)
    patient = existing or Patient(
        id=profile.id,
        kind="patient",
        hospital_id=hospital.id,
        place=place,
        appearance=world.appearance(profile.id),
    )
    patient.hospital_id = hospital.id
    patient.place = place
    patient.profile = profile
    patient.mode = mode
    patient.esi = esi
    patient.complaint = complaint
    patient.encounter_id = world.next_number("encounter")
    patient.arrived_at = world.now
    patient.admitted_at = None
    patient.phase = "waiting_er" if mode != "walk_in" else "waiting_triage"
    patient.los_end = None
    patient.disposition = None
    patient.er_bed_at = None
    patient.expedited = False
    patient.unit = None
    patient.reserved_bed = None
    patient.move = None
    if patient.physiology is None:
        patient.physiology = initial_physiology(profile, esi, complaint == "respiratory", rng)
    world.pool.present.add(profile.id)
    hospital.people[patient.id] = patient
    hospital.counters.arrived += 1
    world.emit(hospital.id, SpawnEvent(time=world.time(), entity=entity_model(world, patient)))
    world.emit(
        hospital.id,
        ArrivalEvent(
            time=world.time(),
            patient_id=patient.id,
            mode=mode,
            esi=esi,
            complaint=complaint,
            encounter_id=patient.encounter_id,
        ),
    )
    return patient


def waiting_place(world: World, hospital: HospitalState, person_id: str) -> Place:
    """A free waiting-room seat, else a standing spot in the waiting room, else the line outside the door."""
    seat = hospital.first_free(hospital.seats_where("waiting"))
    if seat is None:
        seat = hospital.first_free(hospital.spots_where(room="WAITING", kinds=("standing",)))
    if seat is None:
        return world.curb()
    hospital.claim(seat, person_id)
    return hospital.place_of_spot(seat)


# ---- beds -------------------------------------------------------------------------------------------------


def set_bed(world: World, hospital: HospitalState, bed_id: str, patient_id: str | None, state: str) -> None:
    bed = hospital.beds[bed_id]
    bed.patient_id = patient_id
    bed.state = state  # type: ignore[assignment]
    world.emit(hospital.id, BedEvent(time=world.time(), bed_id=bed_id, patient_id=patient_id, state=bed.state))


def clean_bed(world: World, hospital: HospitalState, bed_id: str) -> SimGen:
    yield world.env.timeout(world.rng("cleaning", hospital.id).uniform(*c.CLEANING_MIN))
    set_bed(world, hospital, bed_id, None, "open")
    hospital.pools[hospital.beds[bed_id].unit].release(bed_id)


def vacate(world: World, hospital: HospitalState, patient: Patient, place: Place) -> None:
    """Free the bed, seat or spot `patient` held at `place`. A bed goes to cleaning first."""
    if place.bed is not None:
        set_bed(world, hospital, place.bed, None, "cleaning")
        world.env.process(clean_bed(world, hospital, place.bed))
    elif place.spot is not None:
        pool = hospital.pool_for_spot(place.spot)
        if pool is not None:
            pool.release(place.spot)
        else:
            hospital.release_place(place, patient.id)


def take_bed(world: World, hospital: HospitalState, patient: Patient, bed_id: str, plan: MovePlan | None = None) -> SimGen:
    """Walk `patient` from where they are to `bed_id` (already granted) and free their old place. `plan` is
    given when the route was planned already (an EMT walks the same route beside the patient)."""
    old = patient.place
    set_bed(world, hospital, bed_id, patient.id, "occupied")
    dest = hospital.place_of_bed(bed_id)
    vacate(world, hospital, patient, old)
    if plan is None:
        yield from world.walk(hospital, patient, dest, start=old)
    else:
        yield from world.follow(hospital, patient, old, dest, plan)


def admit(world: World, hospital: HospitalState, patient: Patient, bed_id: str, los_median_h: float) -> SimGen:
    yield from take_bed(world, hospital, patient, bed_id)
    unit = hospital.beds[bed_id].unit
    patient.unit = unit
    patient.phase = "inpatient"
    patient.admitted_at = patient.admitted_at if patient.admitted_at is not None else world.now
    rng = world.rng("los", patient.id)
    factor = (1 + 0.05 * (patient.profile.comorbidity_count if patient.profile else 0)) * (
        1.2 if patient.profile is not None and patient.profile.age > 70 else 1.0
    )
    factor *= c.LOS_ESI_FACTOR[patient.esi] * c.LOS_COMPLAINT_FACTOR[patient.complaint]
    patient.los_end = world.now + 60.0 * lognormal(rng, los_median_h) * factor
    world.emit(hospital.id, AdmitEvent(time=world.time(), patient_id=patient.id, unit=unit, bed_id=bed_id))
    from twin.sim.visitors import maybe_visit

    maybe_visit(world, hospital, patient)


def wait_for_slot(world: World, hospital: HospitalState, patient: Patient, pool_name: str, priority: float) -> SimGen:
    """Queue for a slot of `pool_name`. Returns the slot id, or None if the patient was kicked first."""
    pool = hospital.pools[pool_name]
    request = pool.request(priority)
    granted = yield from world.wait(patient, request)
    if not granted:
        pool.cancel(request)
        return None
    return str(request.value)


def priority(patient: Patient) -> float:
    return patient.esi * 1e6 + patient.arrived_at


# ---- phases -----------------------------------------------------------------------------------------------


def waiting_triage(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    seat = yield from wait_for_slot(world, hospital, p, "TRIAGE", p.arrived_at)
    if seat is None:
        return
    old = p.place
    p.phase = "triage"
    vacate(world, hospital, p, old)
    yield from world.walk(hospital, p, hospital.place_of_spot(seat), start=old)
    yield world.env.timeout(world.rng("triage", hospital.id).uniform(*c.TRIAGE_MIN))
    world.emit(hospital.id, TriageEvent(time=world.time(), patient_id=p.id, esi=p.esi))
    back = waiting_place(world, hospital, p.id)
    hospital.pools["TRIAGE"].release(seat)
    p.phase = "waiting_er"
    yield from world.walk(hospital, p, back, start=hospital.place_of_spot(seat))


def waiting_er(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    bed = yield from wait_for_slot(world, hospital, p, "ER", priority(p))
    if bed is None:
        return
    yield from start_er(world, hospital, p, bed)


def start_er(world: World, hospital: HospitalState, p: Patient, bed: str, plan: MovePlan | None = None) -> SimGen:
    wait = world.now - p.arrived_at
    hospital.er_waits.append((world.now, wait))
    p.phase = "er"
    p.unit = "ER"
    p.er_bed_at = world.now
    world.emit(hospital.id, ErAdmitEvent(time=world.time(), patient_id=p.id, bed_id=bed, wait_min=round(wait, 1)))
    yield from take_bed(world, hospital, p, bed, plan)


def choose_disposition(world: World, p: Patient) -> str:
    rng = world.rng("disposition", p.id)
    disposition = str(rng.choices(c.DISPOSITIONS, weights=c.DISPOSITION_WEIGHTS[p.esi])[0])
    age = p.profile.age if p.profile else 0
    if disposition == "discharge" and age >= 65 and p.esi <= 3 and rng.random() < c.OLDER_ADMIT_SHIFT:
        disposition = "admit_ward"
    return disposition


def er(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    if p.disposition is None:
        rng = world.rng("treatment", p.id)
        done = yield from world.wait_for(p, lognormal(rng, c.ER_TREATMENT_MEDIAN_MIN[p.esi], 0.35))
        if not done:
            return
        p.disposition = choose_disposition(world, p)
    target = {"admit_ward": "WARD", "admit_icu": "ICU"}.get(p.disposition)
    if p.disposition == "discharge":
        p.phase = "discharge"
    elif p.disposition == "surgery":
        p.phase = "surgery_wait"
    elif p.disposition == "transfer":
        p.phase = "transfer"
    elif target is not None:
        bed = yield from wait_for_slot(world, hospital, p, target, priority(p))
        if bed is None:
            return
        yield from admit(world, hospital, p, bed, c.ICU_LOS_MEDIAN_H if target == "ICU" else c.WARD_LOS_MEDIAN_H)


def surgery_wait(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    table = yield from wait_for_slot(world, hospital, p, "OR", priority(p))
    if table is None:
        return
    old = p.place
    p.phase = "surgery"
    p.unit = "OR"
    vacate(world, hospital, p, old)
    yield from world.walk(hospital, p, hospital.place_of_spot(table), start=old)
    from twin.sim.staff import call_surgeons

    call_surgeons(world, hospital, True)
    world.emit(hospital.id, SurgeryEvent(time=world.time(), patient_id=p.id, phase="start"))


def surgery(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    yield world.env.timeout(world.rng("surgery", p.id).uniform(*c.SURGERY_MIN))
    world.emit(hospital.id, SurgeryEvent(time=world.time(), patient_id=p.id, phase="end"))
    from twin.sim.staff import call_surgeons

    call_surgeons(world, hospital, False)
    bed = yield from wait_for_slot(world, hospital, p, "REC", priority(p))
    if bed is None:
        return
    yield from take_bed(world, hospital, p, bed)
    p.unit = "REC"
    p.phase = "recovery"
    world.emit(hospital.id, AdmitEvent(time=world.time(), patient_id=p.id, unit="REC", bed_id=bed))


def recovery(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    if p.los_end is None:
        p.los_end = world.now + world.rng("recovery", p.id).uniform(*c.RECOVERY_MIN)
    done = yield from world.wait_for(p, p.los_end - world.now)
    if not done:
        return
    bed = yield from wait_for_slot(world, hospital, p, "WARD", priority(p))
    if bed is None:
        return
    yield from admit(world, hospital, p, bed, c.WARD_LOS_MEDIAN_H)


def inpatient(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    if p.los_end is None or p.physiology is None:
        raise ValueError(f"Inpatient {p.id} has no discharge time or physiology")
    done = yield from world.wait_for(p, p.los_end - world.now)
    if not done:
        return
    if p.physiology.s > c.DISCHARGE_MAX_SEVERITY:
        p.los_end = world.now + 60.0 * c.DISCHARGE_RECHECK_H
        return
    if p.unit == "ICU":
        bed = yield from wait_for_slot(world, hospital, p, "WARD", priority(p))
        if bed is None:
            return
        yield from admit(world, hospital, p, bed, c.STEP_DOWN_LOS_MEDIAN_H)
        return
    p.phase = "discharge"


def discharge(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    old = p.place
    vacate(world, hospital, p, old)
    yield from world.walk(hospital, p, world.curb(), start=old)
    leave(world, hospital, p, "discharged")
    hospital.counters.discharged += 1
    los_h = (world.now - p.arrived_at) / 60.0
    world.emit(
        hospital.id,
        DischargeEvent(time=world.time(), patient_id=p.id, los_h=round(los_h, 2), expedited=p.expedited),
    )
    p.phase = "gone"


def leave(world: World, hospital: HospitalState, p: Patient, reason: DespawnReason) -> None:
    del hospital.people[p.id]
    p.hospital_id = None
    if reason != "boarded_vehicle":
        world.pool.present.discard(p.id)
    world.emit(hospital.id, DespawnEvent(time=world.time(), entity_id=p.id, reason=reason))


def relocate(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    """Move to the bed reserved by an ICU escalation or a move-patient action."""
    bed = p.reserved_bed
    if bed is None:
        raise ValueError(f"{p.id} has no reserved bed to move to")
    p.reserved_bed = None
    unit = hospital.beds[bed].unit
    if unit == "ER":
        yield from start_er(world, hospital, p, bed)
        return
    median = {"ICU": c.ICU_LOS_MEDIAN_H, "REC": c.RECOVERY_MIN[1] / 60.0}.get(unit, c.WARD_LOS_MEDIAN_H)
    keep_los = p.los_end if p.phase == "inpatient" and unit != "ICU" else None
    yield from admit(world, hospital, p, bed, median)
    if keep_los is not None:
        p.los_end = keep_los


def transfer(world: World, hospital: HospitalState, p: Patient) -> SimGen:
    from twin.sim.vehicles import transfer_out

    yield from transfer_out(world, hospital, p)


PHASES = {
    "waiting_triage": waiting_triage,
    "triage": waiting_triage,
    "waiting_er": waiting_er,
    "er": er,
    "surgery_wait": surgery_wait,
    "surgery": surgery,
    "recovery": recovery,
    "inpatient": inpatient,
    "escalate": relocate,
    "discharge": discharge,
    "transfer": transfer,
}


def journey(world: World, p: Patient) -> SimGen:
    """Run the patient's care until they leave. Kicks (ICU escalation, actions) redirect the next phase."""
    while p.phase != "gone" and p.hospital_id is not None:
        hospital = world.hospitals[p.hospital_id]
        yield from PHASES[p.phase](world, hospital, p)
        if p.kick_cause is not None:
            cause, _ = p.kick_cause
            p.kick_cause = None
            if cause in ("icu", "move"):
                p.phase = "escalate"
            elif cause == "discharge":
                p.expedited = True
                p.phase = "discharge"
