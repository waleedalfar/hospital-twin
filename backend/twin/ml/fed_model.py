"""The federated deterioration model at inference time (PROMPT.md §7.6): a small MLP stored as plain arrays.

Forward and attribution run in numpy, so the API does not need PyTorch to score patients. Inputs are scaled by
fixed constants (`FEATURE_SCALE`) that every hospital knows in advance, so no statistics of any hospital's data are
shared. Probabilities are calibrated like the LightGBM model's; factors are gradient x input, as signed shares.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from twin.ml.features import FEATURE_NAMES
from twin.ml.metrics import Floats
from twin.ml.model import MODELS_DIR, Calibrator, Scored, level_of, top_factors

FED_VERSION = "fed-mlp-v1"
HIDDEN = (64, 32)

# (center, scale) for each feature, written down once from the physiology the features describe.
FEATURE_SCALE: dict[str, tuple[float, float]] = {
    "hr": (80, 25),
    "spo2": (96, 4),
    "sbp": (120, 25),
    "dbp": (70, 15),
    "temp": (37, 0.8),
    "rr": (16, 5),
    "hr_d1h": (0, 12),
    "spo2_d1h": (0, 3),
    "sbp_d1h": (0, 15),
    "rr_d1h": (0, 4),
    "temp_d1h": (0, 0.6),
    "hr_d2h": (0, 15),
    "spo2_d2h": (0, 4),
    "sbp_d2h": (0, 18),
    "rr_d2h": (0, 5),
    "temp_d2h": (0, 0.8),
    "spo2_min_2h": (96, 4),
    "spo2_max_2h": (96, 4),
    "hr_min_2h": (80, 25),
    "hr_max_2h": (80, 25),
    "rr_min_2h": (16, 5),
    "rr_max_2h": (16, 5),
    "news2": (3, 3),
    "age": (55, 22),
    "sex_male": (0.5, 0.5),
    "comorbidities": (2, 2),
    "unit": (1.5, 1.5),
    "hours_since_admission": (10, 24),
    "esi": (3, 1.2),
}
CENTER = np.array([FEATURE_SCALE[n][0] for n in FEATURE_NAMES], dtype=np.float64)
SCALE = np.array([FEATURE_SCALE[n][1] for n in FEATURE_NAMES], dtype=np.float64)


def normalise(frame: pd.DataFrame) -> Floats:
    """Scaled feature matrix; a missing value (no history yet) becomes 0, the scaled centre."""
    x = (frame[list(FEATURE_NAMES)].to_numpy(dtype=np.float64) - CENTER) / SCALE
    return np.nan_to_num(x, nan=0.0)


@dataclass
class FederatedMlp:
    version: str
    weights: list[Floats]  # w0, b0, w1, b1, w2, b2
    calibrator: Calibrator

    def logits(self, x: Floats) -> Floats:
        h = x
        for i in range(0, len(self.weights) - 2, 2):
            h = np.maximum(h @ self.weights[i].T + self.weights[i + 1], 0.0)
        return np.asarray((h @ self.weights[-2].T + self.weights[-1])[:, 0], dtype=np.float64)

    def raw(self, frame: pd.DataFrame) -> Floats:
        return 1.0 / (1.0 + np.exp(-self.logits(normalise(frame))))

    def predict(self, frame: pd.DataFrame) -> Floats:
        return self.calibrator.apply(self.raw(frame))

    def contributions(self, x: Floats) -> Floats:
        """Gradient of the logit with respect to each input, times the input: (rows, features)."""
        masks: list[Floats] = []
        h = x
        for i in range(0, len(self.weights) - 2, 2):
            pre = h @ self.weights[i].T + self.weights[i + 1]
            masks.append((pre > 0).astype(np.float64))
            h = np.maximum(pre, 0.0)
        grad = np.broadcast_to(self.weights[-2], (len(x), self.weights[-2].shape[1])).copy()
        for k in range(len(masks) - 1, -1, -1):
            grad = (grad * masks[k]) @ self.weights[2 * k]
        return np.asarray(grad * x, dtype=np.float64)

    def score(self, frame: pd.DataFrame) -> list[Scored]:
        probs = self.predict(frame)
        contribs = self.contributions(normalise(frame))
        return [Scored(float(p), level_of(float(p)), top_factors(row)) for p, row in zip(probs, contribs, strict=True)]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, Any] = {f"p{i}": w for i, w in enumerate(self.weights)}
        np.savez(directory / "weights.npz", **arrays)
        (directory / "calibrator.json").write_text(json.dumps(self.calibrator.to_json()), encoding="utf-8")
        (directory / "features.json").write_text(json.dumps(list(FEATURE_NAMES)), encoding="utf-8")

    @staticmethod
    def load(version: str = FED_VERSION, root: Path = MODELS_DIR) -> "FederatedMlp":
        d = root / version
        if not (d / "weights.npz").is_file():
            raise FileNotFoundError(f"No trained model {version} in {root}")
        if json.loads((d / "features.json").read_text(encoding="utf-8")) != list(FEATURE_NAMES):
            raise ValueError(f"Model {version} was trained with different features than this code builds")
        with np.load(d / "weights.npz", allow_pickle=False) as z:
            weights = [np.asarray(z[f"p{i}"], dtype=np.float64) for i in range(len(z.files))]
        return FederatedMlp(version, weights, Calibrator.from_json(json.loads((d / "calibrator.json").read_text(encoding="utf-8"))))
