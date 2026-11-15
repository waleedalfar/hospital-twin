"""Lists the trained models under `models/` with their metrics (`GET /models`)."""

import json
from pathlib import Path
from typing import Any

from twin.ml.model import MODELS_DIR


def list_models(root: Path = MODELS_DIR) -> list[dict[str, Any]]:
    """One entry per model directory that has a metrics.json, sorted by name."""
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        metrics_file = directory / "metrics.json"
        if not metrics_file.is_file():
            continue
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        validation = json.dumps(metrics.get("validation", {}))
        kind = "arrivals_forecast" if "seasonal_naive_mae" in validation else "length_of_stay" if "baseline_mae" in validation else "deterioration"
        out.append({"version": directory.name, "kind": kind, "metrics": metrics})
    return out
