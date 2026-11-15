"""The compact structured summary the agent sees (PROMPT.md §9): occupancy and hours-until-full per unit, ER
wait, waiting count, forecasts, high-risk patients with top factors, staffing against ratios, incoming
ambulances, and the other hospitals' status. Built from the live simulation, never from the hidden physiology.
"""

import math
from datetime import datetime

from pydantic import BaseModel

from twin.ml.forecast import BED_UNITS, project_capacity
from twin.ml.inference import InferenceEngine
from twin.sim import config as c
from twin.sim.entities import Patient
from twin.sim.hospital import HospitalState
from twin.sim.snapshot import kpis
from twin.sim.world import World

STAFF_UNITS = ("ER", "WARD", "ICU", "REC")
MAX_HIGH_RISK = 8
MAX_CANDIDATES = 8


class UnitSummary(BaseModel):
    unit: str
    occupied: int
    capacity: int
    hours_until_full: float | None


class PatientSummary(BaseModel):
    id: str
    unit: str
    bed: str | None
    score: float
    level: str
    top_factors: list[tuple[str, float]]
    hours_in_hospital: float
    expected_discharge_h: float | None = None


class StaffSummary(BaseModel):
    unit: str
    nurses: int
    required: int


class OtherHospital(BaseModel):
    id: str
    name: str
    status: str
    census: int
    capacity: int
    occupancy_pct: float
    er_wait_min: float


class Summary(BaseModel):
    hospital_id: str
    hospital_name: str
    sim_time: datetime
    status: str
    census: int
    capacity: int
    er_wait_min: float
    waiting: int
    alerts: int
    forecast_arrivals_6h: float
    units: list[UnitSummary]
    high_risk: list[PatientSummary]
    expedite_candidates: list[PatientSummary]
    open_beds: dict[str, list[str]]
    staffing: list[StaffSummary]
    incoming_ambulances: int
    other_hospitals: list[OtherHospital]


def r1(x: float) -> float:
    return round(x, 1)


def flat_metrics(s: Summary) -> dict[str, float]:
    """Every number in the summary under a stable name. The grounding check compares cited values to these."""
    out: dict[str, float] = {
        "er_wait_min": r1(s.er_wait_min),
        "waiting": float(s.waiting),
        "census": float(s.census),
        "capacity": float(s.capacity),
        "alerts": float(s.alerts),
        "forecast_arrivals_6h": r1(s.forecast_arrivals_6h),
        "incoming_ambulances": float(s.incoming_ambulances),
        "high_risk_patients": float(len(s.high_risk)),
    }
    for u in s.units:
        out[f"{u.unit}.occupied"] = float(u.occupied)
        out[f"{u.unit}.capacity"] = float(u.capacity)
        if u.hours_until_full is not None:
            out[f"{u.unit}.hours_until_full"] = r1(u.hours_until_full)
    for st in s.staffing:
        out[f"staff.{st.unit}.nurses"] = float(st.nurses)
        out[f"staff.{st.unit}.required"] = float(st.required)
    for o in s.other_hospitals:
        out[f"other.{o.id}.occupancy_pct"] = r1(o.occupancy_pct)
        out[f"other.{o.id}.er_wait_min"] = r1(o.er_wait_min)
        out[f"other.{o.id}.census"] = float(o.census)
    for p in [*s.high_risk, *s.expedite_candidates]:
        out[f"patient.{p.id}.score"] = round(p.score, 2)
        out[f"patient.{p.id}.hours_in_hospital"] = r1(p.hours_in_hospital)
        if p.expected_discharge_h is not None:
            out[f"patient.{p.id}.expected_discharge_h"] = r1(p.expected_discharge_h)
    return out


def _patient(world: World, hospital: HospitalState, p: Patient) -> PatientSummary:
    risk = p.risk
    unit = hospital.beds[p.place.bed].unit if p.place.bed else (p.unit or "WAITING")
    return PatientSummary(
        id=p.id,
        unit=unit,
        bed=p.place.bed,
        score=risk.score if risk else 0.0,
        level=risk.level if risk else "low",
        top_factors=list(risk.top_factors) if risk else [],
        hours_in_hospital=max(0.0, (world.now - p.arrived_at) / 60.0),
        expected_discharge_h=p.expected_discharge_h,
    )


def build_summary(world: World, ml: InferenceEngine | None, hospital_id: str, forecast: list[float] | None = None) -> Summary:
    hospital = world.hospitals[hospital_id]
    k = kpis(world, hospital)
    layout = world.layout
    occupancy = {u: sum(1 for b in hospital.beds.values() if b.unit == u and b.state == "occupied") for u in BED_UNITS}
    until_full: dict[str, float | None] = dict.fromkeys(BED_UNITS)
    arrivals = forecast or []
    if ml is not None and ml.arrivals_model is not None:
        history, last = ml.hourly_arrivals(hospital_id, 24)
        from twin.sim.scenarios import flu_active

        arrivals = ml.arrivals_model.forecast(hospital_id, history, last, int(flu_active(world, hospital_id)))
        until_full = project_capacity(arrivals, occupancy, layout.capacity, ml.arrivals_model.unit_stats)
    patients = hospital.patients()
    scored = [p for p in patients if p.risk is not None]
    high = sorted(
        (p for p in scored if p.risk and p.risk.level == "high"),
        key=lambda p: -(p.risk.score if p.risk else 0),
    )
    candidates = sorted(
        (p for p in scored if p.phase == "inpatient" and p.unit in ("WARD", "REC") and p.risk and p.risk.level == "low"),
        # Closest to going home first, by the length-of-stay model; without predictions, longest in hospital first.
        key=lambda p: (p.expected_discharge_h if p.expected_discharge_h is not None else float("inf"), p.arrived_at),
    )
    nurses = {u: sum(1 for s in hospital.staff() if s.kind == "nurse" and s.unit == u and s.on_duty) for u in STAFF_UNITS}
    staffing = [
        StaffSummary(
            unit=u,
            nurses=nurses[u],
            required=math.ceil(occupancy[u] / c.NURSE_RATIO[u]) if u in c.NURSE_RATIO else 0,
        )
        for u in STAFF_UNITS
    ]
    others = []
    for oid in sorted(world.hospitals):
        if oid == hospital_id:
            continue
        other = world.hospitals[oid]
        ok = kpis(world, other)
        others.append(
            OtherHospital(
                id=oid,
                name=other.name,
                status=other.status,
                census=ok.census,
                capacity=ok.capacity,
                occupancy_pct=100.0 * ok.census / max(1, ok.capacity),
                er_wait_min=ok.er_wait_min,
            )
        )
    open_beds = {u: [b.id for b in hospital.beds.values() if b.unit == u and b.state == "open"][:3] for u in BED_UNITS}
    incoming = sum(1 for v in world.vehicles.values() if v.status == "to_hospital" and v.destination == hospital_id)
    return Summary(
        hospital_id=hospital_id,
        hospital_name=hospital.name,
        sim_time=world.time(),
        status=hospital.status,
        census=k.census,
        capacity=k.capacity,
        er_wait_min=k.er_wait_min,
        waiting=k.waiting,
        alerts=k.alerts,
        forecast_arrivals_6h=float(sum(arrivals)),
        units=[UnitSummary(unit=u, occupied=occupancy[u], capacity=layout.capacity[u], hours_until_full=until_full[u]) for u in BED_UNITS],
        high_risk=[_patient(world, hospital, p) for p in high[:MAX_HIGH_RISK]],
        expedite_candidates=[_patient(world, hospital, p) for p in candidates[:MAX_CANDIDATES]],
        open_beds=open_beds,
        staffing=staffing,
        incoming_ambulances=incoming,
        other_hospitals=others,
    )
