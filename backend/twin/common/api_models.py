"""REST request and response models (PROMPT.md §6.2)."""

import re
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from twin.common.ws import ArrivalMode, HospitalStatus, Kpis, Location, RiskLevel, ScenarioName, Vitals

WINDOW_PATTERN = re.compile(r"^(\d{1,4})([mhd])$")
MAX_WINDOW = timedelta(days=30)


class Api(BaseModel):
    model_config = ConfigDict(extra="forbid")


def parse_window(text: str) -> timedelta:
    """'90m', '6h' or '2d' -> timedelta. Raises ValueError for anything else."""
    match = WINDOW_PATTERN.match(text)
    if match is None:
        raise ValueError(f"window must look like 30m, 6h or 2d, not {text!r}")
    amount, unit = int(match[1]), match[2]
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
    if not timedelta(0) < delta <= MAX_WINDOW:
        raise ValueError("window must be more than 0 and at most 30d")
    return delta


class HospitalSummary(Api):
    id: str
    name: str
    lat: float
    lon: float
    status: HospitalStatus
    kpis: Kpis


class Encounter(Api):
    id: int
    hospital_id: str
    arrived_at: datetime
    mode: ArrivalMode
    esi: int
    disposition: str | None
    ended_at: datetime | None


class VitalsReading(Vitals):
    time: datetime


class RiskReading(Api):
    time: datetime
    score: float
    level: RiskLevel
    model_version: str
    top_factors: list[tuple[str, float]]


class PatientDetail(Api):
    id: str
    fhir_id: str = Field(description="FHIR reference of the Synthea record, e.g. Patient/<uuid>")
    age: int
    sex: str
    conditions: list[str]
    comorbidity_count: int
    hospital_id: str | None
    location: Location | None
    encounter: Encounter | None
    vitals: VitalsReading | None
    risk: RiskReading | None


class VitalsPoint(Api):
    time: datetime
    hr: float
    spo2: float
    sbp: float
    dbp: float
    temp: float
    rr: float
    samples: int


class VitalsSeries(Api):
    patient_id: str
    window: str
    points: list[VitalsPoint]


class RiskSeries(Api):
    patient_id: str
    window: str
    points: list[RiskReading]


class UnitOccupancy(Api):
    unit: str
    bucket: datetime
    occupied_avg: float
    beds: int


class ErWait(Api):
    bucket: datetime
    avg_wait_min: float
    p90_wait_min: float
    patients: int


class KpiReport(Api):
    hospital_id: str
    as_of: datetime
    occupancy: list[UnitOccupancy]
    er_wait: ErWait | None
    arrivals_last_hour: dict[str, int]
    alerts_last_hour: dict[str, int]


class ArrivalForecast(Api):
    hours_ahead: int
    expected: float


class ForecastReport(Api):
    hospital_id: str
    as_of: datetime | None
    model_version: str | None
    arrivals: list[ArrivalForecast]
    hours_until_full: dict[str, float | None] = Field(
        description="Hours until each unit is full; null if not within 24 h"
    )


class ModelsResponse(Api):
    active_deterioration: str | None
    active_arrivals: str | None
    error: str | None
    models: list[dict[str, Any]]


class SimState(Api):
    sim_time: datetime
    speed: int
    paused: bool
    frozen: bool
    ready: bool


class SpeedRequest(Api):
    speed: int


class PauseRequest(Api):
    paused: bool


class FreezeRequest(Api):
    frozen: bool


class ScenarioRequest(Api):
    name: ScenarioName
    hospital_id: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class ErrorBody(Api):
    detail: str
