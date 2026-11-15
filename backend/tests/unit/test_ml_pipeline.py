"""The training pipeline end to end on a small seeded dataset, and its quality gates (PROMPT.md §7.2-7.3)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.sim_helpers import make_profiles
from twin.ml.card import model_card
from twin.ml.cli import AUROC_GATE, gate_failures
from twin.ml.dataset import HORIZON_MIN, Dataset, build_dataset
from twin.ml.features import FEATURE_NAMES
from twin.ml.forecast import (
    BED_UNITS,
    HORIZON_H,
    LAGS,
    ArrivalsModel,
    feature_row,
    hour_of_day,
    make_rows,
    project_capacity,
    train_arrivals,
)
from twin.ml.metrics import auroc_or_none, calibration_gap, evaluate
from twin.ml.model import HIGH, MEDIUM, Calibrator, DeteriorationModel, level_of, top_factors
from twin.ml.registry import list_models
from twin.ml.train import MODEL_VERSION, TrainResult, fairness, save_run, split_by_time, train_deterioration

SEED = 5
DAYS = 14


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return build_dataset(make_profiles(), SEED, days=DAYS, surges=2)


@pytest.fixture(scope="module")
def trained(dataset: Dataset) -> TrainResult:
    return train_deterioration(dataset.rows)


# ---- dataset -----------------------------------------------------------------------------------------------


def test_dataset_has_the_feature_schema_and_labels(dataset: Dataset) -> None:
    rows = dataset.rows
    assert list(rows.columns) == ["minute", "hospital", "patient_id", "encounter_id", *FEATURE_NAMES, "label"]
    assert len(rows) > 5000
    assert 0.005 < rows["label"].mean() < 0.15
    assert set(rows["hospital"]) == {"mercy", "stlukes", "desert"}
    assert (rows["minute"] % 30 == 0).all()  # one row per patient per 30 sim minutes
    assert rows.duplicated(["minute", "patient_id"]).sum() == 0
    assert HORIZON_MIN == 360


def test_dataset_is_deterministic_under_a_seed() -> None:
    a = build_dataset(make_profiles(), 3, days=4, surges=1)
    b = build_dataset(make_profiles(), 3, days=4, surges=1)
    pd.testing.assert_frame_equal(a.rows, b.rows)
    pd.testing.assert_frame_equal(a.arrivals, b.arrivals)
    c = build_dataset(make_profiles(), 4, days=4, surges=1)
    assert len(c.rows) != len(a.rows) or not a.rows.equals(c.rows)


def test_latent_severity_is_not_in_the_dataset(dataset: Dataset) -> None:
    assert not any(("sever" in c) or ("latent" in c) or c in ("mu", "s") for c in dataset.rows.columns)


def test_observer_features_do_not_change_when_the_hidden_state_changes() -> None:
    """The models only see charted vitals and public fields, never the physiology."""
    from datetime import timedelta

    from twin.ml.observe import Observer
    from twin.sim.engine import Simulation
    from twin.sim.layout_model import load_layout

    sim = Simulation(load_layout(), make_profiles(), 3, timedelta(hours=10))
    observer = Observer(sim.world)
    for _ in range(10 * 60):
        observer.feed(sim.tick())
    hospital, patient = next(
        (h, p) for h, p in observer.scorable() if p.id in observer.charts and observer.charts[p.id].readings
    )
    before = observer.features_for(hospital, patient, sim.world.now)
    assert before is not None
    assert patient.physiology is not None
    patient.physiology.s += 5.0
    patient.physiology.mu += 5.0
    assert observer.features_for(hospital, patient, sim.world.now) == before


def test_labels_mark_the_six_hours_before_a_critical_event(dataset: Dataset) -> None:
    from twin.ml.dataset import _label

    rows = pd.DataFrame({"minute": [0.0, 60.0, 300.0, 361.0, 480.0], "patient_id": ["P-1"] * 4 + ["P-2"]})
    labels = _label(rows, [(360.0, "P-1", 1)])
    assert labels.tolist() == [1, 1, 1, 0, 0]  # the window is (t, t + 6 h]: exactly 6 h counts, 361 is after
    assert dataset.rows["label"].sum() > 100


def test_hourly_arrivals_cover_every_hour_for_every_hospital(dataset: Dataset) -> None:
    a = dataset.arrivals
    assert len(a) == 3 * DAYS * 24
    assert a.groupby("hospital")["hour"].max().tolist() == [DAYS * 24 - 1] * 3
    assert a["arrivals"].sum() > 500
    assert a["scenario"].sum() > 0  # flu surges are flagged
    assert set(dataset.unit_stats) == set(BED_UNITS)
    assert all(
        v["admit_per_arrival"] >= 0 and v["departure_per_bed_hour"] > 0 for v in dataset.unit_stats.values()
    )


# ---- deterioration model -----------------------------------------------------------------------------------


def test_time_based_split_keeps_validation_after_training_and_test_after_validation(dataset: Dataset) -> None:
    s = split_by_time(dataset.rows)
    assert s.train["minute"].max() < s.val["minute"].min() <= s.val["minute"].max() < s.test["minute"].min()
    assert len(s.train) + len(s.val) + len(s.test) == len(dataset.rows)
    span = (
        dataset.rows["minute"].max() - dataset.rows["minute"].min()
    )  # the split is by sim time, not by row count
    assert s.train["minute"].max() == pytest.approx(0.6 * span, abs=30)
    assert s.val["minute"].max() == pytest.approx(0.8 * span, abs=30)


def test_quality_gates_on_the_seeded_dataset(trained: TrainResult) -> None:
    """Fails if validation AUROC < 0.75, or if the model does not beat NEWS2 alone."""
    val = trained.metrics["validation"]
    assert val["model"]["auroc"] >= AUROC_GATE
    assert val["model"]["auroc"] > val["news2_baseline"]["auroc"]
    test = trained.metrics["test"]
    assert test["model"]["auroc"] > test["news2_baseline"]["auroc"]
    assert test["model"]["auprc"] > test["news2_baseline"]["auprc"]


def test_metrics_include_auroc_auprc_brier_and_calibration_for_model_and_baseline(
    trained: TrainResult,
) -> None:
    for split in ("validation", "test"):
        for who in ("model", "news2_baseline"):
            m = trained.metrics[split][who]
            assert {"auroc", "auprc", "brier", "calibration", "n", "positive_rate"} <= set(m)
            assert 0.5 < m["auroc"] <= 1 and 0 <= m["brier"] < 0.25
            cal = m["calibration"]
            assert len(cal["mean_predicted"]) == len(cal["fraction_positive"]) >= 5
    assert next(iter(trained.metrics["feature_importance"])) in FEATURE_NAMES


def test_predictions_are_probabilities_and_calibrated_in_the_large(trained: TrainResult) -> None:
    p = trained.model.predict(trained.split.test)
    assert p.shape == (len(trained.split.test),)
    assert float(p.min()) >= 0.0 and float(p.max()) <= 1.0
    gap = calibration_gap(trained.split.test["label"].to_numpy(), p)
    assert abs(gap) < 0.02


def test_shap_output_has_the_right_shape_and_top_factors_are_named_and_signed(trained: TrainResult) -> None:
    frame = trained.split.test.head(20)
    values = trained.model.shap_values(frame)
    assert values.shape == (20, len(FEATURE_NAMES))
    scored = trained.model.score(frame)
    assert len(scored) == 20
    for s in scored:
        assert 0.0 <= s.score <= 1.0
        assert s.level == level_of(s.score)
        assert len(s.top_factors) == 3
        names = [n for n, _ in s.top_factors]
        assert len(set(names)) == 3
        assert all(
            isinstance(n, str) and n and n not in FEATURE_NAMES for n in names
        )  # readable, not column names
        assert all(-1.0 <= v <= 1.0 for _, v in s.top_factors)
        assert [abs(v) for _, v in s.top_factors] == sorted((abs(v) for _, v in s.top_factors), reverse=True)


def test_top_factors_picks_the_largest_contributions_with_their_signs() -> None:
    c = np.zeros(len(FEATURE_NAMES))
    c[FEATURE_NAMES.index("spo2")] = -2.0
    c[FEATURE_NAMES.index("hr")] = 1.0
    c[FEATURE_NAMES.index("age")] = 0.5
    c[FEATURE_NAMES.index("esi")] = 0.1
    assert top_factors(c) == [("SpO2", -0.556), ("Heart rate", 0.278), ("Age", 0.139)]
    assert top_factors(np.zeros(len(FEATURE_NAMES)))[0][1] == 0.0


def test_levels_follow_the_spec_thresholds() -> None:
    assert (HIGH, MEDIUM) == (0.70, 0.45)
    assert [level_of(x) for x in (0.0, 0.449, 0.45, 0.699, 0.70, 1.0)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
    ]


def test_model_files_round_trip(trained: TrainResult, tmp_path: Path) -> None:
    trained.model.save(tmp_path / "m")
    assert sorted(p.name for p in (tmp_path / "m").iterdir()) == [
        "calibrator.json",
        "features.json",
        "model.txt",
    ]
    loaded = DeteriorationModel.load("m", tmp_path)
    frame = trained.split.test.head(50)
    np.testing.assert_allclose(loaded.predict(frame), trained.model.predict(frame))
    (tmp_path / "m" / "features.json").write_text(json.dumps(["hr"]), encoding="utf-8")
    with pytest.raises(ValueError, match="different features"):
        DeteriorationModel.load("m", tmp_path)
    with pytest.raises(FileNotFoundError):
        DeteriorationModel.load("nope", tmp_path)


def test_calibrator_clips_and_interpolates() -> None:
    cal = Calibrator(x=[0.0, 0.5, 1.0], y=[0.0, 0.2, 1.0])
    np.testing.assert_allclose(cal.apply(np.array([-1.0, 0.25, 2.0])), [0.0, 0.1, 1.0])
    assert Calibrator.from_json(cal.to_json()) == cal


def test_fairness_reports_age_bands_and_sex(trained: TrainResult) -> None:
    f = trained.metrics["fairness"]
    assert {"age 18-39", "age 40-64", "age 65+", "male", "female"} == set(f["groups"])
    assert f["max_auroc_gap"] >= 0
    assert sum(g["n"] for k, g in f["groups"].items() if k.startswith("age")) == len(trained.split.test)
    again = fairness(trained.split.test, trained.model.predict(trained.split.test))
    assert again == f


def test_training_needs_both_classes_in_every_split() -> None:
    rows = pd.DataFrame({"minute": np.arange(100.0), "label": 0, **dict.fromkeys(FEATURE_NAMES, 1.0)})
    with pytest.raises(ValueError, match="no positive and negative rows"):
        train_deterioration(rows)


def test_metric_helpers() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.4, 0.35, 0.8])
    assert evaluate(y, p, bins=2)["auroc"] == 0.75
    with pytest.raises(ValueError, match="Both classes"):
        evaluate(np.zeros(4, dtype=int), p)
    assert auroc_or_none(y, p) is None  # too few rows
    assert auroc_or_none(np.zeros(100, dtype=int), np.zeros(100)) is None


def test_saved_run_has_metrics_and_the_registry_lists_it(
    trained: TrainResult, dataset: Dataset, tmp_path: Path
) -> None:
    save_run(trained, dataset, tmp_path / MODEL_VERSION)
    saved = json.loads((tmp_path / MODEL_VERSION / "metrics.json").read_text(encoding="utf-8"))
    assert saved["version"] == MODEL_VERSION
    assert saved["data"]["days"] == DAYS and saved["data"]["seed"] == SEED
    assert saved["validation"]["model"]["auroc"] == trained.metrics["validation"]["model"]["auroc"]
    models = list_models(tmp_path)
    assert [m["version"] for m in models] == [MODEL_VERSION]
    assert models[0]["kind"] == "deterioration"
    assert list_models(tmp_path / "missing") == []


# ---- arrivals forecast and capacity ------------------------------------------------------------------------


def test_arrivals_forecast_beats_seasonal_naive_on_validation(dataset: Dataset) -> None:
    model, metrics = train_arrivals(dataset.arrivals, dataset.unit_stats)
    v = metrics["validation"]
    assert v["mae"] < v["seasonal_naive_mae"]
    assert 0 < v["improvement"] < 1
    assert set(v["by_horizon"]) == {str(h) for h in range(1, HORIZON_H + 1)}
    history = np.full(LAGS, 1.0)
    out = model.forecast("mercy", history, 30, 0)
    assert len(out) == HORIZON_H and all(x >= 0 for x in out)
    with pytest.raises(ValueError, match="Need 24"):
        model.forecast("mercy", np.ones(5), 30, 0)


def test_arrivals_model_round_trips(dataset: Dataset, tmp_path: Path) -> None:
    model, _ = train_arrivals(dataset.arrivals, dataset.unit_stats, "arr-test")
    model.save(tmp_path / "arr-test")
    loaded = ArrivalsModel.load("arr-test", tmp_path)
    history = np.arange(LAGS, dtype=float) % 3
    assert loaded.forecast("desert", history, 50, 1) == model.forecast("desert", history, 50, 1)
    assert loaded.unit_stats == model.unit_stats


def test_forecast_rows_use_only_the_past(dataset: Dataset) -> None:
    rows = make_rows(dataset.arrivals)
    row = rows.iloc[100]
    part = dataset.arrivals[
        dataset.arrivals["hospital"] == ["mercy", "stlukes", "desert"][int(row["hospital"])]
    ].sort_values("hour")
    counts = part["arrivals"].to_numpy(dtype=float)
    t = int(row["hour"])
    assert row["lag_0"] == counts[t] and row["lag_1"] == counts[t - 1]
    assert row["target"] == counts[t + int(row["horizon"])]
    rebuilt = feature_row(
        ["mercy", "stlukes", "desert"][int(row["hospital"])],
        counts[: t + 1],
        t,
        int(row["scenario"]),
        int(row["horizon"]),
    )
    assert all(rebuilt[k] == row[k] for k in rebuilt)
    assert hour_of_day(0) == 8 and hour_of_day(16) == 0


def test_capacity_projection_is_free_beds_over_net_inflow() -> None:
    stats = {u: {"admit_per_arrival": 0.5, "departure_per_bed_hour": 0.1} for u in BED_UNITS}
    capacity = {"ER": 6, "WARD": 14, "ICU": 6, "REC": 3}
    occ = {"ER": 6, "WARD": 10, "ICU": 5, "REC": 0}
    out = project_capacity([4.0] * 6, occ, capacity, stats)
    assert out["ER"] == 0.0  # already full
    assert out["WARD"] == pytest.approx(4 / (4.0 * 0.5 - 10 * 0.1))  # 4 free beds, net +1/h
    assert out["ICU"] == pytest.approx(1 / (2.0 - 0.5))
    assert out["REC"] == pytest.approx(3 / 2.0)
    quiet = project_capacity([0.0] * 6, occ, capacity, stats)
    assert quiet["WARD"] is None and quiet["ICU"] is None  # more leave than arrive: never full
    slow = project_capacity([0.25] * 6, {"ER": 0, "WARD": 0, "ICU": 0, "REC": 0}, capacity, stats)
    assert slow["WARD"] is None  # fills in more than 24 h


def test_projection_changes_when_discharge_predictions_change() -> None:
    """The hook CP7 uses: expected discharges can come from length-of-stay predictions."""
    stats = {u: {"admit_per_arrival": 0.5, "departure_per_bed_hour": 0.1} for u in BED_UNITS}
    capacity = {"ER": 6, "WARD": 14, "ICU": 6, "REC": 3}
    occ = {"ER": 2, "WARD": 10, "ICU": 4, "REC": 1}
    base = project_capacity([4.0] * 6, occ, capacity, stats)
    slower = project_capacity([4.0] * 6, occ, capacity, stats, discharge_rate={"WARD": 0.2})
    assert base["WARD"] != slower["WARD"]
    assert slower["WARD"] is not None and base["WARD"] is not None and slower["WARD"] < base["WARD"]


# ---- the training command ----------------------------------------------------------------------------------


def test_gate_failures_name_each_missed_gate(trained: TrainResult, dataset: Dataset) -> None:
    _, fm = train_arrivals(dataset.arrivals, dataset.unit_stats)
    assert gate_failures(trained.metrics, fm) == []
    bad = json.loads(json.dumps(trained.metrics))
    bad["validation"]["model"]["auroc"] = 0.6
    bad["validation"]["news2_baseline"]["auroc"] = 0.7
    worse = json.loads(json.dumps(fm))
    worse["validation"]["mae"] = worse["validation"]["seasonal_naive_mae"] + 0.1
    problems = gate_failures(bad, worse)
    assert any("below 0.75" in p for p in problems)
    assert any("NEWS2" in p for p in problems)
    assert any("seasonal naive" in p for p in problems)
    with pytest.raises(TypeError):
        gate_failures({"validation": 1}, fm)
    with pytest.raises(TypeError):
        gate_failures(trained.metrics, {"validation": 1})


def test_model_card_lists_data_features_metrics_fairness_and_limits(
    trained: TrainResult, dataset: Dataset, tmp_path: Path
) -> None:
    save_run(trained, dataset, tmp_path / MODEL_VERSION)
    det = json.loads((tmp_path / MODEL_VERSION / "metrics.json").read_text(encoding="utf-8"))
    _, fm = train_arrivals(dataset.arrivals, dataset.unit_stats)
    card = model_card(det, fm)
    for heading in (
        "## Deterioration model",
        "### Features",
        "### Metrics against NEWS2 alone",
        "### Fairness",
        "## Arrivals forecast",
        "## Limits",
    ):
        assert heading in card
    assert "NEWS2" in card and "AUROC" in card and "age 65+" in card and "Not for clinical use" in card
    assert f"{det['data']['rows']:,}" in card
    for name in FEATURE_NAMES:
        assert f"`{name}`" in card
