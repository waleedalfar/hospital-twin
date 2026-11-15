"""Live inference inside the simulation loop (PROMPT.md §7.4).

Every 5 sim minutes every waiting or admitted patient is scored; a `risk` event is emitted for each, and an
`alert` event when a patient enters the high level. Every 15 sim minutes the arrivals forecast and the
capacity projection are refreshed and queued for the `forecasts` table. The engine only reads what the
`Observer` exposes, never the hidden physiology.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from twin.common.ws import AlertEvent, DriftAlertEvent, Risk, RiskEvent
from twin.ml.features import FEATURE_NAMES
from twin.ml.forecast import BED_UNITS, LAGS, MAX_HOURS_UNTIL_FULL, ArrivalsModel, project_capacity
from twin.ml.governance import (
    DRIFT_EVERY_MIN,
    FAIRNESS_EVERY_MIN,
    DriftMonitor,
    DriftReading,
    FairnessMonitor,
    FeatureBaseline,
    ScoredRow,
)
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


@dataclass(frozen=True)
class AuditRow:
    time: datetime
    actor: str
    action: str
    payload: dict[str, Any]


@dataclass
class InferenceEngine:
    world: World
    model: DeteriorationModel
    arrivals_model: ArrivalsModel | None = None
    baseline: dict[str, dict[str, FeatureBaseline]] | None = None
    observer: Observer = field(init=False)
    levels: dict[str, str] = field(default_factory=dict)
    pending_forecasts: list[ForecastRow] = field(default_factory=list)
    pending_audit: list[AuditRow] = field(default_factory=list)
    pending_drift: list[DriftReading] = field(default_factory=list)
    drift: DriftMonitor | None = None
    fairness: FairnessMonitor = field(default_factory=FairnessMonitor)
    latest_drift: list[DriftReading] = field(default_factory=list)
    latest_fairness: dict[str, Any] | None = None
    batches: int = 0
    scored: int = 0

    def __post_init__(self) -> None:
        self.observer = Observer(self.world)
        if self.baseline is not None:
            self.drift = DriftMonitor(self.baseline)

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
        if self.drift is not None and minute % DRIFT_EVERY_MIN == 0:
            self.check_drift()
        if minute % FAIRNESS_EVERY_MIN == 0:
            self.check_fairness()

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
        per_hospital: dict[str, dict[str, dict[str, float]]] = {}
        for (hospital, patient), s, features in zip(targets, scored, rows, strict=True):
            per_hospital.setdefault(hospital.id, {})[patient.id] = features
            if round(now) % 30 == 0 and patient.profile is not None:
                self.fairness.add(ScoredRow(now, patient.id, patient.profile.age, patient.profile.sex == "male", s.score))
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
                self.audit(
                    "system",
                    "risk_alert",
                    {"patient_id": patient.id, "hospital_id": hospital.id, "score": risk.score},
                )
            self.levels[patient.id] = s.level
        self.batches += 1
        self.scored += len(targets)
        if self.drift is not None:
            for hospital_id, hospital_rows in per_hospital.items():
                self.drift.add(hospital_id, now, hospital_rows)
        self.audit(
            "system",
            "inference_batch",
            {
                "model_version": self.model.version,
                "patients": len(targets),
                "by_hospital": {h: len(r) for h, r in per_hospital.items()},
            },
        )
        return len(targets)

    # ---- governance ---------------------------------------------------------------------------------

    def audit(self, actor: str, action: str, payload: dict[str, Any]) -> None:
        self.pending_audit.append(AuditRow(self.world.time(), actor, action, payload))

    def check_drift(self) -> None:
        """PSI per feature and hospital over the last 2 sim hours; a drift alert for each new crossing of 0.2."""
        if self.drift is None:
            return
        readings, fresh = self.drift.evaluate(self.world.now, self.world.time())
        self.latest_drift = readings
        self.pending_drift.extend(readings)
        for r in fresh:
            self.world.emit(r.hospital_id, DriftAlertEvent(time=r.time, feature=r.feature, psi=round(r.psi, 3)))
            self.audit(
                "system",
                "drift_alert",
                {"hospital_id": r.hospital_id, "feature": r.feature, "psi": round(r.psi, 3)},
            )

    def check_fairness(self) -> None:
        report = self.fairness.report(self.world.now, self.observer.criticals)
        self.latest_fairness = {**report, "as_of": self.world.time().isoformat()}
        self.audit(
            "system",
            "fairness_report",
            {"rows": report["rows"], "max_auroc_gap": report["max_auroc_gap"], "flagged": report["flagged"]},
        )

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
            forecast = self.arrivals_model.forecast(hospital_id, history, last, int(flu_active(self.world, hospital_id)))
            occupancy = {u: sum(1 for b in hospital.beds.values() if b.unit == u and b.state == "occupied") for u in BED_UNITS}
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

    def drain_audit(self) -> list[AuditRow]:
        out, self.pending_audit = self.pending_audit, []
        return out

    def drain_drift(self) -> list[DriftReading]:
        out, self.pending_drift = self.pending_drift, []
        return out

    def drain_forecasts(self) -> list[ForecastRow]:
        out, self.pending_forecasts = self.pending_forecasts, []
        return out

    def high_risk_count(self, hospital_id: str) -> int:
        hospital = self.world.hospitals[hospital_id]
        return sum(1 for p in hospital.patients() if p.risk is not None and p.risk.level == "high")
