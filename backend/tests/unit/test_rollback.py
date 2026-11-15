"""Rollback proposals (extra X3)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from twin.ml.governance import DriftReading
from twin.ml.registry import deterioration_versions, list_models, validation_auroc
from twin.ml.rollback import AUROC_DROP, DRIFT_FEATURES, DRIFT_PSI, pick_target, propose

NOW = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)


def drift(n: int, psi: float = 0.5) -> list[DriftReading]:
    return [DriftReading(NOW, "mercy", f"f{i}", psi) for i in range(n)]


def test_a_replacement_is_the_first_preferred_version_that_is_not_live() -> None:
    assert pick_target("lgbm-v1", ["lgbm-v1", "fed-mlp-v1"]) == "fed-mlp-v1"
    assert pick_target("fed-mlp-v1", ["lgbm-v1", "fed-mlp-v1"]) == "lgbm-v1"
    assert pick_target("a", ["a", "z", "b"]) == "b" and pick_target("a", ["a"]) is None


def test_a_fall_in_live_auroc_of_more_than_the_limit_proposes_a_rollback() -> None:
    p = propose(0.80, 0.90, [], "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW)
    assert p is not None and p.reason == "live_auroc_drop" and p.to_version == "fed-mlp-v1" and p.from_version == "lgbm-v1"
    assert "0.800" in p.detail and "0.900" in p.detail
    assert propose(0.90 - AUROC_DROP + 0.001, 0.90, [], "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW) is None  # within the limit


def test_drift_on_more_than_three_features_proposes_one_and_three_does_not() -> None:
    assert propose(None, None, drift(DRIFT_FEATURES), "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW) is None
    p = propose(None, None, drift(DRIFT_FEATURES + 1), "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW)
    assert p is not None and p.reason == "drift_spread" and "4 features" in p.detail
    assert propose(None, None, drift(9, DRIFT_PSI - 0.01), "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW) is None  # below 0.3
    same = [DriftReading(NOW, h, "spo2", 0.9) for h in ("mercy", "desert", "stlukes", "x", "y")]
    assert propose(None, None, same, "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW) is None  # one feature at five hospitals is one feature


def test_there_is_no_proposal_without_somewhere_to_go_or_without_numbers() -> None:
    assert propose(0.5, 0.9, drift(9), "lgbm-v1", ["lgbm-v1"], NOW) is None
    assert propose(None, 0.9, [], "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW) is None
    assert propose(0.5, None, [], "lgbm-v1", ["lgbm-v1", "fed-mlp-v1"], NOW) is None


def test_the_registry_lists_versions_with_time_and_validation_auroc(tmp_path: Path) -> None:
    import json

    (tmp_path / "lgbm-v1").mkdir()
    (tmp_path / "lgbm-v1" / "metrics.json").write_text(json.dumps({"validation": {"model": {"auroc": 0.91}}}), encoding="utf-8")
    (tmp_path / "lgbm-v1" / "model.txt").write_text("x", encoding="utf-8")
    (tmp_path / "fed-mlp-v1").mkdir()
    (tmp_path / "fed-mlp-v1" / "metrics.json").write_text(json.dumps({"validation": {"model": {"auroc": 0.88}}}), encoding="utf-8")
    (tmp_path / "los-lgbm-v1").mkdir()
    (tmp_path / "los-lgbm-v1" / "metrics.json").write_text(json.dumps({"validation": {"baseline_mae": 9}}), encoding="utf-8")
    listed = {m["version"]: m for m in list_models(tmp_path)}
    assert datetime.fromisoformat(listed["lgbm-v1"]["trained_at"]).tzinfo is not None
    assert validation_auroc("lgbm-v1", tmp_path) == 0.91 and validation_auroc("nope", tmp_path) is None
    assert deterioration_versions(tmp_path) == ["lgbm-v1"]  # the federated one has no weights yet, the LOS model is another kind
    (tmp_path / "fed-mlp-v1" / "weights.npz").write_text("x", encoding="utf-8")
    assert deterioration_versions(tmp_path) == ["fed-mlp-v1", "lgbm-v1"]
    assert pytest is not None
