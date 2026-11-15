"""Model governance (PROMPT.md §8): drift, fairness and audit rows.

- **Drift.** Every 15 sim minutes, for each hospital and feature, the Population Stability Index compares the
  last 2 sim hours of scored rows with the training distribution. PSI above 0.2 raises a drift alert.
- **Fairness.** Every sim hour, AUROC and calibration by age band (18-39, 40-64, 65+) and by sex on the most
  recent labeled window: rows scored at least 6 sim hours ago, whose outcome is known. A gap above 0.05 AUROC
  between groups is flagged.
"""

import json
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from twin.ml.features import FEATURE_NAMES
from twin.ml.metrics import AGE_BANDS, auroc_or_none, calibration_gap

PSI_ALERT = 0.2
DRIFT_WINDOW_MIN = 120.0
DRIFT_EVERY_MIN = 15
MIN_DRIFT_SAMPLES = 20
SNAPSHOT_EVERY_MIN = 30
FAIRNESS_EVERY_MIN = 60
FAIRNESS_WINDOW_MIN = 24 * 60
LABEL_DELAY_MIN = 6 * 60
FAIRNESS_GAP = 0.05
MIN_GROUP_ROWS = 40
# Quantile levels of the inner bin edges. The tails get narrow bins so that a shift deeper into a tail (for
# example SpO2 falling from 93 to 88) changes the distribution; five equal bins would not see it.
EDGE_QUANTILES = (0.03, 0.10, 0.30, 0.70, 0.90, 0.97)
EPS = 5e-3
# Features whose drift is shown for respiratory illness (PROMPT.md §8 test).
RESPIRATORY_FEATURES = ("spo2", "spo2_min_2h", "spo2_max_2h", "rr", "rr_min_2h", "rr_max_2h", "temp")


@dataclass(frozen=True)
class FeatureBaseline:
    """Bin edges (inner edges only) and the share of training rows in each bin."""

    edges: list[float]
    proportions: list[float]


def make_baseline(train: pd.DataFrame, quantiles: tuple[float, ...] = EDGE_QUANTILES) -> dict[str, FeatureBaseline]:
    """Quantile bins of each feature over the training rows (missing values are ignored)."""
    out: dict[str, FeatureBaseline] = {}
    for name in FEATURE_NAMES:
        values = train[name].to_numpy(dtype=np.float64)
        values = values[~np.isnan(values)]
        if len(values) == 0:
            continue
        edges = sorted({float(e) for e in np.quantile(values, quantiles)})
        counts = np.bincount(np.searchsorted(edges, values, side="right"), minlength=len(edges) + 1)
        out[name] = FeatureBaseline(edges, [float(c) / len(values) for c in counts])
    return out


def make_baselines(train: pd.DataFrame) -> dict[str, dict[str, FeatureBaseline]]:
    """One baseline per hospital: each hospital's recent window is compared with its own training rows, since the
    hospitals differ in size and demand (a pooled baseline would make the quieter ones look like drift)."""
    return {str(h): make_baseline(part) for h, part in train.groupby("hospital")}


def save_baseline(baseline: dict[str, dict[str, FeatureBaseline]], directory: Path) -> None:
    payload = {h: {k: {"edges": v.edges, "proportions": v.proportions} for k, v in features.items()} for h, features in baseline.items()}
    (directory / "drift_baseline.json").write_text(json.dumps(payload), encoding="utf-8")


def load_baseline(directory: Path) -> dict[str, dict[str, FeatureBaseline]]:
    raw = json.loads((directory / "drift_baseline.json").read_text(encoding="utf-8"))
    return {
        h: {k: FeatureBaseline([float(e) for e in v["edges"]], [float(p) for p in v["proportions"]]) for k, v in features.items()}
        for h, features in raw.items()
    }


def raw_psi(baseline: FeatureBaseline, finite: np.ndarray) -> float:
    counts = np.bincount(np.searchsorted(baseline.edges, finite, side="right"), minlength=len(baseline.proportions))
    actual = np.maximum(counts / len(finite), EPS)
    expected = np.maximum(np.asarray(baseline.proportions), EPS)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def psi(
    baseline: FeatureBaseline,
    values: np.ndarray,
    *,
    correct_bias: bool = True,
    n_effective: int | None = None,
) -> float | None:
    """Population Stability Index of `values` against the baseline, or None if there are too few values.

    PSI of a small sample from the *same* distribution is not zero: it is about (bins - 1) / n. With the few
    patients a hospital has in 2 hours that noise alone would pass 0.2, so by default the expected noise is
    subtracted (never below 0). Pass `correct_bias=False` for the plain index."""
    finite = values[~np.isnan(values)]
    if len(finite) < MIN_DRIFT_SAMPLES:
        return None
    value = raw_psi(baseline, finite)
    if not correct_bias:
        return value
    # Rows of one patient at different times are alike, so the independent sample is nearer the number of patients.
    n = min(len(finite), n_effective) if n_effective else len(finite)
    return max(0.0, value - (len(baseline.proportions) - 1) / max(1, n))


@dataclass(frozen=True)
class DriftReading:
    time: datetime
    hospital_id: str
    feature: str
    psi: float


@dataclass
class DriftMonitor:
    baseline: dict[str, dict[str, FeatureBaseline]]
    alerting: set[tuple[str, str]] = field(default_factory=set)
    # Per hospital: the rows scored at 30-minute marks, the same sampling as the training rows, so that
    # patients count in proportion to how long they stay (comparing one row per patient would not be like
    # for like and drifts on its own).
    buffers: dict[str, deque[tuple[float, str, dict[str, float]]]] = field(default_factory=dict)

    def add(self, hospital_id: str, minute: float, rows: dict[str, dict[str, float]]) -> None:
        """Record the rows of a scoring batch (patient id -> feature row). Only 30-minute marks are kept."""
        if round(minute) % SNAPSHOT_EVERY_MIN != 0:
            return
        buf = self.buffers.setdefault(hospital_id, deque())
        for patient_id, row in rows.items():
            buf.append((minute, patient_id, row))
        while buf and buf[0][0] < minute - DRIFT_WINDOW_MIN:
            buf.popleft()

    def evaluate(self, now: float, time: datetime) -> tuple[list[DriftReading], list[DriftReading]]:
        """PSI for every feature at every hospital, and the readings that just crossed 0.2 (new alerts)."""
        readings: list[DriftReading] = []
        fresh: list[DriftReading] = []
        for hospital_id in sorted(self.buffers):
            window = [(p, r) for m, p, r in self.buffers[hospital_id] if m >= now - DRIFT_WINDOW_MIN]
            rows = [r for _, r in window]
            patients = len({p for p, _ in window})
            for feature, base in self.baseline.get(hospital_id, {}).items():
                value = psi(base, np.array([r[feature] for r in rows], dtype=np.float64), n_effective=patients)
                if value is None:
                    continue
                reading = DriftReading(time, hospital_id, feature, value)
                readings.append(reading)
                key = (hospital_id, feature)
                if value > PSI_ALERT and key not in self.alerting:
                    self.alerting.add(key)
                    fresh.append(reading)
                elif value <= PSI_ALERT:
                    self.alerting.discard(key)
        return readings, fresh


@dataclass(frozen=True)
class ScoredRow:
    minute: float
    patient_id: str
    age: int
    male: bool
    score: float
    hospital: str = ""


@dataclass
class FairnessMonitor:
    rows: deque[ScoredRow] = field(default_factory=deque)

    def add(self, row: ScoredRow) -> None:
        self.rows.append(row)
        while self.rows and self.rows[0].minute < row.minute - FAIRNESS_WINDOW_MIN - LABEL_DELAY_MIN:
            self.rows.popleft()

    def report(self, now: float, criticals: list[tuple[float, str, int]], hospital: str | None = None) -> dict[str, Any]:
        """Fairness on rows scored 6 to 30 sim hours ago, labeled from the critical events since. With `hospital`,
        only that hospital's rows count (network-wide otherwise)."""
        window = [
            r
            for r in self.rows
            if now - FAIRNESS_WINDOW_MIN - LABEL_DELAY_MIN <= r.minute <= now - LABEL_DELAY_MIN and (hospital is None or r.hospital == hospital)
        ]
        times: dict[str, list[float]] = {}
        for minute, patient_id, _ in criticals:
            times.setdefault(patient_id, []).append(minute)
        y = np.array(
            [1 if any(r.minute < t <= r.minute + LABEL_DELAY_MIN for t in times.get(r.patient_id, ())) else 0 for r in window],
            dtype=np.int_,
        )
        p = np.array([r.score for r in window], dtype=np.float64)
        ages = np.array([r.age for r in window])
        male = np.array([r.male for r in window], dtype=bool)
        groups: dict[str, Any] = {}

        def group(name: str, mask: np.ndarray) -> None:
            ys, ps = y[mask], p[mask]
            ok = len(ys) >= MIN_GROUP_ROWS and len(set(ys.tolist())) == 2
            groups[name] = {
                "n": len(ys),
                "positives": int(ys.sum()),
                "auroc": auroc_or_none(ys, ps) if ok else None,
                "calibration_gap": calibration_gap(ys, ps) if len(ys) else None,
            }

        for label, lo, hi in AGE_BANDS:
            group(f"age {label}", (ages >= lo) & (ages <= hi))
        group("male", male)
        group("female", ~male)
        aurocs = {k: g["auroc"] for k, g in groups.items() if g["auroc"] is not None}
        gap = float(max(aurocs.values()) - min(aurocs.values())) if len(aurocs) > 1 else 0.0
        return {
            "overall_auroc": auroc_or_none(y, p) if len(window) >= MIN_GROUP_ROWS and len(set(y.tolist())) == 2 else None,
            "rows": len(window),
            "positives": int(y.sum()),
            "groups": groups,
            "max_auroc_gap": gap,
            "flagged": gap > FAIRNESS_GAP,
            "threshold": FAIRNESS_GAP,
        }


def finite(x: float) -> float | None:
    return None if math.isnan(x) else x
