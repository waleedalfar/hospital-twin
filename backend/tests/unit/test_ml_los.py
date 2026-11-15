"""The length-of-stay model and its use in the capacity projection (PROMPT.md §7.5)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tests.agent_helpers import patient
from tests.sim_helpers import make_profiles
from twin.agent.summary import build_summary
from twin.common.ws import LosEvent
from twin.ml.cli import gate_failures
from twin.ml.dataset import Dataset, build_dataset
from twin.ml.forecast import project_capacity, train_arrivals
from twin.ml.inference import LOS_EVERY_MIN, InferenceEngine
from twin.ml.los import (
    LOS_FEATURES,
    LOS_UNITS,
    MIN_IMPROVEMENT,
    LosBaseline,
    LosModel,
    bucket_of,
    discharge_rates,
    fit_baseline,
    los_rows,
    train_los,
)
from twin.ml.registry import list_models
from twin.ml.train import train_deterioration
from twin.sim.engine import Simulation
from twin.sim.layout_model import load_layout


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return build_dataset(make_profiles(), 5, days=18, surges=1)


@pytest.fixture(scope="module")
def trained(dataset: Dataset) -> tuple[LosModel, dict[str, object], object]:
    det = train_deterioration(dataset.rows).model
    model, metrics = train_los(dataset.rows, det)
    return model, metrics, det


def test_buckets_cap_at_the_last_one() -> None:
    assert [bucket_of(h) for h in (-1, 0, 5.9, 6, 100, 1000)] == [0, 0, 0, 1, 12, 12]


def test_the_baseline_is_the_median_by_unit_and_bucket_with_fallbacks() -> None:
    rows = pd.DataFrame(
        {
            "unit": [1.0] * 10 + [2.0] * 3,
            "hours_since_admission": [1.0] * 5 + [8.0] * 5 + [1.0] * 3,
            "remaining_h": [10, 20, 30, 40, 50, 5, 5, 5, 5, 5, 99, 99, 99],
        }
    )
    base = fit_baseline(rows)
    assert base.predict(1, 2.0) == 30.0 and base.predict(1, 9.0) == 5.0
    assert base.predict(2, 2.0) == 99.0  # too few rows for the cell, so the unit median
    assert base.predict(3, 2.0) == base.overall  # unknown unit
    assert LosBaseline.from_json(base.to_json()) == base


def test_training_rows_are_finished_stays_in_a_bed_with_a_risk_score(dataset: Dataset, trained: tuple[LosModel, dict[str, object], object]) -> None:
    rows = los_rows(dataset.rows, trained[2])  # type: ignore[arg-type]
    assert len(rows) > 1000
    assert set(rows["unit"]) <= set(LOS_UNITS)
    assert (rows["remaining_h"] > 0).all() and rows["exit_minute"].notna().all()
    assert rows["risk"].between(0, 1).all()
    assert set(LOS_FEATURES) <= set(rows.columns)
    waiting_or_theatre = dataset.rows[~dataset.rows["unit"].isin(LOS_UNITS)]
    assert len(waiting_or_theatre) > 0  # they exist in the data but are not used here


def test_the_model_beats_the_baseline_by_the_gate_on_validation(trained: tuple[LosModel, dict[str, object], object]) -> None:
    _, metrics, _ = trained
    v = metrics["validation"]
    assert isinstance(v, dict)
    assert v["improvement"] >= MIN_IMPROVEMENT, f"validation MAE {v['mae']:.2f} h vs baseline {v['baseline_mae']:.2f} h"
    assert v["mae"] < v["baseline_mae"]
    assert metrics["test"] is not None and metrics["features"] == list(LOS_FEATURES)
    assert set(metrics["rows"]) == {"train", "validation", "test"}  # type: ignore[call-overload]


def test_predictions_are_positive_hours_and_survive_saving(
    tmp_path: Path, trained: tuple[LosModel, dict[str, object], object], dataset: Dataset
) -> None:
    model, _, det = trained
    rows = los_rows(dataset.rows, det).head(200)  # type: ignore[arg-type]
    before = model.predict(rows)
    assert (before >= 0.25).all() and (before <= 24 * 14).all()
    model.save(tmp_path / "los")
    after = LosModel.load("los", tmp_path).predict(rows)
    assert np.allclose(before, after)
    with pytest.raises(FileNotFoundError, match="No trained model"):
        LosModel.load("missing", tmp_path)


def test_too_few_finished_stays_is_an_error_not_a_weak_model(dataset: Dataset, trained: tuple[LosModel, dict[str, object], object]) -> None:
    with pytest.raises(ValueError, match="Not enough finished stays"):
        train_los(dataset.rows.head(300), trained[2])  # type: ignore[arg-type]


def test_a_missed_gate_is_reported() -> None:
    det: dict[str, Any] = {"validation": {"model": {"auroc": 0.9}, "news2_baseline": {"auroc": 0.8}}}
    arrivals: dict[str, Any] = {"validation": {"mae": 0.5, "seasonal_naive_mae": 1.0}}
    good: dict[str, Any] = {"validation": {"improvement": 0.15, "mae": 8.5, "baseline_mae": 10.0}}
    poor: dict[str, Any] = {"validation": {"improvement": 0.04, "mae": 9.6, "baseline_mae": 10.0}}
    assert gate_failures(det, arrivals, good) == []
    problems = gate_failures(det, arrivals, poor)
    assert len(problems) == 1 and "length-of-stay" in problems[0] and "4.0%" in problems[0]
    with pytest.raises(TypeError, match="length-of-stay"):
        gate_failures(det, arrivals, {"validation": 3})


def test_discharge_rates_count_patients_leaving_within_the_window() -> None:
    assert discharge_rates({"WARD": [1.0, 5.0, 6.0, 7.0, 40.0], "ICU": [30.0]}) == {"WARD": 0.5, "ICU": 0.0}
    assert discharge_rates({"WARD": [2.0, 3.0]}, window_h=2.0) == {"WARD": 0.5}


def test_the_projection_uses_los_discharges_when_given() -> None:
    cap = {"ER": 6, "WARD": 14, "ICU": 6, "REC": 3}
    occupancy = {"ER": 3, "WARD": 10, "ICU": 4, "REC": 1}
    stats = {u: {"admit_per_arrival": 0.3, "departure_per_bed_hour": 0.05} for u in cap}
    forecast = [6.0] * 6
    historical = project_capacity(forecast, occupancy, cap, stats)
    slow = project_capacity(forecast, occupancy, cap, stats, dict.fromkeys(cap, 0.0))
    fast = project_capacity(forecast, occupancy, cap, stats, dict.fromkeys(cap, 5.0))
    assert slow["WARD"] is not None and slow["WARD"] == pytest.approx(4 / 1.8)
    assert fast["WARD"] is None  # everyone leaves faster than they arrive
    assert historical["WARD"] != slow["WARD"]


# ---- in the running simulation ---------------------------------------------------------------------------------


def make_sim(trained: tuple[LosModel, dict[str, object], object], dataset: Dataset, seed: int = 9, hours: int = 3) -> Simulation:
    model, _, det = trained
    arrivals, _ = train_arrivals(dataset.arrivals, dataset.unit_stats)
    sim = Simulation(load_layout(), make_profiles(), seed, timedelta(hours=12))
    sim.attach_ml(InferenceEngine(sim.world, det, arrivals, None, model))  # type: ignore[arg-type]
    sim.run_until(sim.visible_start + timedelta(hours=hours))
    return sim


def test_admitted_patients_get_a_prediction_every_15_minutes(trained: tuple[LosModel, dict[str, object], object], dataset: Dataset) -> None:
    sim = make_sim(trained, dataset)
    ml = sim.ml
    assert ml is not None and ml.los_model is not None
    seen: dict[str, float] = {}
    minutes: set[int] = set()
    for _ in range(60):
        for item in sim.tick():
            if isinstance(item.event, LosEvent):
                seen[item.event.patient_id] = item.event.hours
                minutes.add(round(sim.world.minutes(item.event.time)))
                assert item.event.model_version == ml.los_model.version and item.event.hours >= 0.25
    assert seen and all(m % LOS_EVERY_MIN == 0 for m in minutes) and len(minutes) == 60 // LOS_EVERY_MIN
    snap = sim.snapshot("mercy", 1, False, False)
    with_prediction = [e for e in snap.entities if e.kind == "patient" and e.expected_discharge_h is not None]
    assert with_prediction
    for e in with_prediction:
        assert e.location.bed is not None  # only patients in a bed are predicted
    assert set(ml.remaining) <= {"mercy", "stlukes", "desert"}


def test_the_capacity_projection_changes_when_the_los_predictions_change(
    trained: tuple[LosModel, dict[str, object], object], dataset: Dataset
) -> None:
    sim = make_sim(trained, dataset)
    ml = sim.ml
    assert ml is not None and ml.los_model is not None

    def hours_until_full(scale: float) -> dict[str, float]:
        original = ml.los_model.predict  # type: ignore[union-attr]
        ml.los_model.predict = lambda frame: original(frame) * scale  # type: ignore[union-attr,method-assign]
        try:
            ml.predict_stays()
            ml.drain_forecasts()
            ml.forecast_all()
        finally:
            ml.los_model.predict = original  # type: ignore[union-attr,method-assign]
        return {r.metric: r.value for r in ml.drain_forecasts() if r.hospital_id == "mercy" and r.metric.startswith("hours_until_full")}

    quick, slow = hours_until_full(0.05), hours_until_full(20.0)
    assert quick != slow
    # when everybody is expected to leave soon units fill later than when nobody is
    assert all(quick[k] >= slow[k] for k in quick) and any(quick[k] > slow[k] for k in quick)


def test_without_a_los_model_nothing_is_predicted(dataset: Dataset, trained: tuple[LosModel, dict[str, object], object]) -> None:
    det = trained[2]
    sim = Simulation(load_layout(), make_profiles(), 9, timedelta(hours=12))
    sim.attach_ml(InferenceEngine(sim.world, det))  # type: ignore[arg-type]
    sim.run_until(sim.visible_start + timedelta(hours=1))
    assert all(e.expected_discharge_h is None for e in sim.snapshot("mercy", 1, False, False).entities)
    assert sim.ml is not None and sim.ml.remaining == {}


def test_the_agent_prefers_low_risk_patients_who_are_expected_home_soonest(
    trained: tuple[LosModel, dict[str, object], object], dataset: Dataset
) -> None:
    sim = make_sim(trained, dataset, hours=14)
    hospital = sim.world.hospitals["mercy"]
    ward = [p for p in hospital.patients() if p.phase == "inpatient" and p.unit in ("WARD", "REC") and p.risk is not None and p.risk.level == "low"]
    assert len(ward) >= 3
    for i, p in enumerate(sorted(ward, key=lambda x: x.id)):
        p.expected_discharge_h = 40.0 - i  # the last one is expected home first
    summary = build_summary(sim.world, sim.ml, "mercy")
    order = [p.expected_discharge_h for p in summary.expedite_candidates]
    assert order == sorted(order, key=lambda x: float("inf") if x is None else x)
    assert summary.expedite_candidates[0].expected_discharge_h == min(p.expected_discharge_h for p in ward if p.expected_discharge_h is not None)


def test_the_registry_labels_the_length_of_stay_model(tmp_path: Path, trained: tuple[LosModel, dict[str, object], object]) -> None:
    import json

    model, metrics, _ = trained
    model.save(tmp_path / model.version)
    (tmp_path / model.version / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    assert [(m["version"], m["kind"]) for m in list_models(tmp_path)] == [(model.version, "length_of_stay")]
    assert patient("P-1").id == "P-1"
