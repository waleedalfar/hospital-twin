"""Drift, fairness and audit rows (PROMPT.md §8)."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.sim_helpers import make_profiles
from twin.ml.dataset import build_dataset
from twin.ml.features import FEATURE_NAMES
from twin.ml.forecast import train_arrivals
from twin.ml.governance import (
    DRIFT_WINDOW_MIN,
    FAIRNESS_GAP,
    MIN_DRIFT_SAMPLES,
    PSI_ALERT,
    RESPIRATORY_FEATURES,
    DriftMonitor,
    FairnessMonitor,
    FeatureBaseline,
    ScoredRow,
    load_baseline,
    make_baseline,
    make_baselines,
    psi,
    raw_psi,
    save_baseline,
)
from twin.ml.inference import InferenceEngine
from twin.ml.train import train_deterioration
from twin.sim.engine import Simulation
from twin.sim.layout_model import load_layout


def frame(seed: int = 0, n: int = 4000, shift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {name: rng.normal(shift, 1.0, n) for name in FEATURE_NAMES}
    data["hospital"] = rng.choice(["a", "b"], n).tolist()
    return pd.DataFrame(data)


def test_a_baseline_has_proportions_that_sum_to_one_and_ignores_missing_values() -> None:
    df = frame()
    df.loc[:100, "age"] = np.nan
    base = make_baseline(df)
    assert set(base) == set(FEATURE_NAMES)
    for b in base.values():
        assert abs(sum(b.proportions) - 1) < 1e-9 and len(b.proportions) == len(b.edges) + 1
        assert b.edges == sorted(b.edges)


def test_psi_is_near_zero_for_the_same_distribution_and_large_for_a_shift() -> None:
    base = make_baseline(frame(0))["hr"]
    same = frame(1, 500)["hr"].to_numpy()
    shifted = frame(2, 500, shift=1.5)["hr"].to_numpy()
    assert (psi(base, same) or 0.0) < 0.05
    assert (psi(base, shifted) or 0.0) > PSI_ALERT
    assert raw_psi(base, same) >= 0


def test_psi_needs_enough_values_and_ignores_nan() -> None:
    base = make_baseline(frame())["hr"]
    assert psi(base, np.full(MIN_DRIFT_SAMPLES - 1, 0.0)) is None
    values = np.concatenate([np.zeros(MIN_DRIFT_SAMPLES), np.full(50, np.nan)])
    assert psi(base, values) is not None


def test_bias_correction_subtracts_the_expected_noise_but_never_goes_below_zero() -> None:
    base = FeatureBaseline([0.0], [0.5, 0.5])
    values = np.array([-1.0] * 15 + [1.0] * 5)
    plain = psi(base, values, correct_bias=False)
    corrected = psi(base, values)
    assert plain is not None and corrected is not None and corrected < plain
    assert psi(base, np.array([-1.0] * 10 + [1.0] * 10)) == 0.0
    fewer_patients = psi(base, values, n_effective=5)
    assert fewer_patients is not None and fewer_patients < corrected


def test_baselines_are_per_hospital_and_survive_a_save_and_load(tmp_path: Path) -> None:
    baselines = make_baselines(frame())
    assert set(baselines) == {"a", "b"}
    save_baseline(baselines, tmp_path)
    assert load_baseline(tmp_path) == baselines


def row(value: float) -> dict[str, float]:
    return dict.fromkeys(FEATURE_NAMES, value)


def test_drift_monitor_alerts_once_per_crossing_and_clears_when_it_returns() -> None:
    from datetime import UTC, datetime

    t = datetime(2026, 11, 14, tzinfo=UTC)
    rng = np.random.default_rng(3)
    baseline = {"a": make_baseline(frame(0))}
    mon = DriftMonitor(baseline)
    minute = 3000.0

    def feed(at: float, mean: float) -> None:
        mon.add("a", at, {f"p{i}": {n: float(rng.normal(mean, 1)) for n in FEATURE_NAMES} for i in range(60)})

    feed(minute, 0.0)
    readings, fresh = mon.evaluate(minute, t)
    assert len(readings) == len(FEATURE_NAMES) and not fresh
    # snapshots off the 30-minute grid are not kept
    mon.add("a", minute + 5, {"x": row(9.0)})
    assert len(mon.buffers["a"]) == 60
    for k in range(1, 5):
        feed(minute + 30 * k, 3.0)
    _, fresh = mon.evaluate(minute + 120, t)
    assert {r.feature for r in fresh} == set(FEATURE_NAMES)
    _, again = mon.evaluate(minute + 120, t)
    assert again == []  # already alerting, no repeat
    for k in range(5, 10):
        feed(minute + 30 * k, 0.0)
    _, clear = mon.evaluate(minute + 300, t)
    assert clear == [] and not mon.alerting
    assert all(m >= minute + 300 - DRIFT_WINDOW_MIN - 30 for m, _, _ in mon.buffers["a"])
    assert mon.evaluate(minute + 300, t)[0]  # still computes after the window moved


def test_drift_monitor_skips_hospitals_without_a_baseline_or_enough_rows() -> None:
    from datetime import UTC, datetime

    t = datetime(2026, 11, 14, tzinfo=UTC)
    mon = DriftMonitor({"a": make_baseline(frame())})
    mon.add("zzz", 30.0, {"p": row(0.0)})
    mon.add("a", 30.0, {"p": row(0.0)})
    assert mon.evaluate(30.0, t) == ([], [])


def fair_row(minute: float, pid: str, age: int, male: bool, score: float) -> ScoredRow:
    return ScoredRow(minute, pid, age, male, score)


def test_fairness_reports_groups_gaps_and_flags_a_large_gap() -> None:
    rng = np.random.default_rng(1)
    mon = FairnessMonitor()
    criticals: list[tuple[float, str, int]] = []
    for i in range(600):
        age = int(rng.integers(18, 90))
        male = bool(i % 2)
        bad = rng.random() < 0.25
        # the model separates outcomes well for under-65 patients and is random for 65+
        informative = age < 65
        score = float(np.clip((0.75 if bad else 0.2) + rng.normal(0, 0.1), 0, 1)) if informative else float(rng.random())
        minute = 100.0 + i
        mon.add(fair_row(minute, f"P{i}", age, male, score))
        if bad:
            criticals.append((minute + 60, f"P{i}", 1))
    report = mon.report(minute + 7 * 60, criticals)
    assert report["rows"] == 600 and report["positives"] == len(criticals)
    assert set(report["groups"]) == {"age 18-39", "age 40-64", "age 65+", "male", "female"}
    assert report["groups"]["age 65+"]["auroc"] < report["groups"]["age 18-39"]["auroc"]
    assert report["max_auroc_gap"] > FAIRNESS_GAP and report["flagged"] is True
    assert report["threshold"] == FAIRNESS_GAP


def test_fairness_with_too_few_rows_reports_none_instead_of_inventing_numbers() -> None:
    mon = FairnessMonitor()
    mon.add(fair_row(10.0, "P1", 30, True, 0.5))
    report = mon.report(10.0 + 7 * 60, [])
    assert report["max_auroc_gap"] == 0.0 and report["flagged"] is False
    assert all(g["auroc"] is None for g in report["groups"].values())


def test_fairness_only_labels_rows_scored_at_least_six_hours_ago() -> None:
    mon = FairnessMonitor()
    mon.add(fair_row(1000.0, "P1", 30, True, 0.5))
    assert mon.report(1000.0 + 60, [])["rows"] == 0  # outcome not known yet
    assert mon.report(1000.0 + 6 * 60, [])["rows"] == 1


# ---- in the running simulation ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def trained() -> tuple[object, object, dict[str, dict[str, FeatureBaseline]]]:
    ds = build_dataset(make_profiles(), 5, days=10, surges=1)
    result = train_deterioration(ds.rows)
    arrivals, _ = train_arrivals(ds.arrivals, ds.unit_stats)
    return result.model, arrivals, make_baselines(result.split.train)


def run_drift(trained: tuple[object, object, dict[str, dict[str, FeatureBaseline]]], flu: bool, seed: int) -> tuple[Simulation, dict[str, float]]:
    model, arrivals, baseline = trained
    sim = Simulation(load_layout(), make_profiles(), seed, timedelta(hours=48))
    sim.attach_ml(InferenceEngine(sim.world, model, arrivals, baseline))  # type: ignore[arg-type]
    sim.run_until(sim.visible_start + timedelta(hours=8))
    if flu:
        sim.start_scenario("flu_surge", "mercy")
    peak: dict[str, float] = {}
    for _ in range(4 * 60):
        sim.tick()
        if round(sim.world.now) % 15 == 0 and sim.ml is not None:
            for r in sim.ml.latest_drift:
                if r.hospital_id == "mercy":
                    peak[r.feature] = max(peak.get(r.feature, 0.0), r.psi)
    return sim, peak


def test_a_respiratory_surge_moves_spo2_and_respiratory_rate_past_the_drift_threshold(
    trained: tuple[object, object, dict[str, dict[str, FeatureBaseline]]],
) -> None:
    sim, peak = run_drift(trained, True, 77)
    assert peak["spo2"] > PSI_ALERT and peak["rr"] > PSI_ALERT
    assert {"spo2", "rr"} <= set(RESPIRATORY_FEATURES)
    alerts = [a for a in sim.ml.pending_audit if a.action == "drift_alert" and a.payload["hospital_id"] == "mercy"]  # type: ignore[union-attr]
    assert {"spo2", "rr"} <= {a.payload["feature"] for a in alerts}
    assert all(a.actor == "system" and a.payload["psi"] > PSI_ALERT for a in alerts)


def test_normal_operation_does_not_alarm_on_spo2_or_respiratory_rate(
    trained: tuple[object, object, dict[str, dict[str, FeatureBaseline]]],
) -> None:
    _, peak = run_drift(trained, False, 77)
    assert peak["spo2"] < PSI_ALERT and peak["rr"] < PSI_ALERT


def test_the_fairness_report_and_audit_rows_appear_as_the_simulation_runs(
    trained: tuple[object, object, dict[str, dict[str, FeatureBaseline]]],
) -> None:
    sim, _ = run_drift(trained, False, 5)
    ml = sim.ml
    assert ml is not None and ml.latest_fairness is not None
    assert {"rows", "groups", "max_auroc_gap", "flagged", "as_of"} <= set(ml.latest_fairness)
    audit = ml.drain_audit()
    assert any(a.action == "fairness_report" for a in audit)
    drift_rows = ml.drain_drift()
    assert drift_rows and {r.feature for r in drift_rows} == set(FEATURE_NAMES)
    assert ml.drain_drift() == []
