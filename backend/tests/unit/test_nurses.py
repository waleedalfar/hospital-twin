"""Nurse assignment and high-risk alerts (extra X1)."""

from datetime import timedelta

import pytest

from tests.sim_helpers import make_sim
from twin.common.ws import NurseAlertEvent, Risk
from twin.sim import nurses
from twin.sim.engine import Simulation
from twin.sim.entities import Patient, Staff
from twin.sim.hospital import HospitalState


def run(sim: Simulation, minutes: int) -> None:
    for _ in range(minutes):
        sim.tick()


def busy_sim(hours: int = 14) -> Simulation:
    sim = make_sim(9, 12)
    sim.run_until(sim.visible_start + timedelta(hours=hours))
    return sim


def test_every_patient_with_a_bed_has_an_on_duty_nurse_of_their_unit() -> None:
    sim = busy_sim()
    checked = 0
    for _ in range(6):
        run(sim, 90)
        for hospital in sim.world.hospitals.values():
            for p in hospital.bedded():
                unit = hospital.beds[p.place.bed or ""].unit
                available = nurses.nurses_of(hospital, unit)
                if available:
                    nurse = hospital.people.get(p.nurse_id or "")
                    assert isinstance(nurse, Staff) and nurse.kind == "nurse" and nurse.on_duty and nurse.unit == unit, (p.id, unit, p.nurse_id)
                    checked += 1
            for p in hospital.patients():
                if p.place.bed is None:
                    assert p.nurse_id is None  # nobody is assigned to a patient without a bed
    assert checked > 50


def test_patients_are_spread_across_the_nurses_of_a_unit() -> None:
    sim = busy_sim()
    for hospital in sim.world.hospitals.values():
        for unit in ("WARD", "ER"):
            mine = list(hospital.bedded(unit))
            available = nurses.nurses_of(hospital, unit)
            if len(available) >= 2 and len(mine) >= 2:
                counts = {n.id: sum(1 for p in mine if p.nurse_id == n.id) for n in available}
                assert max(counts.values()) - min(counts.values()) <= max(2, len(mine) // len(available) + 1), counts


def pick_patient(sim: Simulation) -> tuple[HospitalState, Patient]:
    for hospital in sim.world.hospitals.values():
        for p in hospital.bedded("WARD"):
            if p.nurse_id and hospital.beds[p.place.bed or ""].unit == "WARD":
                return hospital, p
    raise AssertionError("no bedded ward patient")


def make_high(patient: Patient) -> None:
    patient.risk = Risk(score=0.83, level="high", top_factors=[("SpO2 drop, 2h", 0.3), ("HR trend", 0.2), ("Age", 0.1)], model_version="t")


def test_an_alert_goes_to_the_patients_nurse_and_sends_them_to_the_bedside() -> None:
    sim = busy_sim()
    hospital, patient = pick_patient(sim)
    make_high(patient)
    nurse = hospital.people[patient.nurse_id or ""]
    alert = nurses.raise_alert(sim.world, hospital, patient)
    assert alert is not None and alert.nurse_id == nurse.id and alert.patient_id == patient.id and alert.status == "pending"
    assert alert.bed == patient.place.bed and alert.unit == "WARD" and len(alert.top_factors) == 3
    events = [i.event for i in sim.world.drain() if isinstance(i.event, NurseAlertEvent)]
    assert events and events[0].alert.id == alert.id and events[0].alert.nurse_id == nurse.id
    spot = hospital.layout.beds_by_id[patient.place.bed or ""].spot
    reached = False
    for _ in range(40):
        run(sim, 1)
        if nurse.task == "responding" and nurse.place.spot == spot:
            reached = True
            break
    assert reached, f"the nurse did not reach the bedside: task={nurse.task} place={nurse.place}"


def test_acknowledging_records_how_long_it_took_and_cannot_be_done_twice() -> None:
    sim = busy_sim()
    hospital, patient = pick_patient(sim)
    make_high(patient)
    alert = nurses.raise_alert(sim.world, hospital, patient)
    assert alert is not None
    run(sim, 7)
    done = nurses.respond(sim.world, alert.id, "acknowledge")
    assert done.status == "acknowledged" and done.seconds_to_ack == pytest.approx(7 * 60, abs=60)
    updates = [i.event for i in sim.world.drain() if isinstance(i.event, NurseAlertEvent) and i.event.alert.status == "acknowledged"]
    assert updates
    with pytest.raises(nurses.AlertError, match="already acknowledged") as again:
        nurses.respond(sim.world, alert.id, "escalate")
    assert again.value.status == 409
    with pytest.raises(nurses.AlertError, match="Unknown alert") as unknown:
        nurses.respond(sim.world, "NA-999", "acknowledge")
    assert unknown.value.status == 404


def test_escalating_sends_a_doctor_of_the_unit_as_well() -> None:
    sim = busy_sim()
    hospital, patient = pick_patient(sim)
    make_high(patient)
    alert = nurses.raise_alert(sim.world, hospital, patient)
    assert alert is not None
    doctors = sorted((s for s in hospital.staff() if s.kind == "doctor" and s.on_duty and s.unit == "WARD"), key=lambda s: s.id)
    assert doctors, "the test hospital has a ward doctor on duty"
    nurses.respond(sim.world, alert.id, "escalate")
    assert alert.status == "escalated" and doctors[0].dispatch == patient.id
    spot = hospital.layout.beds_by_id[patient.place.bed or ""].spot
    arrived = False
    for _ in range(60):
        run(sim, 1)
        if doctors[0].task == "responding" and doctors[0].place.spot == spot:
            arrived = True
            break
    assert arrived


def test_no_alert_without_a_bed_a_risk_score_or_a_nurse() -> None:
    sim = busy_sim()
    hospital, patient = pick_patient(sim)
    patient.risk = None
    assert nurses.raise_alert(sim.world, hospital, patient) is None
    make_high(patient)
    patient.nurse_id = None
    for n in nurses.nurses_of(hospital, "WARD"):
        n.on_duty = False
    assert nurses.raise_alert(sim.world, hospital, patient) is None
    waiting = next(p for p in hospital.patients() if p.place.bed is None)
    make_high(waiting)
    assert nurses.raise_alert(sim.world, hospital, waiting) is None


def test_a_nurse_who_goes_off_duty_hands_their_patients_to_another() -> None:
    sim = busy_sim()
    hospital, patient = pick_patient(sim)
    first = patient.nurse_id
    holder = hospital.people[first or ""]
    assert isinstance(holder, Staff)
    holder.on_duty = False
    run(sim, 2)
    unit_nurses = nurses.nurses_of(hospital, "WARD")
    if unit_nurses:
        assert patient.nurse_id != first and patient.nurse_id in {n.id for n in unit_nurses}
