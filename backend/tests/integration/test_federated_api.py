"""Federated runs, their live progress and the model switch through the API (PROMPT.md §7.6)."""

import asyncio
import json
import sys
from pathlib import Path

import asyncpg
import pandas as pd
import pytest

from tests.integration.test_ml_api import app_client
from tests.integration.test_sim_db import seed_patients
from twin.api.federated import FederatedService
from twin.ml.fed_model import FederatedMlp

FAKE = str(Path(__file__).parent.parent / "fixtures" / "fake_fed_run.py")


def service_of(app: object) -> FederatedService:
    service = app.state.federated  # type: ignore[attr-defined]
    assert isinstance(service, FederatedService)
    return service


def use_fake(service: FederatedService, tmp_path: Path, mode: str = "ok") -> None:
    rows = tmp_path / "train.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(rows)
    service.rows_path = rows
    service.command = [sys.executable, FAKE, mode]


async def wait_done(service: FederatedService) -> None:
    assert service.task is not None
    await asyncio.wait_for(service.task, 30)


async def audit_actions(dsn: str) -> list[str]:
    conn = await asyncpg.connect(dsn)
    try:
        return [r["action"] for r in await conn.fetch("SELECT action FROM audit_log ORDER BY time, action")]
    finally:
        await conn.close()


async def test_status_before_any_run_shows_the_saved_comparison(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, _app):
        body = (await client.get("/federated")).json()
        assert body["state"]["status"] == "idle" and body["available"] is True
        assert set(body["result"]) >= {"federated", "centralized", "local_only", "gates"}
        assert len(body["result"]["federated"]["validation_auroc_by_round"]) == 25


async def test_a_run_streams_each_round_to_the_network_websocket_and_is_audited(migrated_db_url: str, tmp_path: Path) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        service = service_of(app)
        use_fake(service, tmp_path)
        feed = rt.hub.subscribe("__network__")
        started = await client.post("/federated/run")
        assert started.status_code == 202 and started.json()["status"] == "running"
        assert (await client.post("/federated/run")).status_code == 409  # one run at a time
        await wait_done(service)
        messages = []
        while not feed.queue.empty():
            messages.append(json.loads(feed.queue.get_nowait() or "{}"))
        fed = [m for m in messages if m["type"] == "federated"]
        assert [m["round"] for m in fed if m["status"] == "running"][-3:] == [1, 2, 3]
        assert fed[-1]["status"] == "done" and fed[-1]["val_auroc"] == pytest.approx([0.81, 0.82, 0.83]) and fed[-1]["error"] is None
        state = (await client.get("/federated")).json()["state"]
        assert state["status"] == "done" and state["rounds"] == 3
        actions = await audit_actions(migrated_db_url)
        assert "federated_run_start" in actions and "federated_run_done" in actions


async def test_a_run_that_misses_its_gates_finishes_and_says_so(migrated_db_url: str, tmp_path: Path) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, app):
        service = service_of(app)
        use_fake(service, tmp_path, "gates")
        await client.post("/federated/run")
        await wait_done(service)
        assert service.state.status == "done" and "below centralized" in (service.state.error or "")


@pytest.mark.parametrize(("mode", "needle"), [("error", "boom"), ("crash", "it crashed")])
async def test_a_failing_run_is_reported_not_hidden(migrated_db_url: str, tmp_path: Path, mode: str, needle: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, app):
        service = service_of(app)
        use_fake(service, tmp_path, mode)
        await client.post("/federated/run")
        await wait_done(service)
        assert service.state.status == "failed" and needle in (service.state.error or "")
        assert "federated_run_failed" in await audit_actions(migrated_db_url)
        use_fake(service, tmp_path, "ok")  # a new run is possible after a failure
        assert (await client.post("/federated/run")).status_code == 202
        await wait_done(service)


async def test_a_command_that_cannot_start_is_a_failed_run(migrated_db_url: str, tmp_path: Path) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, app):
        service = service_of(app)
        use_fake(service, tmp_path)
        service.command = ["/nonexistent/program"]
        await client.post("/federated/run")
        await wait_done(service)
        assert service.state.status == "failed" and service.state.error


async def test_running_without_training_rows_asks_for_make_train(migrated_db_url: str, tmp_path: Path) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, app):
        service_of(app).rows_path = tmp_path / "missing.parquet"
        response = await client.post("/federated/run")
        assert response.status_code == 409 and "make train" in response.json()["detail"]


async def test_switching_the_live_model_rescoring_everyone_and_auditing_it(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        for _ in range(10):
            await rt.step()
        before = (await client.get("/hospitals/mercy/state")).json()
        assert {e["risk"]["model_version"] for e in before["entities"] if e["risk"]} == {"lgbm-v1"}
        switched = await client.post("/models/active", json={"version": "fed-mlp-v1"})
        assert switched.status_code == 200 and switched.json() == {"active_deterioration": "fed-mlp-v1", "previous": "lgbm-v1"}
        assert (await client.get("/models")).json()["active_deterioration"] == "fed-mlp-v1"
        assert (await client.get("/health")).json()["ml_version"] == "fed-mlp-v1"
        after = (await client.get("/hospitals/mercy/state")).json()
        versions = {e["risk"]["model_version"] for e in after["entities"] if e["risk"]}
        assert versions == {"fed-mlp-v1"}
        for e in after["entities"]:
            if e["risk"]:
                assert 0 <= e["risk"]["score"] <= 1 and len(e["risk"]["top_factors"]) == 3
        assert (await client.post("/models/active", json={"version": "lgbm-v1"})).json()["previous"] == "fed-mlp-v1"
        assert (await audit_actions(migrated_db_url)).count("model_switch") == 2


async def test_switching_to_an_unknown_or_untrained_model_is_refused(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        bad = await client.post("/models/active", json={"version": "nope"})
        assert bad.status_code == 422 and "nope" in bad.json()["detail"]

        def untrained(version: str, root: Path = tmp_path) -> FederatedMlp:
            raise FileNotFoundError(f"No trained model {version} in {root}")

        monkeypatch.setattr(FederatedMlp, "load", staticmethod(untrained))
        missing = await client.post("/models/active", json={"version": "fed-mlp-v1"})
        assert missing.status_code == 409 and "make fed-train" in missing.json()["detail"]
        assert rt.sim.ml is not None and rt.sim.ml.model.version == "lgbm-v1"


async def test_the_model_switch_needs_loaded_models(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url, ml=False) as (client, rt, _app):
        await rt.step()
        response = await client.post("/models/active", json={"version": "fed-mlp-v1"})
        assert response.status_code == 409 and "make train" in response.json()["detail"]
