"""Evaluation metrics (PROMPT.md §7.2): AUROC, AUPRC, Brier score and a calibration curve."""

from typing import Any

import numpy as np
import numpy.typing as npt
from sklearn.calibration import calibration_curve
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

Floats = npt.NDArray[np.float64]
Ints = npt.NDArray[np.int_]

AGE_BANDS: tuple[tuple[str, int, int], ...] = (("18-39", 18, 39), ("40-64", 40, 64), ("65+", 65, 200))


def evaluate(y_true: Ints, y_prob: Floats, bins: int = 10) -> dict[str, Any]:
    """AUROC, AUPRC, Brier score and the calibration curve for predicted probabilities `y_prob`."""
    if len(set(y_true.tolist())) < 2:
        raise ValueError("Both classes are needed to compute AUROC")
    frac, mean_pred = calibration_curve(y_true, y_prob, n_bins=bins, strategy="quantile")
    return {
        "auroc": float(roc_auc_score(y_true, y_prob)),
        "auprc": float(average_precision_score(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob)),
        "positive_rate": float(np.mean(y_true)),
        "n": len(y_true),
        "calibration": {
            "mean_predicted": [float(x) for x in mean_pred],
            "fraction_positive": [float(x) for x in frac],
        },
    }


def auroc_or_none(y_true: Ints, y_prob: Floats) -> float | None:
    """AUROC, or None for a group that has only one class (too small to say anything)."""
    if len(y_true) < 50 or len(set(y_true.tolist())) < 2:
        return None
    return float(roc_auc_score(y_true, y_prob))


def calibration_gap(y_true: Ints, y_prob: Floats) -> float:
    """Mean predicted risk minus the observed rate (0 is perfectly calibrated in the large)."""
    return float(np.mean(y_prob) - np.mean(y_true))
