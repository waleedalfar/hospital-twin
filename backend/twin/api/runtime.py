"""Runs the simulation inside the API process (PROMPT.md §2): one tick per real second at 1x, written to the
database and broadcast to WebSocket clients after every tick."""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from twin.api.hub import Hub
from twin.common.ws import ActionName, EventsMessage, ScenarioName
from twin.db.pool import Pool
from twin.db.sim_writer import SimWriter, reset_run, write_audit
from twin.sim.config import SPEEDS
from twin.sim.engine import Simulation
from twin.sim.entities import PatientProfile
from twin.sim.scenarios import Scenario

logger = logging.getLogger(__name__)
WARMUP_FLUSH_TICKS = 240


class ControlError(Exception):
    """A sim control request is invalid."""


async def load_profiles(pool: Pool) -> list[PatientProfile]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, age, sex, comorbidity_count, conditions FROM patients ORDER BY id"
        )
    return [
        PatientProfile(r["id"], r["age"], r["sex"], r["comorbidity_count"], tuple(r["conditions"]))
        for r in rows
    ]


class SimRuntime:
    def __init__(self, sim: Simulation, pool: Pool, hub: Hub, speed: int = 1) -> None:
        if speed not in SPEEDS:
            raise ControlError(f"speed must be one of {SPEEDS}")
        self.sim = sim
        self.pool = pool
        self.hub = hub
        self.writer = SimWriter(sim.world)
        self.speed = speed
        self.paused = False
        self.frozen = False
        self.ready = False
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.ticks = 0

    # ---- lifecycle ------------------------------------------------------------------------------------

    async def prepare(self, reset: bool) -> None:
        """Start a new run: clear the previous run's rows (if `reset`) and simulate the warm-up period."""
        async with self.pool.acquire() as conn:
            if reset:
                await reset_run(conn)
            self.writer.add_all_staff()
            started = time.monotonic()
            ticks = 0
            while self.sim.now < self.sim.visible_start:
                self.writer.add(self.sim.tick())
                ticks += 1
                if ticks % WARMUP_FLUSH_TICKS == 0:
                    await self.writer.flush(conn)
                    await asyncio.sleep(0)
            await self.writer.flush(conn)
            await write_audit(
                conn,
                self.sim.now,
                "system",
                "sim_start",
                {"seed": self.sim.world.seed, "warmup_ticks": ticks},
            )
        logger.info("Warm-up done: %d sim minutes in %.1f s", ticks, time.monotonic() - started)
        self.ready = True

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="sim-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("Simulation loop stopped")
            self._task = None

    async def _loop(self) -> None:
        while True:
            if self.paused or self.frozen:
                self._wake.clear()
                await self._wake.wait()
                continue
            started = time.monotonic()
            await self.step()
            delay = 1.0 / self.speed - (time.monotonic() - started)
            if delay > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except TimeoutError:
                    continue
                self._wake.clear()

    async def step(self) -> None:
        """Advance one sim minute, write it, broadcast it."""
        emitted = self.sim.tick()
        self.ticks += 1
        self.writer.add(emitted)
        # Broadcast before any await: a snapshot is built between awaits, so it always reflects exactly the
        # ticks whose events have already been sent. Otherwise a client could receive events that its
        # snapshot already includes.
        self.broadcast(emitted)
        async with self.pool.acquire() as conn:
            await self.writer.flush(conn)

    def broadcast(self, emitted: list[Any]) -> None:
        for hospital_id in self.sim.world.hospitals:
            if not self.hub.has_hospital_clients(hospital_id):
                continue
            events = [e.event for e in emitted if e.hospital_id in (hospital_id, None)]
            snapshot_kpis = self.sim.snapshot(hospital_id, self.speed, self.paused, self.frozen).kpis
            message = EventsMessage(
                sim_time=self.sim.now,
                speed=self.speed,
                paused=self.paused,
                frozen=self.frozen,
                events=events,
                kpis=snapshot_kpis,
            )
            self.hub.publish_hospital(hospital_id, message.model_dump_json(by_alias=True))
        if self.hub.has_network_clients():
            self.hub.publish_network(self.network_json())

    def snapshot_json(self, hospital_id: str) -> str:
        return self.sim.snapshot(hospital_id, self.speed, self.paused, self.frozen).model_dump_json(
            by_alias=True
        )

    def network_json(self) -> str:
        return self.sim.network(self.speed, self.paused, self.frozen).model_dump_json(by_alias=True)

    # ---- control (each one is audited) -----------------------------------------------------------------

    async def audit(self, action: str, payload: dict[str, Any], actor: str = "user") -> None:
        async with self.pool.acquire() as conn:
            await write_audit(conn, self.sim.now, actor, action, payload)

    async def set_speed(self, speed: int) -> None:
        if speed not in SPEEDS:
            raise ControlError(f"speed must be one of {SPEEDS}")
        self.speed = speed
        self._wake.set()
        await self.audit("sim_speed", {"speed": speed})
        self._announce()

    async def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self._wake.set()
        await self.audit("sim_pause", {"paused": paused})
        self._announce()

    async def set_frozen(self, frozen: bool) -> None:
        self.frozen = frozen
        self._wake.set()
        await self.audit("sim_freeze", {"frozen": frozen})
        self._announce()

    def _announce(self) -> None:
        """Tell clients about a control change at once, even while paused, with an events message."""
        self.broadcast([])

    async def _publish_now(self) -> None:
        """Write and broadcast what a command emitted without waiting for the next tick."""
        emitted = self.sim.world.drain()
        self.writer.add(emitted)
        self.broadcast(emitted)
        async with self.pool.acquire() as conn:
            await self.writer.flush(conn)

    async def start_scenario(
        self, name: ScenarioName, hospital_id: str | None, lat: float | None, lon: float | None
    ) -> Scenario:
        scenario = self.sim.start_scenario(name, hospital_id, lat, lon)
        await self._publish_now()
        await self.audit(
            "scenario_start",
            {"id": scenario.id, "name": name, "hospital_id": scenario.hospital_id, **scenario.params},
        )
        return scenario

    async def stop_scenario(self, scenario_id: str) -> Scenario:
        scenario = self.sim.stop_scenario(scenario_id)
        await self._publish_now()
        await self.audit("scenario_stop", {"id": scenario.id, "name": scenario.name})
        return scenario

    async def apply_action(self, action: ActionName, params: dict[str, Any], actor: str) -> str:
        result = self.sim.apply_action(action, params)
        await self._publish_now()
        await self.audit(
            "action_applied", {"action": action, "params": params, "result": result}, actor=actor
        )
        return result


def warmup_delta(hours: float) -> timedelta:
    return timedelta(hours=hours)
