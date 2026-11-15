"""ER arrivals forecast and capacity projection (PROMPT.md §7.3).

A LightGBM regression predicts arrivals per hospital for each of the next 6 sim hours from the hour of day,
the day of week, the last 24 hourly counts, rolling means and whether a scenario is active. It must beat a
seasonal-naive baseline (the same hour yesterday) on validation MAE. The capacity projection turns the
forecast into "hours until full" per unit.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from twin.common.config import REPO_ROOT
from twin.ml.metrics import Floats

FORECAST_VERSION = "arrivals-lgbm-v1"
MODELS_DIR = REPO_ROOT / "models"
HORIZON_H = 6
LAGS = 24
START_HOUR_OF_DAY = 8  # the visible run starts at 08:00 Phoenix time
START_DAY_OF_WEEK = 5  # 2026-11-14 is a Saturday (Monday = 0)
HOSPITAL_CODE = {"mercy": 0, "stlukes": 1, "desert": 2}
BED_UNITS = ("ER", "WARD", "ICU", "REC")
VAL_FRAC = 0.3
MAX_HOURS_UNTIL_FULL = 24.0
FEATURES = (
    "hospital",
    "horizon",
    "target_hour",
    "target_dow",
    "scenario",
    *(f"lag_{i}" for i in range(LAGS)),
    "mean_3h",
    "mean_6h",
    "mean_24h",
)
PARAMS: dict[str, Any] = {
    "objective": "regression_l1",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 30,
    "feature_fraction": 0.9,
    "verbosity": -1,
    "seed": 7,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
}


def hour_of_day(hour: int) -> int:
    """Local hour of day for sim hour `hour` (hour 0 = 08:00)."""
    return (START_HOUR_OF_DAY + hour) % 24


def day_of_week(hour: int) -> int:
    return (START_DAY_OF_WEEK + (START_HOUR_OF_DAY + hour) // 24) % 7


def feature_row(hospital: str, history: Floats, hour: int, scenario: int, horizon: int) -> dict[str, float]:
    """Features for forecasting `horizon` hours after sim hour `hour`. `history[-1]` is the count of hour
    `hour` itself; `history` must hold at least 24 values (older first)."""
    if len(history) < LAGS:
        raise ValueError(f"Need {LAGS} hourly counts, got {len(history)}")
    recent = history[-LAGS:][::-1]  # lag_0 is the latest hour
    row: dict[str, float] = {
        "hospital": float(HOSPITAL_CODE[hospital]),
        "horizon": float(horizon),
        "target_hour": float(hour_of_day(hour + horizon)),
        "target_dow": float(day_of_week(hour + horizon)),
        "scenario": float(scenario),
        "mean_3h": float(np.mean(recent[:3])),
        "mean_6h": float(np.mean(recent[:6])),
        "mean_24h": float(np.mean(recent)),
    }
    for i in range(LAGS):
        row[f"lag_{i}"] = float(recent[i])
    return row


def make_rows(arrivals: pd.DataFrame) -> pd.DataFrame:
    """One row per (hospital, hour, horizon): features at that hour and the arrivals `horizon` hours later."""
    out: list[dict[str, float]] = []
    for hospital, part in arrivals.groupby("hospital"):
        counts = part.sort_values("hour")["arrivals"].to_numpy(dtype=np.float64)
        flag = part.sort_values("hour")["scenario"].to_numpy()
        for t in range(LAGS - 1, len(counts) - HORIZON_H):
            for h in range(1, HORIZON_H + 1):
                row = feature_row(str(hospital), counts[: t + 1], t, int(flag[t]), h)
                row["hour"] = float(t)
                row["target"] = float(counts[t + h])
                row["naive"] = float(counts[t + h - 24]) if t + h - 24 >= 0 else float(counts[t])
                out.append(row)
    return pd.DataFrame(out)


@dataclass
class ArrivalsModel:
    version: str
    booster: lgb.Booster
    unit_stats: dict[str, dict[str, float]]

    def forecast(self, hospital: str, history: Floats, hour: int, scenario: int) -> list[float]:
        """Predicted arrivals for each of the next 6 sim hours (never negative)."""
        rows = pd.DataFrame([feature_row(hospital, history, hour, scenario, h) for h in range(1, HORIZON_H + 1)])
        pred = np.asarray(self.booster.predict(rows[list(FEATURES)]), dtype=np.float64)
        return [max(0.0, float(v)) for v in pred]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(directory / "model.txt"))
        (directory / "unit_stats.json").write_text(json.dumps(self.unit_stats, indent=1), encoding="utf-8")

    @staticmethod
    def load(version: str = FORECAST_VERSION, root: Path = MODELS_DIR) -> "ArrivalsModel":
        d = root / version
        if not (d / "model.txt").is_file():
            raise FileNotFoundError(f"No trained model {version} in {root}")
        booster = lgb.Booster(model_file=str(d / "model.txt"))
        stats = json.loads((d / "unit_stats.json").read_text(encoding="utf-8"))
        return ArrivalsModel(version, booster, stats)


def train_arrivals(
    arrivals: pd.DataFrame, unit_stats: dict[str, dict[str, float]], version: str = FORECAST_VERSION
) -> tuple[ArrivalsModel, dict[str, Any]]:
    """Train on the first 70% of the hours, validate on the last 30%, and compare with seasonal naive."""
    rows = make_rows(arrivals)
    cut = rows["hour"].min() + (rows["hour"].max() - rows["hour"].min()) * (1 - VAL_FRAC)
    train, val = rows[rows["hour"] <= cut], rows[rows["hour"] > cut]
    if len(val) == 0:
        raise ValueError("Not enough hours to validate the arrivals forecast; run a longer simulation")
    feats = list(FEATURES)
    d_train = lgb.Dataset(train[feats], label=train["target"].to_numpy(), free_raw_data=False)
    d_val = lgb.Dataset(val[feats], label=val["target"].to_numpy(), reference=d_train, free_raw_data=False)
    booster = lgb.train(
        PARAMS,
        d_train,
        num_boost_round=400,
        valid_sets=[d_val],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    pred = np.asarray(booster.predict(val[feats]), dtype=np.float64)
    target = val["target"].to_numpy(dtype=np.float64)
    mae = float(np.mean(np.abs(pred - target)))
    naive = float(np.mean(np.abs(val["naive"].to_numpy(dtype=np.float64) - target)))
    by_h = {
        str(h): {
            "mae": float(np.mean(np.abs(pred[val["horizon"].to_numpy() == h] - target[val["horizon"].to_numpy() == h]))),
            "naive_mae": float(np.mean(np.abs(val["naive"].to_numpy()[val["horizon"].to_numpy() == h] - target[val["horizon"].to_numpy() == h]))),
        }
        for h in range(1, HORIZON_H + 1)
    }
    metrics = {
        "version": version,
        "validation": {
            "mae": mae,
            "seasonal_naive_mae": naive,
            "improvement": 1 - mae / naive if naive else 0.0,
            "rows": len(val),
            "by_horizon": by_h,
        },
        "features": feats,
        "best_iteration": int(booster.best_iteration or 400),
    }
    return ArrivalsModel(version, booster, unit_stats), metrics


def project_capacity(
    forecast: list[float],
    occupancy: dict[str, int],
    capacity: dict[str, int],
    unit_stats: dict[str, dict[str, float]],
    discharge_rate: dict[str, float] | None = None,
) -> dict[str, float | None]:
    """Hours until each unit is full: free beds divided by the net inflow per hour.

    Inflow = forecast arrivals per hour x the share of arrivals admitted to the unit. Outflow = expected
    discharges per hour: the unit's historical departure rate per occupied bed unless `discharge_rate` (from
    length-of-stay predictions) is given. Returns 0.0 for a full unit and None when the unit will not fill
    within the horizon (net inflow is not positive or the time exceeds 24 h)."""
    mean_arrivals = float(np.mean(forecast)) if forecast else 0.0
    out: dict[str, float | None] = {}
    for unit in BED_UNITS:
        free = capacity[unit] - occupancy.get(unit, 0)
        if free <= 0:
            out[unit] = 0.0
            continue
        stats = unit_stats.get(unit, {})
        inflow = mean_arrivals * stats.get("admit_per_arrival", 0.0)
        outflow = (
            discharge_rate[unit]
            if discharge_rate is not None and unit in discharge_rate
            else occupancy.get(unit, 0) * stats.get("departure_per_bed_hour", 0.0)
        )
        net = inflow - outflow
        hours = free / net if net > 1e-9 else None
        out[unit] = hours if hours is not None and hours <= MAX_HOURS_UNTIL_FULL else None
    return out
