"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twin.api.health import router as health_router
from twin.common.config import Settings, get_settings
from twin.common.logging import configure_logging
from twin.db.pool import create_pool

logger = logging.getLogger(__name__)

APP_TITLE = "Hospital Twin API"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API. The database pool opens on startup and closes on shutdown."""
    resolved = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved.log_level, resolved.secret_values())
        app.state.pool = await create_pool(resolved.database_url.get_secret_value())
        logger.info("Database pool opened")
        try:
            yield
        finally:
            await app.state.pool.close()
            logger.info("Database pool closed")

    app = FastAPI(title=APP_TITLE, version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.include_router(health_router)
    return app
