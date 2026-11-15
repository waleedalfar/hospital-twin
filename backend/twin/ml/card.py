"""Writes `docs/model_card.md` from the saved metrics (PROMPT.md §7.2)."""

from datetime import date
from typing import Any

from twin.ml.features import FEATURES


def _fmt(value: float | None, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def _row(name: str, m: dict[str, Any], b: dict[str, Any]) -> str:
    return f"| {name} | {m['auroc']:.3f} | {b['auroc']:.3f} | {m['auprc']:.3f} | {b['auprc']:.3f} | {m['brier']:.4f} | {b['brier']:.4f} |"


def model_card(det: dict[str, Any], arrivals: dict[str, Any]) -> str:
    """Markdown model card for the deterioration model and the arrivals forecast."""
    data = det["data"]
    val, test = det["validation"], det["test"]
    fair = det["fairness"]
    fa = arrivals["validation"]
    lines = [
        "# Model card: Hospital Twin deterioration and arrivals models",
        "",
        f"Generated {date.today().isoformat()} by `make train`. All data is simulated; no real patient data was used.",
        "",
        "## Deterioration model (`" + det["version"] + "`)",
        "",
        "**Task.** For every patient who is waiting or admitted, every 30 sim minutes: the probability of a",
        "critical event (escalation to ICU or rapid response) within the next 6 sim hours.",
        "",
        "**Data.** The simulation run headless with seed "
        f"{data['seed']} for {data['days']} sim days across three hospitals: {data['rows']:,} patient-snapshots,",
        f"{data['positives']:,} positive. Patients are drawn from Synthea records (Phoenix, Arizona) for age, sex and",
        "comorbidities. Vitals, deterioration and critical events come from the simulator's hidden severity process,",
        "which the model never sees. Flu surges cover about 1% of the time.",
        "",
        "**Split.** By time: first 60% train, next 20% validation (early stopping and calibration), last 20% test.",
        f"Rows: train {det['split']['train']['rows']:,}, validation {det['split']['validation']['rows']:,}, test {det['split']['test']['rows']:,}.",
        "",
        "**Model.** LightGBM gradient-boosted trees, isotonic calibration, SHAP TreeExplainer for the top three",
        "factors of each prediction. Levels: high at 0.70 or more, medium at 0.45 or more, otherwise low.",
        "",
        "### Features",
        "",
        "| Feature | Meaning |",
        "| --- | --- |",
        *[f"| `{name}` | {readable} |" for name, readable in FEATURES],
        "",
        "No latent severity and no future information is used; a test builds features at time t from a history with",
        "future readings added and checks nothing changes.",
        "",
        "### Metrics against NEWS2 alone",
        "",
        "NEWS2 (calibrated the same way) is the baseline.",
        "",
        "| Split | AUROC model | AUROC NEWS2 | AUPRC model | AUPRC NEWS2 | Brier model | Brier NEWS2 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        _row("validation", val["model"], val["news2_baseline"]),
        _row("test", test["model"], test["news2_baseline"]),
        "",
        f"Positive rate on the test split: {test['model']['positive_rate']:.3f}. The calibration curve is in `models/{det['version']}/metrics.json`.",
        "",
        "### Fairness on the test split",
        "",
        "| Group | Rows | Positives | AUROC | Calibration gap |",
        "| --- | --- | --- | --- | --- |",
        *[
            f"| {name} | {g['n']} | {g['positives']} | {_fmt(g['auroc'], '.3f')} | {_fmt(g['calibration_gap'], '+.4f')} |"
            for name, g in fair["groups"].items()
        ],
        "",
        f"Largest AUROC gap between groups: {fair['max_auroc_gap']:.3f} (gaps above 0.05 are flagged in the governance panel).",
        "",
        "## Arrivals forecast (`" + arrivals["version"] + "`)",
        "",
        "LightGBM regression on hourly arrivals per hospital for the next 6 hours, from hour of day, day of week, the",
        "last 24 hourly counts, rolling means and an active-scenario flag.",
        "",
        "| | MAE (arrivals per hour) |",
        "| --- | --- |",
        f"| Model | {fa['mae']:.3f} |",
        f"| Seasonal naive (same hour yesterday) | {fa['seasonal_naive_mae']:.3f} |",
        "",
        f"The model is {fa['improvement'] * 100:.0f}% more accurate than the baseline on {fa['rows']:,} validation rows.",
        "",
        "## Limits",
        "",
        "- Everything is learned from a simulator. The labels follow the simulator's own deterioration rules, so the",
        "  scores say how well the pipeline works, not how well it would work on real patients.",
        "- The simulation has no weekday effect, so the day-of-week feature carries no signal.",
        "- Consciousness and supplemental oxygen are not simulated; NEWS2 assumes alert and room air.",
        "- Critical events are rare (about 2% of snapshots); the 0.70 high-risk threshold is rarely reached, which is",
        "  intended for a demo where alerts should be meaningful.",
        "- Not for clinical use.",
        "",
    ]
    return "\n".join(lines)
