"""Length-of-stay model (PROMPT.md §7.5): hours until discharge for every admitted patient.

LightGBM regression on log hours. Features are the deterioration features plus the chief complaint (the
admission reason category) and the patient's current risk score. Training rows come from the same headless run
as the other models: a row is kept when its patient left the hospital before the run ended, so the remaining
time is known. The baseline is the median remaining stay by unit and hours-since-admission bucket.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from twin.ml.features import FEATURE_NAMES
from twin.ml.model import MODELS_DIR, DeteriorationModel
from twin.ml.split import split_by_time

logger = logging.getLogger(__name__)

LOS_VERSION = "los-lgbm-v1"
LOS_UNITS = (0, 1, 2, 3)  # feature codes of ER, WARD, ICU, REC (see features.UNITS): patients in a bed
LOS_FEATURES: tuple[str, ...] = (*FEATURE_NAMES, "complaint", "hours_in_unit", "risk")
BUCKET_H = 6.0
MAX_BUCKET = 12
MIN_IMPROVEMENT = 0.10
MAX_REMAINING_H = 24 * 14
PARAMS: dict[str, Any] = {
    "objective": "regression_l1",  # median regression, which is what MAE rewards
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 300,  # one patient contributes many rows; large leaves keep the trees from memorising patients
    "feature_fraction": 0.7,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": 7,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
}


def bucket_of(hours_since_admission: float) -> int:
    return min(MAX_BUCKET, int(max(0.0, hours_since_admission) // BUCKET_H))


@dataclass
class LosBaseline:
    """Median remaining hours by (unit code, hours-since-admission bucket), with the unit median as fallback."""

    by_cell: dict[tuple[int, int], float]
    by_unit: dict[int, float]
    overall: float

    def predict(self, unit: float, hours_since_admission: float) -> float:
        u = int(unit)
        return self.by_cell.get((u, bucket_of(hours_since_admission)), self.by_unit.get(u, self.overall))

    def to_json(self) -> dict[str, Any]:
        return {
            "cells": [[u, b, v] for (u, b), v in sorted(self.by_cell.items())],
            "units": [[u, v] for u, v in sorted(self.by_unit.items())],
            "overall": self.overall,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "LosBaseline":
        return LosBaseline(
            {(int(u), int(b)): float(v) for u, b, v in data["cells"]},
            {int(u): float(v) for u, v in data["units"]},
            float(data["overall"]),
        )


def fit_baseline(rows: pd.DataFrame) -> LosBaseline:
    unit = rows["unit"].to_numpy()
    bucket = np.array([bucket_of(h) for h in rows["hours_since_admission"]])
    remaining = rows["remaining_h"].to_numpy(dtype=np.float64)
    cells: dict[tuple[int, int], float] = {}
    for u in np.unique(unit):
        for b in np.unique(bucket[unit == u]):
            mask = (unit == u) & (bucket == b)
            if mask.sum() >= 5:
                cells[(int(u), int(b))] = float(np.median(remaining[mask]))
    units = {int(u): float(np.median(remaining[unit == u])) for u in np.unique(unit)}
    return LosBaseline(cells, units, float(np.median(remaining)))


class LosModel:
    def __init__(self, version: str, booster: lgb.Booster, baseline: LosBaseline) -> None:
        self.version = version
        self.booster = booster
        self.baseline = baseline

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """Expected remaining hours for each row (at least 0.25 h)."""
        raw = np.asarray(self.booster.predict(frame[list(LOS_FEATURES)]), dtype=np.float64)
        return np.clip(np.exp(raw), 0.25, MAX_REMAINING_H)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(directory / "model.txt"))
        (directory / "baseline.json").write_text(json.dumps(self.baseline.to_json()), encoding="utf-8")

    @staticmethod
    def load(version: str = LOS_VERSION, root: Path = MODELS_DIR) -> "LosModel":
        d = root / version
        if not (d / "model.txt").is_file():
            raise FileNotFoundError(f"No trained model {version} in {root}")
        baseline = LosBaseline.from_json(json.loads((d / "baseline.json").read_text(encoding="utf-8")))
        return LosModel(version, lgb.Booster(model_file=str(d / "model.txt")), baseline)


def los_rows(rows: pd.DataFrame, deterioration: DeteriorationModel) -> pd.DataFrame:
    """Rows of admitted patients (in a bed) whose stay ended in the run, with their current risk and the target."""
    kept = rows[rows["unit"].isin(LOS_UNITS) & rows["exit_minute"].notna()].copy()
    kept["remaining_h"] = (kept["exit_minute"] - kept["minute"]) / 60.0
    kept = kept[kept["remaining_h"] > 0].copy()
    kept["risk"] = [s.score for s in deterioration.score(kept[list(FEATURE_NAMES)])] if len(kept) else []
    return kept


def _mae(pred: np.ndarray, target: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - target)))


def train_los(rows: pd.DataFrame, deterioration: DeteriorationModel, version: str = LOS_VERSION) -> tuple[LosModel, dict[str, Any]]:
    """Time split 60/20/20. Early stopping on validation; the gate compares validation MAE with the baseline."""
    data = los_rows(rows, deterioration)
    split = split_by_time(data)
    if len(split.val) < 50 or len(split.train) < 200:
        raise ValueError("Not enough finished stays to train the length-of-stay model; run a longer simulation")
    baseline = fit_baseline(split.train)
    feats = list(LOS_FEATURES)
    d_train = lgb.Dataset(split.train[feats], label=np.log(split.train["remaining_h"].to_numpy()), free_raw_data=False)
    d_val = lgb.Dataset(split.val[feats], label=np.log(split.val["remaining_h"].to_numpy()), reference=d_train, free_raw_data=False)
    booster = lgb.train(PARAMS, d_train, num_boost_round=600, valid_sets=[d_val], callbacks=[lgb.early_stopping(40, verbose=False)])
    model = LosModel(version, booster, baseline)

    def evaluate(frame: pd.DataFrame) -> dict[str, float]:
        target = frame["remaining_h"].to_numpy(dtype=np.float64)
        base = np.array([baseline.predict(u, h) for u, h in zip(frame["unit"], frame["hours_since_admission"], strict=True)])
        mae, base_mae = _mae(model.predict(frame), target), _mae(base, target)
        return {"mae": mae, "baseline_mae": base_mae, "improvement": 1 - mae / base_mae if base_mae else 0.0, "rows": float(len(frame))}

    metrics: dict[str, Any] = {
        "version": version,
        "validation": evaluate(split.val),
        "test": evaluate(split.test) if len(split.test) else None,
        "features": feats,
        "best_iteration": int(booster.best_iteration or 600),
        "baseline": "median remaining hours by unit and hours-since-admission bucket",
        "rows": {"train": len(split.train), "validation": len(split.val), "test": len(split.test)},
    }
    logger.info("LOS: validation MAE %.2f h vs baseline %.2f h", metrics["validation"]["mae"], metrics["validation"]["baseline_mae"])
    return model, metrics


def discharge_rates(remaining_by_unit: dict[str, list[float]], window_h: float = 6.0) -> dict[str, float]:
    """Expected discharges per hour for each unit: patients predicted to leave within the window, per hour of window."""
    return {unit: sum(1 for r in values if r <= window_h) / window_h for unit, values in remaining_by_unit.items()}
