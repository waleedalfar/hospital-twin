"""Simulation parameters (PROMPT.md §5). Every number the simulation uses that is not in the layout lives
here, so it can be read and tuned in one place."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from twin.common.ws import Complaint

LOCAL_TZ = ZoneInfo("America/Phoenix")
# §5.1: sim time starts at 2026-11-14 08:00 local (Phoenix, no daylight saving) = 15:00 UTC.
SIM_START = datetime(2026, 11, 14, 8, 0, tzinfo=LOCAL_TZ).astimezone(UTC)
SPEEDS = (1, 4, 8)
TICK_MIN = 1.0

WALK_SPEED_M_PER_MIN = 1.3 * 60  # §5.5: 1.3 m/s
ELEVATOR_S_PER_FLOOR = 6.0
ELEVATOR_DOOR_S = 8.0

# Relative arrival rate by local hour of day (mean 1.0 after normalising).
_HOURLY_RAW = (
    0.45, 0.38, 0.33, 0.30, 0.32, 0.42, 0.62, 0.85, 1.10, 1.30, 1.42, 1.45,
    1.42, 1.38, 1.35, 1.32, 1.30, 1.30, 1.28, 1.20, 1.08, 0.92, 0.75, 0.58,
)  # fmt: skip
HOURLY_PATTERN = tuple(v * 24 / sum(_HOURLY_RAW) for v in _HOURLY_RAW)


@dataclass(frozen=True)
class HospitalProfile:
    """Demand and staffing for one hospital (§5.2: different staffing and demand, Mercy busiest)."""

    walk_in_per_h: float
    ambulance_per_h: float
    nurses: dict[str, int]
    doctors: dict[str, int] = field(default_factory=lambda: {"ER": 1, "WARD": 1, "ICU": 1})
    surgeons: int = 2
    ambulances: int = 4


PROFILES: dict[str, HospitalProfile] = {
    "mercy": HospitalProfile(1.05, 0.40, {"ER": 2, "TRIAGE": 1, "WARD": 3, "ICU": 3, "REC": 2}),
    "stlukes": HospitalProfile(0.75, 0.30, {"ER": 2, "TRIAGE": 1, "WARD": 2, "ICU": 2, "REC": 1}),
    "desert": HospitalProfile(0.60, 0.25, {"ER": 2, "TRIAGE": 1, "WARD": 2, "ICU": 2, "REC": 1}),
}
EMTS_PER_AMBULANCE = 2
# §5.5 nurse ratios: one nurse per this many patients.
NURSE_RATIO = {"ICU": 2, "WARD": 5, "ER": 3, "REC": 2}

COMPLAINTS: tuple[Complaint, ...] = ("respiratory", "cardiac", "trauma", "gi", "neuro", "infection", "other")
COMPLAINT_WEIGHTS = (0.18, 0.14, 0.16, 0.16, 0.08, 0.10, 0.18)

# ESI 1..5 probabilities by arrival mode.
ESI_WEIGHTS = {
    "walk_in": (0.01, 0.10, 0.40, 0.35, 0.14),
    "ambulance": (0.05, 0.30, 0.45, 0.15, 0.05),
    "air": (0.60, 0.40, 0.0, 0.0, 0.0),
}

# Disposition probabilities by ESI: discharge, ward, icu, surgery, transfer.
DISPOSITIONS = ("discharge", "admit_ward", "admit_icu", "surgery", "transfer")
DISPOSITION_WEIGHTS = {
    1: (0.05, 0.25, 0.45, 0.20, 0.05),
    2: (0.35, 0.35, 0.12, 0.13, 0.05),
    3: (0.70, 0.20, 0.03, 0.05, 0.02),
    4: (0.93, 0.05, 0.00, 0.02, 0.00),
    5: (0.99, 0.01, 0.00, 0.00, 0.00),
}
OLDER_ADMIT_SHIFT = 0.30  # age >= 65, ESI <= 3: this share of discharges become ward admissions

TRIAGE_MIN = (5.0, 10.0)
ER_TREATMENT_MEDIAN_MIN = {1: 150.0, 2: 180.0, 3: 150.0, 4: 90.0, 5: 60.0}
WARD_LOS_MEDIAN_H = 20.0
ICU_LOS_MEDIAN_H = 24.0
STEP_DOWN_LOS_MEDIAN_H = 16.0
LOS_SIGMA = 0.3
# Stays run longer for sicker triage levels and for some chief complaints (multipliers on the median stay).
LOS_ESI_FACTOR = {1: 1.3, 2: 1.1, 3: 0.9, 4: 0.7, 5: 0.55}
LOS_COMPLAINT_FACTOR = {"respiratory": 0.95, "cardiac": 1.15, "trauma": 1.25, "gi": 0.7, "neuro": 1.15, "infection": 0.9, "other": 0.75}
SURGERY_MIN = (60.0, 180.0)
RECOVERY_MIN = (90.0, 180.0)
CLEANING_MIN = (30.0, 45.0)
DISCHARGE_MAX_SEVERITY = 1.6
DISCHARGE_RECHECK_H = 4.0

# Physiology (§5.4). Latent severity s >= 0; a critical event fires at CRITICAL_THRESHOLD.
CRITICAL_THRESHOLD = 3.0
PHYSIO_STEP_MIN = 5.0
VITALS_ADMITTED_MIN = 5.0
VITALS_WAITING_MIN = 15.0
BASE_MU_BY_ESI = {1: 1.6, 2: 1.1, 3: 0.6, 4: 0.3, 5: 0.15}
THETA_PER_H = 0.12
THETA_ICU_PER_H = 0.35
SIGMA_PER_SQRT_H = 0.15
RECOVERY_RATE_PER_H = 0.02
MU_FLOOR = 0.2
ICU_TARGET_MU = 0.8
EPISODE_BASE_PER_H = 0.0025
EPISODE_ESI_FACTOR = {1: 3.0, 2: 2.0, 3: 1.2, 4: 0.7, 5: 0.5}
EPISODE_FLU_RESPIRATORY_FACTOR = 3.0
FLU_SPO2_SHIFT = 5.0  # points of SpO2 lost by respiratory patients while a flu surge lasts
FLU_RR_SHIFT = 8.0  # breaths per minute gained by respiratory patients while a flu surge lasts
EPISODE_DRIFT_PER_H = (0.25, 0.6)
EPISODE_DURATION_H = (4.0, 10.0)
RAPID_RESPONSE_RELIEF = 1.2
CRITICAL_COOLDOWN_H = 6.0

# Staff behaviour (§5.5).
NURSE_TASK_GAP_MIN = (20.0, 45.0)
NURSE_TASK_MIN = (5.0, 10.0)
DOCTOR_ROUND_GAP_MIN = (90.0, 150.0)
DOCTOR_VISIT_MIN = (3.0, 5.0)
BREAK_EVERY_H = 4.0
BREAK_MIN = 30.0
PRAYER_TIMES_LOCAL = ((5, 30), (12, 30), (15, 45), (17, 30), (19, 0))
PRAYER_MIN = 10.0
PRAYING_SHARE = 0.25
HEADSCARF_SHARE = 0.2

# Visitors (§5.3).
VISITOR_SHARE = 0.35
VISITOR_DELAY_MIN = (10.0, 60.0)
VISITOR_STAY_MIN = (60.0, 180.0)

# City and vehicles (§5.2). Speeds along roads, in km per minute.
AMBULANCE_KM_PER_MIN = 0.75
HELICOPTER_KM_PER_MIN = 3.3
HELICOPTER_MIN_FLIGHT_MIN = 3.0  # take-off and landing, so short hops are still a visible flight
SCENE_MIN = (8.0, 15.0)
TURNAROUND_MIN = 10.0
CALL_RADIUS_DEG = 0.06

# Scenarios (§5.6).
FLU_MULTIPLIER = 2.5
FLU_DURATION_MIN = 180.0
FLU_RESPIRATORY_SHARE = 0.8
MASS_CASUALTY_COUNT = 12
MASS_CASUALTY_WINDOW_MIN = 20.0
SHORTAGE_SHARE = 0.30
SHORTAGE_DURATION_MIN = 240.0

DEFAULT_WARMUP = timedelta(days=3)
