"""Features for the deterioration model (PROMPT.md §7.2).

Everything here is computed from what a clinician could see at time t: the vitals charted so far, the
patient's record and where they are. The latent severity and any future information never enter. A test
(`tests/unit/test_ml_features.py`) builds features at time t from histories with extra future readings added
and checks that the result does not change.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

VITAL_KEYS = ("hr", "spo2", "sbp", "dbp", "temp", "rr")
UNITS = ("ER", "WARD", "ICU", "REC", "WAITING", "OR")
COMPLAINT_CODES = {"respiratory": 0, "cardiac": 1, "trauma": 2, "gi": 3, "neuro": 4, "infection": 5, "other": 6}
HISTORY_MIN = 120.0  # features look back at most two hours

# (feature name, readable name shown in the UI and the model card)
FEATURES: tuple[tuple[str, str], ...] = (
    ("hr", "Heart rate"),
    ("spo2", "SpO2"),
    ("sbp", "Systolic BP"),
    ("dbp", "Diastolic BP"),
    ("temp", "Temperature"),
    ("rr", "Resp. rate"),
    ("hr_d1h", "HR change, 1h"),
    ("spo2_d1h", "SpO2 change, 1h"),
    ("sbp_d1h", "BP change, 1h"),
    ("rr_d1h", "Resp. rate change, 1h"),
    ("temp_d1h", "Temp. change, 1h"),
    ("hr_d2h", "HR change, 2h"),
    ("spo2_d2h", "SpO2 change, 2h"),
    ("sbp_d2h", "BP change, 2h"),
    ("rr_d2h", "Resp. rate change, 2h"),
    ("temp_d2h", "Temp. change, 2h"),
    ("spo2_min_2h", "Lowest SpO2, 2h"),
    ("spo2_max_2h", "Highest SpO2, 2h"),
    ("hr_min_2h", "Lowest HR, 2h"),
    ("hr_max_2h", "Highest HR, 2h"),
    ("rr_min_2h", "Lowest resp. rate, 2h"),
    ("rr_max_2h", "Highest resp. rate, 2h"),
    ("news2", "NEWS2 score"),
    ("age", "Age"),
    ("sex_male", "Male sex"),
    ("comorbidities", "Comorbidities"),
    ("unit", "Care unit"),
    ("hours_since_admission", "Hours in hospital"),
    ("esi", "Triage level (ESI)"),
)
FEATURE_NAMES: tuple[str, ...] = tuple(name for name, _ in FEATURES)
READABLE: dict[str, str] = dict(FEATURES)
NAN = float("nan")


@dataclass(frozen=True)
class Reading:
    """One charted set of vital signs at sim minute `t`."""

    t: float
    hr: float
    spo2: float
    sbp: float
    dbp: float
    temp: float
    rr: float

    def value(self, key: str) -> float:
        return float(getattr(self, key))


@dataclass(frozen=True)
class Static:
    """What is known about the patient and where they are at time t."""

    age: int
    male: bool
    comorbidities: int
    unit: str
    hours_since_admission: float
    esi: int


def news2(r: Reading) -> int:
    """NEWS2 aggregate score (Royal College of Physicians), assuming alert and no supplemental oxygen."""
    score = 0
    rr = r.rr
    score += 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3
    s = r.spo2
    score += 3 if s <= 91 else 2 if s <= 93 else 1 if s <= 95 else 0
    b = r.sbp
    score += 3 if b <= 90 else 2 if b <= 100 else 1 if b <= 110 else 0 if b <= 219 else 3
    h = r.hr
    score += 3 if h <= 40 else 1 if h <= 50 else 0 if h <= 90 else 1 if h <= 110 else 2 if h <= 130 else 3
    t = r.temp
    score += 3 if t <= 35.0 else 1 if t <= 36.0 else 0 if t <= 38.0 else 1 if t <= 39.0 else 2
    return score


def _at_or_before(history: Sequence[Reading], t: float) -> Reading | None:
    """The latest reading at or before `t`."""
    best: Reading | None = None
    for r in history:
        if r.t <= t:
            best = r
        else:
            break
    return best


def build_features(history: Sequence[Reading], static: Static, now: float) -> dict[str, float] | None:
    """Features at sim minute `now` from readings sorted by time. Readings after `now` are ignored.
    Returns None if nothing has been charted yet."""
    visible = [r for r in history if r.t <= now]
    latest = visible[-1] if visible else None
    if latest is None:
        return None
    window = [r for r in visible if r.t >= now - HISTORY_MIN]
    out: dict[str, float] = {key: latest.value(key) for key in VITAL_KEYS}
    for hours, tag in ((1.0, "1h"), (2.0, "2h")):
        past = _at_or_before(visible, now - 60.0 * hours)
        for key in ("hr", "spo2", "sbp", "rr", "temp"):
            out[f"{key}_d{tag}"] = latest.value(key) - past.value(key) if past is not None else NAN
    for key, tag in (("spo2", "spo2"), ("hr", "hr"), ("rr", "rr")):
        values = [r.value(key) for r in window]
        out[f"{tag}_min_2h"] = min(values)
        out[f"{tag}_max_2h"] = max(values)
    out["news2"] = float(news2(latest))
    out["age"] = float(static.age)
    out["sex_male"] = 1.0 if static.male else 0.0
    out["comorbidities"] = float(static.comorbidities)
    out["unit"] = float(UNITS.index(static.unit)) if static.unit in UNITS else float(len(UNITS))
    out["hours_since_admission"] = static.hours_since_admission
    out["esi"] = float(static.esi)
    return {name: out.get(name, NAN) for name in FEATURE_NAMES}


def is_finite(x: float) -> bool:
    return not math.isnan(x)
