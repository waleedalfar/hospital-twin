"""The operations agent service (PROMPT.md §9).

Runs for a hospital every 15 sim minutes, immediately when a scenario starts, and when a unit is projected
full within 4 hours. Gemini is asked first (when configured); its output is validated and grounded, retried
once with the errors, and replaced by the rules engine if it errors, times out or fails twice. Recommendations
are stored in `agent_recs`; approving one applies the action to the simulation and writes the audit log.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from google.genai.errors import APIError

from twin.agent import rules
from twin.agent.llm import LLMClient, build_prompt
from twin.agent.schema import FALLBACK_LABEL, AgentOutput, Recommendation, Source, parse_agent_output
from twin.agent.summary import Summary, build_summary
from twin.agent.validator import apply_params, validate
from twin.common.ws import AgentRecEvent, AgentRecModel
from twin.common.ws import CitedMetric as WsCited
from twin.db.pool import Pool
from twin.db.sim_writer import write_audit
from twin.sim.actions import ActionError
from twin.sim.engine import Simulation

logger = logging.getLogger(__name__)
EXPIRE_AFTER_MIN = 120.0
FULL_WITHIN_H = 4.0
MIN_LLM_INTERVAL_S = 20.0
DB_ERRORS: tuple[type[Exception], ...] = (OSError, TimeoutError)


class RecError(Exception):
    """A recommendation cannot be approved or dismissed (unknown, already handled, or no longer valid)."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class AgentService:
    sim: Simulation
    pool: Pool
    llm: LLMClient | None
    apply_action: Any  # async (action, params, actor) -> str, from the runtime (applies and audits)
    publish: Any  # async () -> None, flushes the simulation's pending events to clients and the database
    min_llm_interval_s: float = MIN_LLM_INTERVAL_S
    clock: Any = time.monotonic
    counter: int = 0
    last_llm_call: dict[str, float] = field(default_factory=dict)
    running: set[str] = field(default_factory=set)
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    llm_calls: int = 0

    # ---- triggers ------------------------------------------------------------------------------------------------

    def projected_full(self, s: Summary) -> bool:
        return any(u.hours_until_full is not None and u.hours_until_full <= FULL_WITHIN_H for u in s.units)

    def schedule(self, hospital_ids: list[str], reason: str) -> None:
        """Run the agent in the background for each hospital (never two runs at once for one hospital)."""
        for hospital_id in hospital_ids:
            if hospital_id in self.running:
                continue
            self.running.add(hospital_id)
            task = asyncio.create_task(self._run_guarded(hospital_id, reason), name=f"agent-{hospital_id}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    def tick(self, minute: int, interval: int = 15) -> None:
        """Called every sim minute: run every `interval` minutes, with the reason recorded."""
        if minute % interval:
            return
        ids = sorted(self.sim.world.hospitals)
        full = [h for h in ids if self.projected_full(build_summary(self.sim.world, self.sim.ml, h))]
        self.schedule(full, "projected_full")
        self.schedule([h for h in ids if h not in full], "periodic")

    async def stop(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _run_guarded(self, hospital_id: str, reason: str) -> None:
        try:
            await self.run(hospital_id, reason)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("The agent failed for %s (%s)", hospital_id, reason)
        finally:
            self.running.discard(hospital_id)

    # ---- one run -------------------------------------------------------------------------------------------------

    async def run(self, hospital_id: str, reason: str) -> list[AgentRecModel]:
        """Produce recommendations for a hospital and store the new ones. Returns the new ones."""
        await self.expire_old()
        summary = build_summary(self.sim.world, self.sim.ml, hospital_id)
        output, source = await self.produce(summary, reason)
        pending = await self.pending_keys(hospital_id)
        created: list[AgentRecModel] = []
        for rec in output.recommendations:
            key = (rec.action, tuple(sorted(rec.targets)))
            if key in pending:
                continue
            created.append(await self.store(rec, source))
            pending.add(key)
        if created:
            await self.publish()
        return created

    async def produce(self, summary: Summary, reason: str) -> tuple[AgentOutput, Source]:
        """Gemini first when allowed; the rules engine otherwise or on any failure."""
        if self.llm is not None and self.clock() - self.last_llm_call.get(summary.hospital_id, -1e9) >= self.min_llm_interval_s:
            self.last_llm_call[summary.hospital_id] = self.clock()
            output = await self.ask_llm(summary, reason)
            if output is not None:
                return output, "gemini"
        return rules.recommend(summary), "rules"

    async def ask_llm(self, summary: Summary, reason: str) -> AgentOutput | None:
        errors: list[str] = []
        for attempt in (1, 2):
            self.llm_calls += 1
            try:
                assert self.llm is not None  # noqa: S101 - callers check
                text = await self.llm.generate(build_prompt(summary, errors or None))
            except (APIError, TimeoutError, OSError, ValueError) as error:
                logger.exception("Gemini failed for %s (%s, attempt %d)", summary.hospital_id, reason, attempt)
                await self.audit("agent_llm_error", {"hospital_id": summary.hospital_id, "attempt": attempt, "error": str(error)[:300]})
                return None
            try:
                output = parse_agent_output(text)
                errors = validate(output, summary)
            except ValueError as error:
                errors = [str(error)]  # an unreadable reply is retried once with what is wrong with it, like a failed check
            if not errors:
                return output
            await self.audit(
                "agent_validation_failed",
                {"hospital_id": summary.hospital_id, "attempt": attempt, "errors": errors[:8]},
            )
        return None

    # ---- storage -------------------------------------------------------------------------------------------------

    def model_of(self, rec: Recommendation, source: Source, status: str, created: datetime) -> AgentRecModel:
        return AgentRecModel(
            id=rec.id,
            hospital_id=rec.hospital_id,
            action=rec.action,
            targets=rec.targets,
            params=dict(rec.params),
            rationale=rec.rationale,
            cited_metrics=[WsCited(name=m.name, value=m.value) for m in rec.cited_metrics],
            source=source,
            status=status,
            created=created,
            label=FALLBACK_LABEL if source == "rules" else None,
        )

    async def store(self, rec: Recommendation, source: Source) -> AgentRecModel:
        self.counter += 1
        stored = rec.model_copy(update={"id": f"REC-{self.counter}"})
        when = self.sim.now
        model = self.model_of(stored, source, "pending", when)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent_recs (time, id, hospital_id, source, payload, status) VALUES ($1, $2, $3, $4, $5::jsonb, 'pending')",
                when,
                model.id,
                model.hospital_id,
                source,
                model.model_dump_json(),
            )
        self.sim.world.emit(model.hospital_id, AgentRecEvent(time=self.sim.world.time(), rec=model))
        await self.audit(
            "agent_rec",
            {
                "id": model.id,
                "hospital_id": model.hospital_id,
                "action": model.action,
                "source": source,
                "targets": model.targets,
            },
        )
        return model

    async def pending_keys(self, hospital_id: str) -> set[tuple[str, tuple[str, ...]]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT payload FROM agent_recs WHERE hospital_id = $1 AND status = 'pending'", hospital_id)
        out: set[tuple[str, tuple[str, ...]]] = set()
        for r in rows:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            out.add((p["action"], tuple(sorted(p["targets"]))))
        return out

    async def expire_old(self) -> None:
        cutoff = self.sim.now.timestamp() - EXPIRE_AFTER_MIN * 60
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE agent_recs SET status = 'expired' WHERE status = 'pending' AND time < to_timestamp($1)",
                cutoff,
            )

    async def audit(self, action: str, payload: dict[str, Any], actor: str = "agent") -> None:
        async with self.pool.acquire() as conn:
            await write_audit(conn, self.sim.now, actor, action, payload)

    async def list(self, hospital_id: str | None = None, status: str | None = None, limit: int = 50) -> list[AgentRecModel]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload, status FROM agent_recs
                WHERE ($1::text IS NULL OR hospital_id = $1) AND ($2::text IS NULL OR status = $2)
                ORDER BY time DESC, id DESC LIMIT $3
                """,
                hospital_id,
                status,
                limit,
            )
        out: list[AgentRecModel] = []
        for r in rows:
            payload = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            out.append(AgentRecModel.model_validate({**payload, "status": r["status"]}))
        return out

    async def get(self, rec_id: str) -> AgentRecModel:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT payload, status FROM agent_recs WHERE id = $1 ORDER BY time DESC LIMIT 1", rec_id)
        if row is None:
            raise RecError(f"Unknown recommendation {rec_id}", 404)
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        return AgentRecModel.model_validate({**payload, "status": row["status"]})

    async def set_status(self, rec: AgentRecModel, status: str) -> AgentRecModel:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE agent_recs SET status = $2 WHERE id = $1", rec.id, status)
        updated = rec.model_copy(update={"status": status})
        self.sim.world.emit(rec.hospital_id, AgentRecEvent(time=self.sim.world.time(), rec=updated))
        return updated

    # ---- human decisions -------------------------------------------------------------------------------------------

    async def approve(self, rec_id: str, actor: str = "user") -> tuple[AgentRecModel, str]:
        """Apply a pending recommendation to the simulation. Raises RecError if it cannot be applied."""
        rec = await self.get(rec_id)
        if rec.status != "pending":
            raise RecError(f"{rec_id} is already {rec.status}", 409)
        schema_rec = Recommendation(
            id=rec.id,
            hospital_id=rec.hospital_id,
            action=rec.action,
            targets=rec.targets,
            params=dict(rec.params),
            rationale=rec.rationale,
            cited_metrics=[],
        )
        try:
            result = await self.apply_action(rec.action, apply_params(schema_rec), actor)
        except ActionError as error:
            raise RecError(f"Cannot apply {rec_id}: {error}", 409) from error
        updated = await self.set_status(rec, "approved")
        await self.audit(
            "agent_rec_approved",
            {"id": rec.id, "action": rec.action, "hospital_id": rec.hospital_id, "result": result},
            actor,
        )
        await self.publish()
        return updated, result

    async def dismiss(self, rec_id: str, actor: str = "user") -> AgentRecModel:
        rec = await self.get(rec_id)
        if rec.status != "pending":
            raise RecError(f"{rec_id} is already {rec.status}", 409)
        updated = await self.set_status(rec, "dismissed")
        await self.audit("agent_rec_dismissed", {"id": rec.id, "action": rec.action, "hospital_id": rec.hospital_id}, actor)
        await self.publish()
        return updated
