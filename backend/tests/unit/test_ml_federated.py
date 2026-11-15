"""Federated learning across the three hospitals (PROMPT.md §7.6)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tests.sim_helpers import make_profiles
from twin.ml import fed_cli
from twin.ml.dataset import Dataset, build_dataset
from twin.ml.features import FEATURE_NAMES, READABLE
from twin.ml.fed_model import FEATURE_SCALE, FED_VERSION, FederatedMlp, normalise
from twin.ml.federated import (
    AUROC_GAP_GATE,
    HOSPITALS,
    ROUNDS,
    FederatedResult,
    HospitalClient,
    gate_failures,
    get_weights,
    labels,
    make_mlp,
    partition,
    run_federated,
    save_result,
    set_weights,
    weighted_auroc,
)


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return build_dataset(make_profiles(), 5, days=18, surges=1)


@pytest.fixture(scope="module")
def run(dataset: Dataset) -> tuple[FederatedResult, list[tuple[int, int, float | None]]]:
    seen: list[tuple[int, int, float | None]] = []
    result = run_federated(dataset.rows, progress=lambda r, n, a: seen.append((r, n, a)))
    return result, seen


# ---- what each hospital holds ----------------------------------------------------------------------------------


def test_each_hospital_gets_only_its_own_rows_and_the_test_set_is_the_latest(dataset: Dataset) -> None:
    part = partition(dataset.rows)
    for h in HOSPITALS:
        assert set(part.train[h]["hospital"]) == {h} and set(part.val[h]["hospital"]) == {h}
    assert part.test["minute"].min() > max(t["minute"].max() for t in part.train.values())
    assert set(part.test["hospital"]) == set(HOSPITALS)  # the held-out test set is pooled, to compare the approaches


def test_federated_training_needs_all_three_hospitals(dataset: Dataset) -> None:
    with pytest.raises(ValueError, match="all three hospitals"):
        partition(dataset.rows[dataset.rows["hospital"] != "desert"])


def test_a_client_refuses_rows_of_another_hospital(dataset: Dataset) -> None:
    part = partition(dataset.rows)
    with pytest.raises(ValueError, match="another hospital's patients"):
        HospitalClient("mercy", part.train["stlukes"], part.val["mercy"], 1)
    with pytest.raises(ValueError, match="another hospital's patients"):
        HospitalClient("mercy", pd.concat([part.train["mercy"], part.train["desert"]]), part.val["mercy"], 1)


def test_only_parameters_cross_the_client_boundary(dataset: Dataset) -> None:
    part = partition(dataset.rows)
    client = HospitalClient("mercy", part.train["mercy"], part.val["mercy"], 3)
    initial = client.get_parameters({})
    template = get_weights(make_mlp())
    assert [w.shape for w in initial] == [w.shape for w in template]
    weights, n, metrics = client.fit(initial, {"epochs": 1, "round": 1})
    assert n == len(part.train["mercy"])
    assert all(isinstance(w, np.ndarray) and w.dtype == np.float32 for w in weights)
    assert [w.shape for w in weights] == [w.shape for w in template]  # the size of the update does not depend on the rows
    assert metrics == {}
    loss, n_val, eval_metrics = client.evaluate(weights, {})
    assert isinstance(loss, float) and n_val == len(part.val["mercy"])
    assert set(eval_metrics) == {"auroc"} and 0.0 <= float(eval_metrics["auroc"]) <= 1.0
    assert not any(isinstance(v, pd.DataFrame | pd.Series) for v in (weights, n, metrics, loss, eval_metrics))


def test_training_changes_the_weights_and_is_reproducible(dataset: Dataset) -> None:
    part = partition(dataset.rows)
    start = get_weights(make_mlp())

    def fit() -> list[np.ndarray[Any, Any]]:
        client = HospitalClient("desert", part.train["desert"], part.val["desert"], 4)
        return client.fit(start, {"epochs": 1, "round": 2})[0]

    first, second = fit(), fit()
    assert all(np.array_equal(a, b) for a, b in zip(first, second, strict=True))
    assert any(not np.array_equal(a, b) for a, b in zip(first, start, strict=True))


def test_set_weights_round_trips() -> None:
    a, b = make_mlp(), make_mlp()
    set_weights(b, get_weights(a))
    assert all(np.array_equal(x, y) for x, y in zip(get_weights(a), get_weights(b), strict=True))


def test_weighted_auroc_weights_by_validation_rows() -> None:
    assert weighted_auroc([(100, {"auroc": 0.9}), (300, {"auroc": 0.5})]) == {"auroc": 0.6}


# ---- the run ------------------------------------------------------------------------------------------------


def test_the_run_uses_25_rounds_and_reports_progress_each_round(run: tuple[FederatedResult, list[tuple[int, int, float | None]]]) -> None:
    result, seen = run
    assert ROUNDS == 25 and result.metrics["rounds"] == 25
    assert [r for r, _, _ in seen] == list(range(1, 26)) and {n for _, n, _ in seen} == {25}
    curve = result.comparison["federated"]["validation_auroc_by_round"]
    assert len(curve) == 25 and all(0.5 < a <= 1.0 for a in curve) and curve == [a for _, _, a in seen]
    assert curve[-1] > curve[0] - 0.02  # the shared model does not get worse as hospitals collaborate


def test_federated_is_within_0_03_of_centralized_and_beats_the_average_local_model(
    run: tuple[FederatedResult, list[tuple[int, int, float | None]]],
) -> None:
    c = run[0].comparison
    fed, cent, local = c["federated"]["test"]["auroc"], c["centralized"]["test"]["auroc"], c["local_only"]["mean_auroc"]
    assert fed >= cent - AUROC_GAP_GATE, f"federated {fed:.3f} vs centralized {cent:.3f}"
    assert fed > local, f"federated {fed:.3f} vs mean local-only {local:.3f}"
    assert set(c["local_only"]) == {*HOSPITALS, "mean_auroc"}
    assert run[0].metrics["gates"] == {"within_0.03_of_centralized": True, "beats_local_only_average": True}
    assert gate_failures(run[0].metrics) == []


def test_the_metrics_say_what_crosses_the_boundary_and_how_much_each_hospital_held(
    run: tuple[FederatedResult, list[tuple[int, int, float | None]]],
) -> None:
    m = run[0].metrics
    assert "no patient rows" in m["what_crosses_the_boundary"]
    assert set(m["clients"]) == set(HOSPITALS) and all(c["train_rows"] > 100 for c in m["clients"].values())
    assert m["validation"]["model"]["auroc"] > 0.7 and m["test"]["model"]["auroc"] > 0.7


def test_gate_failures_are_reported() -> None:
    def metrics(fed: float, cent: float, local: float) -> dict[str, Any]:
        return {
            "comparison": {
                "federated": {"test": {"auroc": fed}},
                "centralized": {"test": {"auroc": cent}},
                "local_only": {"mean_auroc": local},
            }
        }

    assert gate_failures(metrics(0.90, 0.91, 0.85)) == []
    assert any("below centralized" in p for p in gate_failures(metrics(0.85, 0.91, 0.80)))
    assert any("local-only" in p for p in gate_failures(metrics(0.90, 0.91, 0.92)))
    assert len(gate_failures(metrics(0.80, 0.91, 0.92))) == 2


# ---- the model that comes out --------------------------------------------------------------------------------


def test_every_feature_has_a_scale_and_scaled_values_are_centred(dataset: Dataset) -> None:
    assert set(FEATURE_SCALE) == set(FEATURE_NAMES)
    x = normalise(dataset.rows)
    assert not np.isnan(x).any()
    assert np.abs(np.median(x, axis=0)).max() < 1.5 and np.abs(x).mean() < 2.0


def test_predictions_are_probabilities_and_survive_saving(
    tmp_path: Path, run: tuple[FederatedResult, list[tuple[int, int, float | None]]], dataset: Dataset
) -> None:
    model = run[0].model
    frame = dataset.rows.head(300)
    p = model.predict(frame)
    assert p.shape == (300,) and ((p >= 0) & (p <= 1)).all()
    model.save(tmp_path / FED_VERSION)
    again = FederatedMlp.load(FED_VERSION, tmp_path)
    assert np.allclose(again.predict(frame), p)
    with pytest.raises(FileNotFoundError, match="No trained model"):
        FederatedMlp.load("missing", tmp_path)
    (tmp_path / FED_VERSION / "features.json").write_text(json.dumps(["x"]), encoding="utf-8")
    with pytest.raises(ValueError, match="different features"):
        FederatedMlp.load(FED_VERSION, tmp_path)


def test_the_numpy_forward_pass_matches_pytorch(run: tuple[FederatedResult, list[tuple[int, int, float | None]]], dataset: Dataset) -> None:
    from twin.ml.federated import predict_raw

    model = run[0].model
    net = make_mlp()
    set_weights(net, [w.astype(np.float32) for w in model.weights])
    frame = dataset.rows.head(200)
    assert np.allclose(predict_raw(net, normalise(frame)), model.raw(frame), atol=1e-5)


def test_factors_are_the_input_gradient_times_the_input(run: tuple[FederatedResult, list[tuple[int, int, float | None]]], dataset: Dataset) -> None:
    model = run[0].model
    x = normalise(dataset.rows.sample(5, random_state=1))
    contrib = model.contributions(x)
    assert contrib.shape == (5, len(FEATURE_NAMES))
    eps = 1e-4
    for i in (0, 5, 22):
        bumped = x.copy()
        bumped[:, i] += eps
        gradient = (model.logits(bumped) - model.logits(x)) / eps
        assert np.allclose(contrib[:, i], gradient * x[:, i], atol=1e-3)


def test_scoring_gives_levels_and_three_signed_factors(run: tuple[FederatedResult, list[tuple[int, int, float | None]]], dataset: Dataset) -> None:
    scored = run[0].model.score(dataset.rows.head(50))
    assert len(scored) == 50
    for s in scored:
        assert 0 <= s.score <= 1 and s.level in ("low", "medium", "high") and len(s.top_factors) == 3
        assert all(name in READABLE.values() and -1 <= share <= 1 for name, share in s.top_factors)
    assert labels(dataset.rows.head(5)).shape == (5,)


# ---- saving and the command line ----------------------------------------------------------------------------


def test_results_are_saved_where_the_spec_says(tmp_path: Path, run: tuple[FederatedResult, list[tuple[int, int, float | None]]]) -> None:
    save_result(run[0], tmp_path)
    assert (tmp_path / FED_VERSION / "weights.npz").is_file()
    comparison = json.loads((tmp_path / "lgbm-v1" / "federated.json").read_text(encoding="utf-8"))
    assert set(comparison) >= {"federated", "centralized", "local_only", "gates", "rounds"}
    assert len(comparison["federated"]["validation_auroc_by_round"]) == 25
    metrics = json.loads((tmp_path / FED_VERSION / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["federated"] is True and metrics["validation"]["model"]["auroc"] > 0.5


def test_the_command_line_prints_json_progress_and_a_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    run: tuple[FederatedResult, list[tuple[int, int, float | None]]],
) -> None:
    rows = tmp_path / "train.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(rows)

    def fake(_: pd.DataFrame, rounds: int, epochs: int, seed: int, progress: Any) -> FederatedResult:
        progress(1, rounds, 0.8)
        return run[0]

    monkeypatch.setattr(fed_cli, "run_federated", fake)
    assert fed_cli.main(["--json", "--rounds", "2"], rows, tmp_path / "models") == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == {"event": "round", "round": 1, "rounds": 2, "auroc": 0.8}
    assert lines[-1]["event"] == "done" and lines[-1]["gates_ok"] is True and "federated" in lines[-1]["summary"]
    assert (tmp_path / "models" / FED_VERSION / "weights.npz").is_file()
    assert fed_cli.main([], rows, tmp_path / "models") == 0
    assert "Federated model fed-mlp-v1" in capsys.readouterr().out


def test_the_command_line_fails_clearly_without_training_rows_or_when_a_gate_is_missed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    run: tuple[FederatedResult, list[tuple[int, int, float | None]]],
) -> None:
    assert fed_cli.main(["--json"], tmp_path / "none.parquet", tmp_path) == 1
    captured = capsys.readouterr()
    assert "make train" in captured.err and json.loads(captured.out)["event"] == "error"
    rows = tmp_path / "train.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(rows)

    def broken(*_: Any) -> FederatedResult:
        raise ValueError("Federated training needs rows from all three hospitals")

    monkeypatch.setattr(fed_cli, "run_federated", broken)
    assert fed_cli.main(["--json"], rows, tmp_path) == 1
    assert "all three hospitals" in capsys.readouterr().err
    worse = FederatedResult(
        run[0].model,
        {
            **run[0].metrics,
            "comparison": {"federated": {"test": {"auroc": 0.5}}, "centralized": {"test": {"auroc": 0.9}}, "local_only": {"mean_auroc": 0.8}},
        },
        {"federated": {"test": {"auroc": 0.5}}, "centralized": {"test": {"auroc": 0.9}}, "local_only": {"mean_auroc": 0.8}},
    )
    monkeypatch.setattr(fed_cli, "run_federated", lambda *_: worse)
    assert fed_cli.main([], rows, tmp_path / "m") == 1
    assert "QUALITY GATE FAILED" in capsys.readouterr().err
