"""Trains and evaluates the deterioration model (PROMPT.md §7.2).

Time-based split: the first 60% of sim time trains, the next 20% validates (early stopping and calibration),
the last 20% tests. NEWS2 alone, calibrated the same way, is the baseline. Metrics, fairness by age band and
sex, and the model files are saved to `models/<version>/`.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from twin.ml.dataset import Dataset
from twin.ml.features import FEATURE_NAMES
from twin.ml.governance import make_baselines, save_baseline
from twin.ml.metrics import AGE_BANDS, Floats, Ints, auroc_or_none, calibration_gap, evaluate
from twin.ml.model import Calibrator, DeteriorationModel
from twin.ml.split import Split, split_by_time

logger = logging.getLogger(__name__)

MODEL_VERSION = "lgbm-v1"
SEED = 7
PARAMS: dict[str, Any] = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 50,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
}
MAX_ROUNDS = 600
EARLY_STOP = 40


def _labels(frame: pd.DataFrame) -> Ints:
    return np.asarray(frame["label"], dtype=np.int_)


@dataclass
class TrainResult:
    model: DeteriorationModel
    metrics: dict[str, Any]
    split: Split


def _fit_isotonic(raw: Floats, y: Ints) -> Calibrator:
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(raw, y)
    return Calibrator(x=[float(v) for v in iso.X_thresholds_], y=[float(v) for v in iso.y_thresholds_])


def train_deterioration(rows: pd.DataFrame, version: str = MODEL_VERSION) -> TrainResult:
    """Train, calibrate and evaluate. Raises if a split has only one class."""
    split = split_by_time(rows)
    for name, part in (("train", split.train), ("validation", split.val), ("test", split.test)):
        if len(part) == 0 or part["label"].nunique() < 2:
            raise ValueError(f"The {name} split has no positive and negative rows; run a longer simulation")
    feats = list(FEATURE_NAMES)
    d_train = lgb.Dataset(split.train[feats], label=_labels(split.train), free_raw_data=False)
    d_val = lgb.Dataset(split.val[feats], label=_labels(split.val), reference=d_train, free_raw_data=False)
    booster = lgb.train(
        PARAMS,
        d_train,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[d_val],
        callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)],
    )
    raw_val = np.asarray(booster.predict(split.val[feats]), dtype=np.float64)
    model = DeteriorationModel(version, booster, _fit_isotonic(raw_val, _labels(split.val)))

    metrics: dict[str, Any] = {
        "version": version,
        "features": feats,
        "best_iteration": int(booster.best_iteration or MAX_ROUNDS),
    }
    baseline = _fit_isotonic(split.val["news2"].to_numpy(dtype=np.float64), _labels(split.val))
    for name, part in (("validation", split.val), ("test", split.test)):
        y = _labels(part)
        metrics[name] = {
            "model": evaluate(y, model.predict(part)),
            "news2_baseline": evaluate(y, baseline.apply(part["news2"].to_numpy(dtype=np.float64))),
        }
    metrics["split"] = {
        name: {
            "rows": len(part),
            "positives": int(part["label"].sum()),
            "minutes": [float(part["minute"].min()), float(part["minute"].max())],
        }
        for name, part in (("train", split.train), ("validation", split.val), ("test", split.test))
    }
    metrics["fairness"] = fairness(split.test, model.predict(split.test))
    metrics["feature_importance"] = _importance(booster)
    logger.info(
        "Deterioration model: validation AUROC %.3f (NEWS2 %.3f), test AUROC %.3f (NEWS2 %.3f)",
        metrics["validation"]["model"]["auroc"],
        metrics["validation"]["news2_baseline"]["auroc"],
        metrics["test"]["model"]["auroc"],
        metrics["test"]["news2_baseline"]["auroc"],
    )
    return TrainResult(model, metrics, split)


def _importance(booster: lgb.Booster) -> dict[str, float]:
    gains = booster.feature_importance(importance_type="gain")
    total = float(np.sum(gains)) or 1.0
    return {name: round(float(g) / total, 4) for name, g in sorted(zip(FEATURE_NAMES, gains, strict=True), key=lambda t: -t[1])}


def fairness(frame: pd.DataFrame, prob: Floats) -> dict[str, Any]:
    """AUROC and calibration gap by age band and by sex (PROMPT.md §8 uses the same definitions live)."""
    y = _labels(frame)
    groups: dict[str, Any] = {}
    ages = frame["age"].to_numpy()
    for label, lo, hi in AGE_BANDS:
        mask = (ages >= lo) & (ages <= hi)
        groups[f"age {label}"] = _group(y[mask], prob[mask])
    male = frame["sex_male"].to_numpy() == 1.0
    groups["male"] = _group(y[male], prob[male])
    groups["female"] = _group(y[~male], prob[~male])
    aurocs = [g["auroc"] for g in groups.values() if g["auroc"] is not None]
    return {"groups": groups, "max_auroc_gap": float(max(aurocs) - min(aurocs)) if len(aurocs) > 1 else 0.0}


def _group(y: Ints, prob: Floats) -> dict[str, Any]:
    return {
        "n": len(y),
        "positives": int(y.sum()),
        "auroc": auroc_or_none(y, prob),
        "calibration_gap": calibration_gap(y, prob) if len(y) else None,
    }


def save_run(result: TrainResult, dataset: Dataset, directory: Path) -> None:
    """Write the model files and metrics.json under `directory` (models/<version>/)."""
    result.model.save(directory)
    save_baseline(make_baselines(result.split.train), directory)
    summary = {
        "days": dataset.days,
        "seed": dataset.seed,
        "rows": len(dataset.rows),
        "positives": int(dataset.rows["label"].sum()),
        "flu_surges": [{"hospital": h, "start_min": a, "end_min": b} for h, a, b in dataset.surges],
    }
    (directory / "metrics.json").write_text(json.dumps({**result.metrics, "data": summary}, indent=1) + "\n", encoding="utf-8")
