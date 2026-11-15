"""Live inference inside the simulation loop (PROMPT.md §7.4).

Every 5 sim minutes every waiting or admitted patient is scored; a `risk` event is emitted for each, and an
`alert` event when a patient enters the high level. Every 15 sim minutes the arrivals forecast and the
capacity projection are refreshed and queued for the `forecasts` table. The engine only reads what the
`Observer` exposes, never the hidden physiology.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from twin.common.ws import AlertEvent, Risk, RiskEvent
from twin.ml.features import FEATURE_NAMES
from twin.ml.forecast import BED_UNITS, LAGS, MAX_HOURS_UNTIL_FULL, ArrivalsModel, project_capacity
from twin.ml.model import DeteriorationModel
from twin.ml.observe import Observer
from twin.sim.config import SIM_START
from twin.sim.scenarios import flu_active
from twin.sim.world import Emitted, World

logger = logging.getLogger(__name__)

SCORE_EVERY_MIN = 5
FORECAST_EVERY_MIN = 15
SCORING_LEAD_MIN = 6 * 60  # start scoring this long before the visible start, so charts have history
NOT_FULL = MAX_HOURS_UNTIL_FULL + 75.0  # stored value meaning "will not fill within 24 h"


@dataclass
class ForecastRow:
    time: datetime
    hospital_id: str
    model_version: str
    horizon_h: int
    metric: str
    value: float


@dataclass
class InferenceEngine:
    world: World
    model: DeteriorationModel
    arrivals_model: ArrivalsModel | None = None
    observer: Observer = field(init=False)
    levels: dict[str, str] = field(default_factory=dict)
    pending_forecasts: list[ForecastRow] = field(default_factory=list)
    batches: int = 0
    scored: int = 0

    def __post_init__(self) -> None:
        self.observer = Observer(self.world)

    # ---- called by the simulation after every tick ---------------------------------------------------------

    def after_tick(self, emitted: list[Emitted]) -> None:
        self.observer.feed(emitted)
        minute = round(self.world.now)
        start = self.world.minutes(SIM_START) - SCORING_LEAD_MIN
        if self.world.now < start:
            return
        if minute % SCORE_EVERY_MIN == 0:
            self.score_all()
        if self.arrivals_model is not None and minute % FORECAST_EVERY_MIN == 0:
            self.forecast_all()

    # ---- risk scores ----------------------------------------------------------------------------------

    def score_all(self) -> int:
        """Score every waiting or admitted patient with something charted. Returns how many were scored."""
        now = self.world.now
        rows: list[dict[str, float]] = []
        targets = []
        for hospital, patient in self.observer.scorable():
            features = self.observer.features_for(hospital, patient, now)
            if features is not None:
                rows.append(features)
                targets.append((hospital, patient))
        if not rows:
            return 0
        scored = self.model.score(pd.DataFrame(rows, columns=list(FEATURE_NAMES)))
        for (hospital, patient), s in zip(targets, scored, strict=True):
            risk = Risk(
                score=round(s.score, 4),
                level=s.level,
                top_factors=s.top_factors,
                model_version=self.model.version,
            )
            patient.risk = risk
            self.world.emit(
                hospital.id,
                RiskEvent(
                    time=self.world.time(),
                    patient_id=patient.id,
                    score=risk.score,
                    level=risk.level,
                    top_factors=risk.top_factors,
                    model_version=risk.model_version,
                ),
            )
            if s.level == "high" and self.levels.get(patient.id) != "high":
                self.world.emit(
                    hospital.id,
                    AlertEvent(time=self.world.time(), patient_id=patient.id, level="high", score=risk.score),
                )
            self.levels[patient.id] = s.level
        self.batches += 1
        self.scored += len(targets)
        return len(targets)

    # ---- forecasts ------------------------------------------------------------------------------------

    def hourly_arrivals(self, hospital_id: str, hours: int) -> tuple[np.ndarray, int]:
        """Arrivals per completed sim hour, oldest first, and the index of the last completed hour. Hour 0
        starts at the visible start (08:00), the same convention as in training."""
        visible = self.world.minutes(SIM_START)
        last = int((self.world.now - visible) // 60) - 1
        counts = np.zeros(hours, dtype=np.float64)
        for minute, hospital, _ in self.observer.arrivals:
            if hospital != hospital_id:
                continue
            hour = int((minute - visible) // 60)
            index = hour - (last - hours + 1)
            if 0 <= index < hours:
                counts[index] += 1
        return counts, last

    def forecast_all(self) -> None:
        if self.arrivals_model is None:
            return
        layout = self.world.layout
        for hospital_id in sorted(self.world.hospitals):
            hospital = self.world.hospitals[hospital_id]
            history, last = self.hourly_arrivals(hospital_id, LAGS)
            forecast = self.arrivals_model.forecast(
                hospital_id, history, last, int(flu_active(self.world, hospital_id))
            )
            occupancy = {
                u: sum(1 for b in hospital.beds.values() if b.unit == u and b.state == "occupied")
                for u in BED_UNITS
            }
            hours = project_capacity(forecast, occupancy, layout.capacity, self.arrivals_model.unit_stats)
            when, version = self.world.time(), self.arrivals_model.version
            for h, value in enumerate(forecast, start=1):
                self.pending_forecasts.append(ForecastRow(when, hospital_id, version, h, "arrivals", value))
            for unit in BED_UNITS:
                hrs = hours[unit]
                self.pending_forecasts.append(
                    ForecastRow(
                        when,
                        hospital_id,
                        version,
                        0,
                        f"hours_until_full:{unit}",
                        NOT_FULL if hrs is None else hrs,
                    )
                )

    def drain_forecasts(self) -> list[ForecastRow]:
        out, self.pending_forecasts = self.pending_forecasts, []
        return out

    def high_risk_count(self, hospital_id: str) -> int:
        hospital = self.world.hospitals[hospital_id]
        return sum(1 for p in hospital.patients() if p.risk is not None and p.risk.level == "high")
