"""What the models are allowed to see of the simulation.

`Observer` follows the events the simulation publishes (the same ones the browser gets) and the public parts
of each present patient: age, sex, comorbidities, ESI, unit, time of arrival. It never reads the hidden
physiology, so a model trained or run through it cannot use the latent severity (PROMPT.md §5.4, §7.2).
"""

from collections import deque
from dataclasses import dataclass, field

from twin.common.ws import AdmitEvent, ArrivalEvent, CriticalEvent, DespawnEvent, ErAdmitEvent, SimEvent, VitalsEvent
from twin.ml.features import Reading, Static, build_features
from twin.sim.entities import Patient
from twin.sim.hospital import HospitalState
from twin.sim.world import Emitted, World

MAX_READINGS = 40
UNIT_OF_PHASE = {
    "waiting_triage": "WAITING",
    "triage": "WAITING",
    "waiting_er": "WAITING",
    "surgery_wait": "OR",
    "surgery": "OR",
}


@dataclass
class Chart:
    """The vitals charted for one patient, newest last."""

    readings: deque[Reading] = field(default_factory=lambda: deque(maxlen=MAX_READINGS))
    encounter_id: int = 0
    unit_since: float = 0.0  # when the patient entered the unit they are in now


class Observer:
    def __init__(self, world: World) -> None:
        self._world = world
        self.charts: dict[str, Chart] = {}
        self.criticals: list[tuple[float, str, int]] = []
        self.arrivals: list[tuple[float, str, str]] = []  # (minute, hospital, mode)
        self.exits: dict[tuple[str, int], float] = {}  # (patient, encounter) -> minute they left the hospital

    def feed(self, emitted: list[Emitted]) -> None:
        """Take in one tick's events."""
        for item in emitted:
            self._on_event(item.hospital_id, item.event)

    def _minute(self, event: SimEvent) -> float:
        return self._world.minutes(event.time)

    def _on_event(self, hospital_id: str | None, event: SimEvent) -> None:
        if isinstance(event, ArrivalEvent):
            chart = self.charts.get(event.patient_id)
            if chart is None or chart.encounter_id != event.encounter_id:
                self.charts[event.patient_id] = Chart(encounter_id=event.encounter_id, unit_since=self._minute(event))
            self.arrivals.append((self._minute(event), hospital_id or "", event.mode))
        elif isinstance(event, AdmitEvent | ErAdmitEvent):
            admitted = self.charts.get(event.patient_id)
            if admitted is not None:
                admitted.unit_since = self._minute(event)
        elif isinstance(event, VitalsEvent):
            chart = self.charts.setdefault(event.patient_id, Chart())
            v = event.vitals
            chart.readings.append(Reading(self._minute(event), v.hr, v.spo2, v.sbp, v.dbp, v.temp, v.rr))
        elif isinstance(event, CriticalEvent):
            chart = self.charts.get(event.patient_id)
            self.criticals.append((self._minute(event), event.patient_id, chart.encounter_id if chart else 0))
        elif isinstance(event, DespawnEvent) and event.reason in ("discharged", "left"):
            chart = self.charts.pop(event.entity_id, None)
            if chart is not None:
                self.exits[(event.entity_id, chart.encounter_id)] = self._minute(event)

    def unit_of(self, hospital: HospitalState, p: Patient) -> str:
        if p.phase in UNIT_OF_PHASE:
            return UNIT_OF_PHASE[p.phase]
        if p.place.bed is not None:
            return hospital.beds[p.place.bed].unit
        return p.unit or "WAITING"

    def features_for(self, hospital: HospitalState, p: Patient, now: float) -> dict[str, float] | None:
        """Feature row for a present patient at sim minute `now`, or None if nothing is charted yet."""
        chart = self.charts.get(p.id)
        profile = p.profile
        if chart is None or profile is None or not chart.readings:
            return None
        admitted = p.admitted_at if p.admitted_at is not None else p.arrived_at
        static = Static(
            age=profile.age,
            male=profile.sex == "male",
            comorbidities=profile.comorbidity_count,
            unit=self.unit_of(hospital, p),
            hours_since_admission=max(0.0, (now - admitted) / 60.0),
            esi=p.esi,
        )
        return build_features(list(chart.readings), static, now)

    def scorable(self) -> list[tuple[HospitalState, Patient]]:
        """Every present patient who is waiting or admitted (not being discharged)."""
        out: list[tuple[HospitalState, Patient]] = []
        for hospital_id in sorted(self._world.hospitals):
            hospital = self._world.hospitals[hospital_id]
            for p in sorted(hospital.patients(), key=lambda x: x.id):
                if p.phase not in ("discharge", "gone"):
                    out.append((hospital, p))
        return out

    def hours_in_unit(self, patient_id: str, now: float) -> float:
        chart = self.charts.get(patient_id)
        return 0.0 if chart is None else max(0.0, (now - chart.unit_since) / 60.0)
