"""Runs the hidden physiology of every patient, emits their vitals and fires critical events (§5.4)."""

from twin.common.ws import CriticalEvent, VitalsEvent
from twin.sim import config as c
from twin.sim.entities import Patient
from twin.sim.hospital import HospitalState
from twin.sim.physiology import after_icu_transfer, after_rapid_response, is_critical, step, vitals
from twin.sim.world import SimGen, World

WAITING_PHASES = ("waiting_triage", "triage", "waiting_er")
TREATED_PHASES = ("er", "inpatient", "recovery", "surgery", "surgery_wait", "escalate", "relocate")


def monitor(world: World) -> SimGen:
    while True:
        from twin.sim.scenarios import flu_active

        for hospital_id in sorted(world.hospitals):
            hospital = world.hospitals[hospital_id]
            flu = flu_active(world, hospital_id)
            for patient in sorted(hospital.patients(), key=lambda p: p.id):
                update(world, hospital, patient, flu)
        yield world.env.timeout(c.PHYSIO_STEP_MIN)


def update(world: World, hospital: HospitalState, patient: Patient, flu: bool) -> None:
    phys, profile = patient.physiology, patient.profile
    if phys is None or profile is None or patient.phase == "discharge":
        return
    rng = world.rng("physiology", patient.id)
    in_icu = patient.unit == "ICU" and patient.place.bed is not None
    step(
        phys,
        profile,
        patient.esi,
        world.now,
        c.PHYSIO_STEP_MIN,
        rng,
        flu=flu,
        in_icu=in_icu,
        treated=patient.phase in TREATED_PHASES,
    )
    interval = c.VITALS_WAITING_MIN if patient.phase in WAITING_PHASES else c.VITALS_ADMITTED_MIN
    if world.now - phys.last_vitals_at >= interval - 1e-6:
        phys.last_vitals_at = world.now
        patient.vitals = vitals(phys, profile, rng)
        world.emit(hospital.id, VitalsEvent(time=world.time(), patient_id=patient.id, vitals=patient.vitals))
    if is_critical(phys, world.now):
        escalate(world, hospital, patient)


def escalate(world: World, hospital: HospitalState, patient: Patient) -> None:
    """Move the patient to a free ICU bed if there is one and they can be moved now; otherwise the rapid
    response team treats them where they are."""
    phys = patient.physiology
    if phys is None:
        raise ValueError(f"{patient.id} has no physiology")
    unit = patient.unit or "WAITING"
    if unit != "ICU":
        bed = hospital.pools["ICU"].try_take()
        if bed is not None:
            patient.reserved_bed = bed
            if world.kick(patient, "icu", bed):
                after_icu_transfer(phys, world.now)
                world.emit(
                    hospital.id,
                    CriticalEvent(
                        time=world.time(), patient_id=patient.id, unit=unit, response="icu_transfer"
                    ),
                )
                return
            patient.reserved_bed = None
            hospital.pools["ICU"].release(bed)
    after_rapid_response(phys, world.now)
    world.emit(
        hospital.id,
        CriticalEvent(time=world.time(), patient_id=patient.id, unit=unit, response="rapid_response"),
    )
