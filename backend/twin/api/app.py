"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from twin.agent.llm import make_client
from twin.agent.service import AgentService
from twin.api.health import router as health_router
from twin.api.hub import Hub
from twin.api.routes_agent import router as agent_router
from twin.api.routes_governance import router as governance_router
from twin.api.routes_hospitals import router as hospitals_router
from twin.api.routes_ml import router as ml_router
from twin.api.routes_patients import router as patients_router
from twin.api.routes_sim import router as sim_router
from twin.api.routes_ws import router as ws_router
from twin.api.runtime import SimRuntime, load_profiles
from twin.common.config import Settings, get_settings
from twin.common.logging import configure_logging
from twin.db.pool import create_pool
from twin.ml.forecast import FORECAST_VERSION, ArrivalsModel
from twin.ml.governance import load_baseline
from twin.ml.inference import InferenceEngine
from twin.ml.model import MODELS_DIR, DeteriorationModel
from twin.ml.train import MODEL_VERSION
from twin.sim.engine import Simulation
from twin.sim.layout_model import load_layout

logger = logging.getLogger(__name__)

APP_TITLE = "Hospital Twin API"


def attach_models(app: FastAPI, sim: Simulation) -> None:
    """Load the trained models and attach live inference. Without models the simulation still runs, scores are
    absent, and /health says so."""
    try:
        det = DeteriorationModel.load(MODEL_VERSION)
        arrivals = ArrivalsModel.load(FORECAST_VERSION)
    except (FileNotFoundError, ValueError) as error:
        app.state.ml_error = f"Models not available ({error}). Run `make train`."
        logger.error(app.state.ml_error)
        return
    baseline = load_baseline(MODELS_DIR / det.version)
    sim.attach_ml(InferenceEngine(sim.world, det, arrivals, baseline))
    logger.info("Inference attached: %s and %s", det.version, arrivals.version)


async def start_simulation(app: FastAPI, settings: Settings) -> None:
    """Build the simulation from the Synthea pool, simulate the warm-up, and start the tick loop. If the
    pool is empty the API still serves /health, which reports why the simulation is not running."""
    profiles = await load_profiles(app.state.pool)
    if not profiles:
        app.state.sim_error = "No Synthea patients in the database. Run `make seed`."
        logger.error(app.state.sim_error)
        return
    sim = Simulation(
        load_layout(),
        profiles,
        settings.sim_seed,
        timedelta(hours=settings.sim_warmup_hours),
        debug=settings.sim_debug,
    )
    app.state.ml_error = None
    if settings.ml_enabled:
        attach_models(app, sim)
    runtime = SimRuntime(sim, app.state.pool, Hub(), settings.sim_speed)
    app.state.runtime = runtime
    if settings.agent_enabled:
        runtime.agent = AgentService(
            sim,
            app.state.pool,
            make_client(
                settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None,
                settings.gemini_model,
            ),
            runtime.apply_action,
            runtime.publish_now,
            min_llm_interval_s=settings.agent_llm_min_interval_s,
        )
    await runtime.prepare(reset=settings.sim_reset_on_start)
    if settings.sim_autostart:
        runtime.start()


def create_app(settings: Settings | None = None, *, simulate: bool = True) -> FastAPI:
    """Build the API. The database pool opens on startup and closes on shutdown. With `simulate`, the
    simulation runs inside the same process (PROMPT.md §2)."""
    resolved = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved.log_level, resolved.secret_values())
        app.state.pool = await create_pool(resolved.database_url.get_secret_value())
        app.state.runtime = None
        app.state.sim_error = None
        logger.info("Database pool opened")
        try:
            if simulate:
                await start_simulation(app, resolved)
            yield
        finally:
            if app.state.runtime is not None:
                await app.state.runtime.stop()
            await app.state.pool.close()
            logger.info("Database pool closed")

    app = FastAPI(title=APP_TITLE, version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    for router in (
        health_router,
        hospitals_router,
        patients_router,
        sim_router,
        ml_router,
        agent_router,
        governance_router,
        ws_router,
    ):
        app.include_router(router)
    return app
