"""Scores, forecasts and models through the real database and API (PROMPT.md §6.2, §7.4)."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tests.integration.test_sim_db import seed_patients
from twin.api.app import create_app
from twin.api.runtime import SimRuntime
from twin.common.config import Settings


@asynccontextmanager
async def app_client(dsn: str, *, ml: bool = True) -> AsyncIterator[tuple[httpx.AsyncClient, SimRuntime, FastAPI]]:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(dsn),
        sim_warmup_hours=10,
        sim_autostart=False,
        sim_seed=5,
        ml_enabled=ml,
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, app.state.runtime, app


async def test_scores_and_forecasts_are_stored_and_served(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _):
        for _ in range(20):
            await rt.step()
        health = (await client.get("/health")).json()
        assert health["ml"] == "ready" and health["ml_version"] == "lgbm-v1"

        conn = await asyncpg.connect(migrated_db_url)
        try:
            n_scores = await conn.fetchval("SELECT count(*) FROM risk_scores")
            levels = {r["level"] for r in await conn.fetch("SELECT DISTINCT level FROM risk_scores")}
            row = await conn.fetchrow("SELECT * FROM risk_scores ORDER BY time DESC, patient_id LIMIT 1")
            n_forecasts = await conn.fetchval("SELECT count(*) FROM forecasts")
            kinds = {r["metric"] for r in await conn.fetch("SELECT DISTINCT metric FROM forecasts")}
            assert await conn.fetchval("SELECT count(*) FROM events WHERE kind = 'risk'") == 0  # scores live in risk_scores
        finally:
            await conn.close()
        assert n_scores > 200 and "low" in levels
        assert row is not None
        assert 0 <= row["score"] <= 1 and row["model_version"] == "lgbm-v1"
        assert len(json.loads(row["top_factors"])) == 3
        assert n_forecasts > 0 and "arrivals" in kinds and "hours_until_full:ICU" in kinds

        state = (await client.get("/hospitals/mercy/state")).json()
        scored = [e for e in state["entities"] if e["kind"] == "patient" and e["risk"]]
        assert scored
        patient = scored[0]
        detail = (await client.get(f"/patients/{patient['id']}")).json()
        assert detail["risk"]["model_version"] == "lgbm-v1"
        assert len(detail["risk"]["top_factors"]) == 3
        history = (await client.get(f"/patients/{patient['id']}/risk?window=6h")).json()
        assert history["points"] and all(0 <= p["score"] <= 1 for p in history["points"])

        report = (await client.get("/forecast/mercy")).json()
        assert report["model_version"] == "arrivals-lgbm-v1"
        assert [a["hours_ahead"] for a in report["arrivals"]] == [1, 2, 3, 4, 5, 6]
        assert set(report["hours_until_full"]) == {"ER", "WARD", "ICU", "REC"}
        assert (await client.get("/forecast/nope")).status_code == 404
        assert state["kpis"]["alerts"] == sum(1 for e in state["entities"] if e["risk"] and e["risk"]["level"] == "high")


async def test_models_endpoint_lists_versions_metrics_and_the_active_models(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, _):
        body = (await client.get("/models")).json()
        assert body["active_deterioration"] == "lgbm-v1" and body["active_arrivals"] == "arrivals-lgbm-v1"
        by_version = {m["version"]: m for m in body["models"]}
        det = by_version["lgbm-v1"]
        assert det["kind"] == "deterioration"
        assert det["metrics"]["validation"]["model"]["auroc"] >= 0.75
        assert det["metrics"]["validation"]["model"]["auroc"] > det["metrics"]["validation"]["news2_baseline"]["auroc"]
        assert by_version["arrivals-lgbm-v1"]["kind"] == "arrivals_forecast"


async def test_without_models_the_sim_runs_unscored_and_says_so(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed_patients(migrated_db_url)
    monkeypatch.setattr("twin.api.app.MODEL_VERSION", "does-not-exist")
    async with app_client(migrated_db_url) as (client, rt, _):
        await rt.step()
        health = (await client.get("/health")).json()
        assert health["ml"] == "missing" and health["status"] == "ok"
        assert "make train" in (await client.get("/models")).json()["error"]
        state = (await client.get("/hospitals/mercy/state")).json()
        assert all(e["risk"] is None for e in state["entities"])
        report = (await client.get("/forecast/mercy")).json()
        assert report["arrivals"] == [] and report["model_version"] is None


async def test_ml_can_be_switched_off(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url, ml=False) as (client, rt, _):
        await rt.step()
        assert (await client.get("/health")).json()["ml"] == "off"
        assert (await client.get("/models")).json()["active_deterioration"] is None
