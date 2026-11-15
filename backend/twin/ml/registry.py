"""Lists the trained models under `models/` with their metrics (`GET /models`)."""

import json
from datetime import UTC, datetime
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
        trained_at = datetime.fromtimestamp(metrics_file.stat().st_mtime, UTC).isoformat()
        out.append({"version": directory.name, "kind": kind, "metrics": metrics, "trained_at": trained_at})
    return out


def validation_auroc(version: str, root: Path = MODELS_DIR) -> float | None:
    """The validation AUROC a deterioration model was saved with, or None if it has none."""
    path = root / version / "metrics.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8")).get("validation", {}).get("model", {}).get("auroc")
    return float(value) if isinstance(value, int | float) else None


def deterioration_versions(root: Path = MODELS_DIR) -> list[str]:
    """Versions that can score patients right now: the LightGBM model and, if trained, the federated MLP."""
    return [
        m["version"]
        for m in list_models(root)
        if m["kind"] == "deterioration" and ((root / m["version"] / "model.txt").is_file() or (root / m["version"] / "weights.npz").is_file())
    ]
