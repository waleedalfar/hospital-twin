"""Builds the training data by running the simulation headless (PROMPT.md §7.1).

The run uses a fixed seed and no sleeping: 30 sim days, three hospitals. Every 30 sim minutes, each patient
who is waiting or admitted becomes one row: the features a clinician could see at that moment, and the label
"a critical event within the next 6 sim hours". A few flu surges are included so the arrivals forecast has
an active-scenario signal; they cover about 1% of the time.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from twin.common.ws import BedEvent
from twin.ml.features import FEATURE_NAMES
from twin.ml.observe import Observer
from twin.sim.engine import Simulation
from twin.sim.entities import PatientProfile
from twin.sim.layout_model import Layout, load_layout
from twin.sim.pathing import stream

logger = logging.getLogger(__name__)

SNAPSHOT_EVERY_MIN = 30
HORIZON_MIN = 6 * 60
DEFAULT_DAYS = 30
FLU_SURGES = 3
BED_UNITS = ("ER", "WARD", "ICU", "REC")
META = ("minute", "hospital", "patient_id", "encounter_id", "label")


@dataclass
class Dataset:
    """Training rows plus the aggregates the forecasts need."""

    rows: pd.DataFrame
    arrivals: pd.DataFrame
    unit_stats: dict[str, dict[str, float]]
    days: int
    seed: int
    surges: list[tuple[str, float, float]] = field(default_factory=list)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.rows.to_parquet(directory / "train.parquet", index=False)
        self.arrivals.to_parquet(directory / "arrivals.parquet", index=False)


def _label(rows: pd.DataFrame, criticals: list[tuple[float, str, int]]) -> np.ndarray:
    """1 if the patient has a critical event in (t, t + 6 h]."""
    by_patient: dict[str, list[float]] = {}
    for minute, patient_id, _ in criticals:
        by_patient.setdefault(patient_id, []).append(minute)
    out = np.zeros(len(rows), dtype=np.int8)
    for i, (minute, patient_id) in enumerate(zip(rows["minute"], rows["patient_id"], strict=True)):
        times = by_patient.get(str(patient_id))
        if times and any(minute < t <= minute + HORIZON_MIN for t in times):
            out[i] = 1
    return out


def build_dataset(
    profiles: list[PatientProfile],
    seed: int,
    days: int = DEFAULT_DAYS,
    *,
    layout: Layout | None = None,
    warmup_days: int = 1,
    surges: int = FLU_SURGES,
) -> Dataset:
    """Run the simulation for `days` sim days and collect the rows."""
    layout = layout or load_layout()
    sim = Simulation(layout, profiles, seed, timedelta(days=warmup_days))
    world = sim.world
    observer = Observer(world)
    hospital_ids = sorted(world.hospitals)
    rng = stream(seed, "training-surges")
    start = warmup_days * 1440
    total = days * 1440
    # Flu surges are spread over the run, never in the first or last two days.
    schedule = sorted(
        (start + int(rng.uniform(2, days - 2) * 1440), hospital_ids[i % len(hospital_ids)])
        for i in range(surges)
    )
    surge_spans: list[tuple[str, float, float]] = []
    records: list[dict[str, float | int | str]] = []
    admits = dict.fromkeys(BED_UNITS, 0)
    departures = dict.fromkeys(BED_UNITS, 0)
    occupied_bed_hours = dict.fromkeys(BED_UNITS, 0.0)
    arrivals_total = 0
    pending = list(schedule)
    for _ in range(start + total):
        minute = round(world.now)
        while pending and pending[0][0] <= minute:
            _, hospital_id = pending.pop(0)
            scenario = sim.start_scenario("flu_surge", hospital_id)
            surge_spans.append((hospital_id, world.now, scenario.ends or world.now))
        emitted = sim.tick()
        observer.feed(emitted)
        now = world.now
        if now >= start:
            for item in emitted:
                if isinstance(item.event, BedEvent):
                    unit = layout.beds_by_id[item.event.bed_id].unit
                    if item.event.state == "occupied":
                        admits[unit] += 1
                    elif item.event.state == "cleaning":
                        departures[unit] += 1
            for hospital in world.hospitals.values():
                for unit in BED_UNITS:
                    occupied_bed_hours[unit] += (
                        sum(1 for b in hospital.beds.values() if b.unit == unit and b.state == "occupied")
                        / 60.0
                    )
            if round(now) % SNAPSHOT_EVERY_MIN == 0:
                for hospital, patient in observer.scorable():
                    features = observer.features_for(hospital, patient, now)
                    if features is None:
                        continue
                    chart = observer.charts[patient.id]
                    records.append(
                        {
                            "minute": now - start,
                            "hospital": hospital.id,
                            "patient_id": patient.id,
                            "encounter_id": chart.encounter_id,
                            **features,
                        }
                    )
    rows = pd.DataFrame.from_records(records, columns=[*META[:4], *FEATURE_NAMES])
    rows["label"] = _label(rows, [(m - start, p, e) for m, p, e in observer.criticals])
    arrivals_total = sum(1 for m, _, _ in observer.arrivals if m >= start)
    arrivals = _hourly_arrivals(
        observer.arrivals, start, total, hospital_ids, [(h, a - start, b - start) for h, a, b in surge_spans]
    )
    unit_stats = {
        unit: {
            "admit_per_arrival": admits[unit] / max(1, arrivals_total),
            "departure_per_bed_hour": departures[unit] / max(1e-9, occupied_bed_hours[unit]),
        }
        for unit in BED_UNITS
    }
    logger.info(
        "Dataset: %d rows, %d positive, %d arrivals over %d days",
        len(rows),
        int(rows["label"].sum()),
        arrivals_total,
        days,
    )
    return Dataset(
        rows=rows,
        arrivals=arrivals,
        unit_stats=unit_stats,
        days=days,
        seed=seed,
        surges=[(h, a - start, b - start) for h, a, b in surge_spans],
    )


def _hourly_arrivals(
    arrivals: list[tuple[float, str, str]],
    start: float,
    total: int,
    hospitals: list[str],
    surges: list[tuple[str, float, float]],
) -> pd.DataFrame:
    """Arrivals per hospital per sim hour, with the flu-surge flag. Hour 0 is the start of the visible run."""
    hours = total // 60
    counts = {h: np.zeros(hours, dtype=np.int32) for h in hospitals}
    for minute, hospital, _ in arrivals:
        hour = int((minute - start) // 60)
        if 0 <= hour < hours and hospital in counts:
            counts[hospital][hour] += 1
    frames = []
    for hospital in hospitals:
        flag = np.zeros(hours, dtype=np.int8)
        for h, a, b in surges:
            if h == hospital:
                flag[max(0, int(a // 60)) : min(hours, int(b // 60) + 1)] = 1
        frames.append(
            pd.DataFrame(
                {
                    "hour": np.arange(hours),
                    "hospital": hospital,
                    "arrivals": counts[hospital],
                    "scenario": flag,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
