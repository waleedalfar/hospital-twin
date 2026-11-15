"""Nurse assignment and high-risk alerts (extra X1).

Every patient who has a bed is assigned an on-duty nurse of that unit (the one with the fewest patients). When the
risk model puts a patient into the high level, an alert is addressed to their nurse, who is sent to the bedside. The
nurse (or a person using the UI) acknowledges it or escalates it to a doctor; the time it took is recorded.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from twin.common.ws import NurseAlertEvent, NurseAlertModel, NurseAlertStatus
from twin.sim.entities import Patient, Staff
from twin.sim.hospital import HospitalState
from twin.sim.world import World

DISPATCH_PATIENCE_MIN = 40.0  # a responder waits this long for the bedside to be free (someone else may be there)


class AlertError(Exception):
    """An alert cannot be answered (unknown, or already answered)."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class NurseAlert:
    id: str
    hospital_id: str
    patient_id: str
    nurse_id: str
    unit: str
    bed: str | None
    score: float
    top_factors: list[tuple[str, float]]
    created: datetime
    status: NurseAlertStatus = "pending"
    responded: datetime | None = None
    seconds_to_ack: float | None = None
    reason: Literal["high_risk", "paged"] = "high_risk"
    history: list[str] = field(default_factory=list)

    def model(self) -> NurseAlertModel:
        return NurseAlertModel(
            id=self.id,
            hospital_id=self.hospital_id,
            patient_id=self.patient_id,
            nurse_id=self.nurse_id,
            unit=self.unit,
            bed=self.bed,
            score=self.score,
            top_factors=self.top_factors,
            status=self.status,
            created=self.created,
            responded=self.responded,
            seconds_to_ack=self.seconds_to_ack,
            reason=self.reason,
        )


def unit_of(hospital: HospitalState, patient: Patient) -> str | None:
    return hospital.beds[patient.place.bed].unit if patient.place.bed is not None else None


def nurses_of(hospital: HospitalState, unit: str) -> list[Staff]:
    return sorted((s for s in hospital.staff() if s.kind == "nurse" and s.on_duty and s.unit == unit), key=lambda s: s.id)


def assign_nurses(world: World) -> None:
    """Give every bedded patient an on-duty nurse of their unit; keep an assignment while it is still valid."""
    for hospital in world.hospitals.values():
        load: dict[str, int] = {}
        pending: list[tuple[Patient, str]] = []
        for patient in sorted(hospital.bedded(), key=lambda p: p.id):
            unit = unit_of(hospital, patient)
            if unit is None:
                continue
            nurse_ids = {n.id for n in nurses_of(hospital, unit)}
            if patient.nurse_id in nurse_ids and patient.nurse_id is not None:
                load[patient.nurse_id] = load.get(patient.nurse_id, 0) + 1
            else:
                patient.nurse_id = None
                pending.append((patient, unit))
        for patient, unit in pending:
            candidates = nurses_of(hospital, unit)
            if candidates:
                chosen = min(candidates, key=lambda n: (load.get(n.id, 0), n.id))
                patient.nurse_id = chosen.id
                load[chosen.id] = load.get(chosen.id, 0) + 1
    for hospital in world.hospitals.values():
        for patient in hospital.patients():
            if patient.place.bed is None:
                patient.nurse_id = None


def send_to_patient(world: World, hospital: HospitalState, staff: Staff, patient_id: str) -> None:
    """Ask `staff` to go to the patient's bedside as soon as they are free."""
    staff.dispatch = patient_id
    staff.dispatch_until = world.now + DISPATCH_PATIENCE_MIN
    world.kick(staff, "alert", patient_id)


def raise_alert(world: World, hospital: HospitalState, patient: Patient, reason: Literal["high_risk", "paged"] = "high_risk") -> NurseAlert | None:
    """Address a high-risk alert to the patient's nurse and send them over. None if no nurse is on duty in the unit."""
    unit = unit_of(hospital, patient)
    if unit is None or patient.risk is None:
        return None
    if patient.nurse_id is None:
        assign_nurses(world)
    nurse = hospital.people.get(patient.nurse_id) if patient.nurse_id else None
    if not isinstance(nurse, Staff):
        return None
    world.alert_counter += 1
    alert = NurseAlert(
        id=f"NA-{world.alert_counter}",
        hospital_id=hospital.id,
        patient_id=patient.id,
        nurse_id=nurse.id,
        unit=unit,
        bed=patient.place.bed,
        score=patient.risk.score,
        top_factors=list(patient.risk.top_factors),
        created=world.time(),
        reason=reason,
    )
    world.nurse_alerts[alert.id] = alert
    send_to_patient(world, hospital, nurse, patient.id)
    world.emit(hospital.id, NurseAlertEvent(time=world.time(), alert=alert.model()))
    return alert


def respond(world: World, alert_id: str, action: str) -> NurseAlert:
    """Acknowledge an alert, or escalate it (a doctor of the unit is sent too). Records the time taken."""
    alert: NurseAlert | None = world.nurse_alerts.get(alert_id)
    if alert is None:
        raise AlertError(f"Unknown alert {alert_id}", 404)
    if alert.status != "pending":
        raise AlertError(f"{alert_id} is already {alert.status}", 409)
    hospital = world.hospitals[alert.hospital_id]
    now = world.time()
    alert.status = "acknowledged" if action == "acknowledge" else "escalated"
    alert.responded = now
    alert.seconds_to_ack = (now - alert.created).total_seconds()
    if alert.status == "escalated":
        doctors = sorted((s for s in hospital.staff() if s.kind == "doctor" and s.on_duty and s.unit == alert.unit), key=lambda s: s.id)
        if doctors:
            send_to_patient(world, hospital, doctors[0], alert.patient_id)
    world.emit(hospital.id, NurseAlertEvent(time=now, alert=alert.model()))
    return alert
