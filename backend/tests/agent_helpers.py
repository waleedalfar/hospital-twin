"""A hand-built summary for agent tests: Mercy's ER is full and busy, Desert Valley is quiet."""

from datetime import UTC, datetime
from pathlib import Path

from twin.agent.summary import (
    OtherHospital,
    PatientSummary,
    StaffSummary,
    Summary,
    UnitSummary,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gemini"
T0 = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def patient(pid: str, unit: str = "WARD", level: str = "low", score: float = 0.1, hours: float = 30.0) -> PatientSummary:
    return PatientSummary(
        id=pid,
        unit=unit,
        bed=f"{unit}-1",
        score=score,
        level=level,
        top_factors=[("Age", 0.4)],
        hours_in_hospital=hours,
    )


def busy_summary(**overrides: object) -> Summary:
    base: dict[str, object] = {
        "hospital_id": "mercy",
        "hospital_name": "Mercy General",
        "sim_time": T0,
        "status": "open",
        "census": 27,
        "capacity": 29,
        "er_wait_min": 77.2,
        "waiting": 10,
        "alerts": 2,
        "forecast_arrivals_6h": 9.4,
        "units": [
            UnitSummary(unit="ER", occupied=6, capacity=6, hours_until_full=0.0),
            UnitSummary(unit="WARD", occupied=13, capacity=14, hours_until_full=3.0),
            UnitSummary(unit="ICU", occupied=5, capacity=6, hours_until_full=None),
            UnitSummary(unit="REC", occupied=3, capacity=3, hours_until_full=0.0),
        ],
        "high_risk": [patient("P-0042", "ICU", "high", 0.81, 12.0)],
        "expedite_candidates": [patient("P-0100", hours=55.0), patient("P-0101", hours=41.5)],
        "open_beds": {"ER": [], "WARD": ["WARD-3"], "ICU": ["ICU-6"], "REC": []},
        "staffing": [
            StaffSummary(unit="ER", nurses=2, required=2),
            StaffSummary(unit="WARD", nurses=2, required=3),
            StaffSummary(unit="ICU", nurses=3, required=3),
            StaffSummary(unit="REC", nurses=1, required=2),
        ],
        "incoming_ambulances": 1,
        "other_hospitals": [
            OtherHospital(
                id="desert",
                name="Desert Valley",
                status="open",
                census=14,
                capacity=29,
                occupancy_pct=48.3,
                er_wait_min=5.0,
            ),
            OtherHospital(
                id="stlukes",
                name="St. Luke's",
                status="open",
                census=26,
                capacity=29,
                occupancy_pct=89.7,
                er_wait_min=30.0,
            ),
        ],
    }
    base.update(overrides)
    return Summary.model_validate(base)
