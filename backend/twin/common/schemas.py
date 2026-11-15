"""Pydantic models for API payloads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Body of `GET /health`. When the database check fails, `status` is "degraded" and `error` is set."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    timescaledb_version: str | None = None
    migrations_applied: int | None = None
    error: str | None = None
    sim: Literal["running", "paused", "frozen", "starting", "off"] = "off"
    sim_time: datetime | None = None
    sim_error: str | None = None
    ml: Literal["ready", "missing", "off"] = "off"
    ml_version: str | None = None
