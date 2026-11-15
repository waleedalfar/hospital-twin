"""Federated training of the deterioration model across the three hospitals (PROMPT.md §7.6).

Hospitals cannot pool patient records, so each one trains on its own rows and only model weights leave the building.
A Flower simulation runs three clients (one per hospital) that train a PyTorch MLP with FedAvg. The result is
compared on one held-out test set with (b) the same MLP trained centrally on the pooled rows and (c) one MLP per
hospital trained only on that hospital's rows.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import flwr as fl
import numpy as np
import pandas as pd
import torch
from flwr.client import NumPyClient
from flwr.common import EvaluateRes, FitRes, Metrics, NDArrays, Parameters, Scalar, ndarrays_to_parameters, parameters_to_ndarrays
from flwr.server.client_proxy import ClientProxy
from torch import nn

from twin.ml.features import FEATURE_NAMES
from twin.ml.fed_model import FED_VERSION, HIDDEN, FederatedMlp, normalise
from twin.ml.metrics import Floats, Ints, auroc_or_none, evaluate
from twin.ml.model import MODELS_DIR, Calibrator
from twin.ml.split import split_by_time

logger = logging.getLogger(__name__)

ROUNDS = 25
LOCAL_EPOCHS = 1
BATCH = 256
LR = 1e-3
SEED = 11
MAX_POS_WEIGHT = 20.0
AUROC_GAP_GATE = 0.03
HOSPITALS = ("mercy", "stlukes", "desert")

Progress = Callable[[int, int, float | None], None]


def make_mlp() -> nn.Module:
    layers: list[nn.Module] = []
    width = len(FEATURE_NAMES)
    for h in HIDDEN:
        layers += [nn.Linear(width, h), nn.ReLU()]
        width = h
    layers.append(nn.Linear(width, 1))
    return nn.Sequential(*layers)


def get_weights(model: nn.Module) -> NDArrays:
    return [p.detach().cpu().numpy().astype(np.float32) for p in model.state_dict().values()]


def set_weights(model: nn.Module, weights: NDArrays) -> None:
    model.load_state_dict({k: torch.tensor(w) for k, w in zip(model.state_dict().keys(), weights, strict=True)})


def labels(frame: pd.DataFrame) -> Ints:
    return np.asarray(frame["label"], dtype=np.int_)


def train_epochs(model: nn.Module, x: Floats, y: Ints, epochs: int, seed: int) -> None:
    """Adam on class-weighted binary cross-entropy (events are rare). The weight comes from this data alone."""
    torch.set_num_threads(1)
    positives = max(1, int(y.sum()))
    pos_weight = torch.tensor(min(MAX_POS_WEIGHT, max(1.0, (len(y) - positives) / positives)), dtype=torch.float32)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    xt, yt = torch.tensor(x, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    gen = torch.Generator().manual_seed(seed)
    model.train()
    for _ in range(epochs):
        order = torch.randperm(len(yt), generator=gen)
        for start in range(0, len(order), BATCH):
            idx = order[start : start + BATCH]
            opt.zero_grad()
            loss_fn(model(xt[idx])[:, 0], yt[idx]).backward()
            opt.step()


def predict_raw(model: nn.Module, x: Floats) -> Floats:
    model.eval()
    with torch.no_grad():
        return np.asarray(torch.sigmoid(model(torch.tensor(x, dtype=torch.float32))[:, 0]).numpy(), dtype=np.float64)


class HospitalClient(NumPyClient):
    """One hospital. It holds only that hospital's rows; what it returns is weights, a row count and an AUROC."""

    def __init__(self, hospital: str, train: pd.DataFrame, val: pd.DataFrame, seed: int) -> None:
        if set(train["hospital"]) | set(val["hospital"]) != {hospital}:
            raise ValueError(f"The data given to the {hospital} client contains another hospital's patients")
        self.hospital = hospital
        self._x, self._y = normalise(train), labels(train)
        self._xv, self._yv = normalise(val), labels(val)
        self._seed = seed
        self._model = make_mlp()

    def get_parameters(self, config: dict[str, Scalar]) -> NDArrays:
        return get_weights(self._model)

    def fit(self, parameters: NDArrays, config: dict[str, Scalar]) -> tuple[NDArrays, int, dict[str, Scalar]]:
        set_weights(self._model, parameters)
        epochs, rnd = int(config["epochs"]), int(config["round"])
        train_epochs(self._model, self._x, self._y, epochs, self._seed + 1000 * rnd)
        return get_weights(self._model), len(self._y), {}

    def evaluate(self, parameters: NDArrays, config: dict[str, Scalar]) -> tuple[float, int, dict[str, Scalar]]:
        set_weights(self._model, parameters)
        p = predict_raw(self._model, self._xv)
        auroc = auroc_or_none(self._yv, p)
        eps = 1e-7
        loss = float(-np.mean(self._yv * np.log(p + eps) + (1 - self._yv) * np.log(1 - p + eps)))
        return loss, len(self._yv), {"auroc": 0.5 if auroc is None else float(auroc)}


def weighted_auroc(results: list[tuple[int, Metrics]]) -> Metrics:
    total = sum(n for n, _ in results) or 1
    return {"auroc": sum(n * float(m["auroc"]) for n, m in results) / total}


class TrackedFedAvg(fl.server.strategy.FedAvg):
    """FedAvg that keeps the final weights and reports each round's validation AUROC as it happens."""

    def __init__(self, progress: Progress | None, rounds: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.progress, self.rounds = progress, rounds
        self.final: NDArrays | None = None
        self.per_round: list[float] = []

    def aggregate_fit(
        self, server_round: int, results: list[tuple[ClientProxy, FitRes]], failures: list[Any]
    ) -> tuple[Parameters | None, dict[str, Scalar]]:
        params, metrics = super().aggregate_fit(server_round, results, failures)
        if params is not None:
            self.final = parameters_to_ndarrays(params)
        return params, metrics

    def aggregate_evaluate(
        self, server_round: int, results: list[tuple[ClientProxy, EvaluateRes]], failures: list[Any]
    ) -> tuple[float | None, dict[str, Scalar]]:
        loss, metrics = super().aggregate_evaluate(server_round, results, failures)
        auroc = float(metrics["auroc"]) if "auroc" in metrics else None
        if auroc is not None:
            self.per_round.append(auroc)
        if self.progress is not None:
            self.progress(server_round, self.rounds, auroc)
        return loss, metrics


@dataclass
class Partition:
    """The rows each hospital holds, and the pooled held-out test set (used only to compare the three approaches)."""

    train: dict[str, pd.DataFrame]
    val: dict[str, pd.DataFrame]
    test: pd.DataFrame
    pooled_val: pd.DataFrame = field(default_factory=pd.DataFrame)


def partition(rows: pd.DataFrame) -> Partition:
    split = split_by_time(rows)
    present = [h for h in HOSPITALS if (split.train["hospital"] == h).any()]
    if len(present) != len(HOSPITALS):
        raise ValueError(f"Federated training needs rows from all three hospitals; got {present}")
    return Partition(
        {h: split.train[split.train["hospital"] == h] for h in HOSPITALS},
        {h: split.val[split.val["hospital"] == h] for h in HOSPITALS},
        split.test,
        split.val,
    )


def score_on(model: nn.Module, frame: pd.DataFrame) -> dict[str, Any]:
    return evaluate(labels(frame), predict_raw(model, normalise(frame)))


def train_model(x: Floats, y: Ints, epochs: int, seed: int) -> nn.Module:
    torch.manual_seed(seed)
    model = make_mlp()
    train_epochs(model, x, y, epochs, seed)
    return model


@dataclass
class FederatedResult:
    model: FederatedMlp
    metrics: dict[str, Any]
    comparison: dict[str, Any]


def run_federated(
    rows: pd.DataFrame, rounds: int = ROUNDS, local_epochs: int = LOCAL_EPOCHS, seed: int = SEED, progress: Progress | None = None
) -> FederatedResult:
    """Run the Flower simulation, then train the centralized and local-only comparisons with the same budget."""
    part = partition(rows)
    torch.manual_seed(seed)
    initial = get_weights(make_mlp())
    strategy = TrackedFedAvg(
        progress,
        rounds,
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=3,
        min_evaluate_clients=3,
        min_available_clients=3,
        initial_parameters=ndarrays_to_parameters(initial),
        on_fit_config_fn=lambda rnd: {"epochs": local_epochs, "round": rnd},
        evaluate_metrics_aggregation_fn=weighted_auroc,
    )

    def client_fn(cid: str) -> Any:
        hospital = HOSPITALS[int(cid)]
        return HospitalClient(hospital, part.train[hospital], part.val[hospital], seed + int(cid)).to_client()

    fl.simulation.start_simulation(
        client_fn=client_fn,
        num_clients=len(HOSPITALS),
        config=fl.server.ServerConfig(num_rounds=rounds),
        strategy=strategy,
        client_resources={"num_cpus": 1},
        ray_init_args={"include_dashboard": False, "num_cpus": len(HOSPITALS), "log_to_driver": False, "logging_level": logging.ERROR},
    )
    if strategy.final is None:
        raise RuntimeError("The federated run finished without any aggregated weights")
    fed = make_mlp()
    set_weights(fed, strategy.final)
    epochs = rounds * local_epochs

    pooled_train = pd.concat(part.train.values())
    central = train_model(normalise(pooled_train), labels(pooled_train), epochs, seed)
    local = {h: train_model(normalise(part.train[h]), labels(part.train[h]), epochs, seed + i) for i, h in enumerate(HOSPITALS)}

    fed_test, central_test = score_on(fed, part.test), score_on(central, part.test)
    local_test = {h: score_on(m, part.test) for h, m in local.items()}
    local_mean = float(np.mean([m["auroc"] for m in local_test.values()]))
    comparison: dict[str, Any] = {
        "federated": {"test": fed_test, "validation_auroc_by_round": strategy.per_round},
        "centralized": {"test": central_test},
        "local_only": {**{h: {"test": m} for h, m in local_test.items()}, "mean_auroc": local_mean},
    }
    gates = {
        "within_0.03_of_centralized": fed_test["auroc"] >= central_test["auroc"] - AUROC_GAP_GATE,
        "beats_local_only_average": fed_test["auroc"] > local_mean,
    }
    pooled_val = part.pooled_val
    calibrator = fit_calibrator(predict_raw(fed, normalise(pooled_val)), labels(pooled_val))
    model = FederatedMlp(FED_VERSION, [w.astype(np.float64) for w in get_weights(fed)], calibrator)
    val_metrics = evaluate(labels(pooled_val), model.predict(pooled_val))
    test_metrics = evaluate(labels(part.test), model.predict(part.test))
    metrics: dict[str, Any] = {
        "version": FED_VERSION,
        "federated": True,
        "validation": {"model": val_metrics},
        "test": {"model": test_metrics},
        "rounds": rounds,
        "local_epochs": local_epochs,
        "seed": seed,
        "clients": {h: {"train_rows": len(part.train[h]), "validation_rows": len(part.val[h])} for h in HOSPITALS},
        "comparison": comparison,
        "gates": gates,
        "what_crosses_the_boundary": "model weights (and each client's row count and validation AUROC); no patient rows",
    }
    logger.info("Federated: test AUROC %.3f vs centralized %.3f vs local mean %.3f", fed_test["auroc"], central_test["auroc"], local_mean)
    return FederatedResult(model, metrics, comparison)


def fit_calibrator(raw: Floats, y: Ints) -> Calibrator:
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(raw, y)
    return Calibrator(x=[float(v) for v in iso.X_thresholds_], y=[float(v) for v in iso.y_thresholds_])


def gate_failures(metrics: dict[str, Any]) -> list[str]:
    fed = metrics["comparison"]["federated"]["test"]["auroc"]
    cent = metrics["comparison"]["centralized"]["test"]["auroc"]
    local = metrics["comparison"]["local_only"]["mean_auroc"]
    problems: list[str] = []
    if fed < cent - AUROC_GAP_GATE:
        problems.append(f"federated AUROC {fed:.3f} is more than {AUROC_GAP_GATE} below centralized {cent:.3f}")
    if fed <= local:
        problems.append(f"federated AUROC {fed:.3f} does not beat the local-only average {local:.3f}")
    return problems


def save_result(result: FederatedResult, models_dir: Path = MODELS_DIR, deterioration_version: str = "lgbm-v1") -> None:
    """Weights and metrics under `models/fed-mlp-v1/`, the comparison under `models/<deterioration version>/federated.json`."""
    result.model.save(models_dir / FED_VERSION)
    (models_dir / FED_VERSION / "metrics.json").write_text(json.dumps(result.metrics, indent=1) + "\n", encoding="utf-8")
    target = models_dir / deterioration_version
    target.mkdir(parents=True, exist_ok=True)
    (target / "federated.json").write_text(
        json.dumps(
            {"version": FED_VERSION, **result.metrics["comparison"], "gates": result.metrics["gates"], "rounds": result.metrics["rounds"]}, indent=1
        )
        + "\n",
        encoding="utf-8",
    )
