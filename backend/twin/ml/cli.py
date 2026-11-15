"""`make train`: build the dataset from the simulation, train and evaluate the models, write the model card.

    python -m twin.ml.cli [--days 30] [--no-save]

Fails (exit 1) when a quality gate is missed: validation AUROC below 0.75, the model not beating NEWS2, or the
arrivals forecast not beating seasonal naive.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import asyncpg

from twin.common.config import REPO_ROOT, get_settings
from twin.common.logging import configure_logging
from twin.ml.card import model_card
from twin.ml.dataset import DEFAULT_DAYS, build_dataset
from twin.ml.forecast import FORECAST_VERSION, train_arrivals
from twin.ml.model import MODELS_DIR
from twin.ml.train import MODEL_VERSION, save_run, train_deterioration
from twin.sim.entities import PatientProfile

logger = logging.getLogger(__name__)
AUROC_GATE = 0.75


async def load_profiles(dsn: str) -> list[PatientProfile]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id, age, sex, comorbidity_count, conditions FROM patients ORDER BY id"
        )
    finally:
        await conn.close()
    return [
        PatientProfile(r["id"], r["age"], r["sex"], r["comorbidity_count"], tuple(r["conditions"]))
        for r in rows
    ]


def gate_failures(det: dict[str, object], arrivals: dict[str, object]) -> list[str]:
    """Human-readable list of the quality gates that were missed (empty when all pass)."""
    problems: list[str] = []
    val = det["validation"]
    if not isinstance(val, dict):
        raise TypeError("metrics.json has no validation section")
    model, base = val["model"], val["news2_baseline"]
    if model["auroc"] < AUROC_GATE:
        problems.append(f"validation AUROC {model['auroc']:.3f} is below {AUROC_GATE}")
    if model["auroc"] <= base["auroc"]:
        problems.append(f"model AUROC {model['auroc']:.3f} does not beat NEWS2 {base['auroc']:.3f}")
    fa = arrivals["validation"]
    if not isinstance(fa, dict):
        raise TypeError("forecast metrics have no validation section")
    if fa["mae"] >= fa["seasonal_naive_mae"]:
        problems.append(
            f"arrivals MAE {fa['mae']:.3f} does not beat seasonal naive {fa['seasonal_naive_mae']:.3f}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the Hospital Twin models")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--card", type=Path, default=REPO_ROOT / "docs" / "model_card.md")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    profiles = asyncio.run(load_profiles(settings.database_url.get_secret_value()))
    if not profiles:
        print("No Synthea patients in the database. Run `make seed` first.", file=sys.stderr)
        return 1
    dataset = build_dataset(profiles, settings.sim_seed, days=args.days)
    dataset.save(REPO_ROOT / "data" / "ml")
    result = train_deterioration(dataset.rows)
    forecast, forecast_metrics = train_arrivals(dataset.arrivals, dataset.unit_stats)
    save_run(result, dataset, args.models_dir / MODEL_VERSION)
    forecast.save(args.models_dir / FORECAST_VERSION)
    (args.models_dir / FORECAST_VERSION / "metrics.json").write_text(
        json.dumps(forecast_metrics, indent=1) + "\n", encoding="utf-8"
    )
    det = json.loads((args.models_dir / MODEL_VERSION / "metrics.json").read_text(encoding="utf-8"))
    args.card.parent.mkdir(parents=True, exist_ok=True)
    args.card.write_text(model_card(det, forecast_metrics), encoding="utf-8")

    v, t = det["validation"], det["test"]
    fa = forecast_metrics["validation"]
    print(
        f"Deterioration model {MODEL_VERSION}: {det['data']['rows']:,} rows, {det['data']['positives']:,} positive"
    )
    print(
        f"  validation AUROC {v['model']['auroc']:.3f} (NEWS2 {v['news2_baseline']['auroc']:.3f}), AUPRC {v['model']['auprc']:.3f} (NEWS2 {v['news2_baseline']['auprc']:.3f})"
    )
    print(
        f"  test       AUROC {t['model']['auroc']:.3f} (NEWS2 {t['news2_baseline']['auroc']:.3f}), Brier {t['model']['brier']:.4f} (NEWS2 {t['news2_baseline']['brier']:.4f})"
    )
    print(
        f"Arrivals forecast {FORECAST_VERSION}: MAE {fa['mae']:.3f} vs seasonal naive {fa['seasonal_naive_mae']:.3f} ({fa['improvement'] * 100:.0f}% better)"
    )
    print(f"Model card written to {args.card}")
    problems = gate_failures(det, forecast_metrics)
    for problem in problems:
        print(f"QUALITY GATE FAILED: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
