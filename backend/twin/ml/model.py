"""The deterioration model: a LightGBM classifier with isotonic calibration, SHAP explanations and levels
(PROMPT.md §7.2). Models are plain files (text and JSON), no pickles."""

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap

from twin.common.config import REPO_ROOT
from twin.ml.features import FEATURE_NAMES, READABLE
from twin.ml.metrics import Floats

MODELS_DIR = REPO_ROOT / "models"
HIGH = 0.70
MEDIUM = 0.45
TOP_FACTORS = 3


def level_of(score: float) -> str:
    """high >= 0.70, medium >= 0.45, else low."""
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


@dataclass
class Calibrator:
    """Isotonic regression stored as its fitted points; applied by linear interpolation."""

    x: list[float]
    y: list[float]

    def apply(self, raw: Floats) -> Floats:
        return np.clip(np.interp(raw, self.x, self.y), 0.0, 1.0).astype(np.float64)

    def to_json(self) -> dict[str, list[float]]:
        return {"x": self.x, "y": self.y}

    @staticmethod
    def from_json(data: dict[str, list[float]]) -> "Calibrator":
        return Calibrator(x=[float(v) for v in data["x"]], y=[float(v) for v in data["y"]])


@dataclass
class Scored:
    score: float
    level: str
    top_factors: list[tuple[str, float]]


class RiskModel(Protocol):
    """What live inference needs from a deterioration model: LightGBM and the federated MLP both provide it."""

    version: str

    def score(self, frame: pd.DataFrame) -> list[Scored]: ...


class DeteriorationModel:
    def __init__(self, version: str, booster: lgb.Booster, calibrator: Calibrator) -> None:
        self.version = version
        self.booster = booster
        self.calibrator = calibrator
        self._explainer: Any = None

    # ---- persistence ----------------------------------------------------------------------------------

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(directory / "model.txt"))
        (directory / "calibrator.json").write_text(json.dumps(self.calibrator.to_json()), encoding="utf-8")
        (directory / "features.json").write_text(json.dumps(list(FEATURE_NAMES)), encoding="utf-8")

    @staticmethod
    def load(version: str, root: Path = MODELS_DIR) -> "DeteriorationModel":
        directory = root / version
        if not (directory / "model.txt").is_file():
            raise FileNotFoundError(f"No trained model {version} in {root}")
        booster = lgb.Booster(model_file=str(directory / "model.txt"))
        names = json.loads((directory / "features.json").read_text(encoding="utf-8"))
        if names != list(FEATURE_NAMES):
            raise ValueError(f"Model {version} was trained with different features than this code builds")
        calibrator = Calibrator.from_json(json.loads((directory / "calibrator.json").read_text(encoding="utf-8")))
        return DeteriorationModel(version, booster, calibrator)

    # ---- prediction -----------------------------------------------------------------------------------

    def raw(self, frame: pd.DataFrame) -> Floats:
        return np.asarray(self.booster.predict(frame[list(FEATURE_NAMES)]), dtype=np.float64)

    def predict(self, frame: pd.DataFrame) -> Floats:
        """Calibrated probabilities of a critical event within 6 sim hours, one per row, in [0, 1]."""
        return self.calibrator.apply(self.raw(frame))

    def shap_values(self, frame: pd.DataFrame) -> Floats:
        """SHAP contributions, shape (rows, features), in the model's log-odds space."""
        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self.booster)
        with warnings.catch_warnings():
            # SHAP warns on every call that LightGBM binary models return a list; handled just below.
            warnings.filterwarnings("ignore", message="LightGBM binary classifier with TreeExplainer")
            values = self._explainer.shap_values(frame[list(FEATURE_NAMES)])
        if isinstance(values, list):  # older SHAP versions return one array per class
            values = values[-1]
        return np.asarray(values, dtype=np.float64)

    def score(self, frame: pd.DataFrame) -> list[Scored]:
        """Score rows: calibrated probability, level and the top 3 factors with signed contributions."""
        probs = self.predict(frame)
        contributions = self.shap_values(frame)
        out: list[Scored] = []
        for p, row in zip(probs, contributions, strict=True):
            out.append(Scored(float(p), level_of(float(p)), top_factors(row)))
        return out


def top_factors(contributions: Floats, count: int = TOP_FACTORS) -> list[tuple[str, float]]:
    """The `count` features that moved this prediction most: (readable name, signed share).

    SHAP values are in log-odds, where a single factor can be 3.0. The share is each contribution divided by
    the sum of all absolute contributions, so it is between -1 and 1, positive when the factor raises the
    risk, and the shares of all features add up (in absolute value) to 1."""
    total = float(np.sum(np.abs(contributions))) or 1.0
    order = np.argsort(-np.abs(contributions))[:count]
    return [(READABLE[FEATURE_NAMES[int(i)]], round(float(contributions[int(i)]) / total, 3)) for i in order]
