"""`POST /agent/ask` (PROMPT.md §9.1): a question, answered with the read-only tools.

Gemini gets the six tools through function calling. Its answer must pass the grounding check (one retry with the
errors). If Gemini is not configured, errors, times out or fails twice, the deterministic intent parser answers and
the response says so."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from google.genai.errors import APIError
from pydantic import BaseModel, ValidationError

from twin.agent.ask_llm import AskError, AskLLM
from twin.agent.grounding import AskOutput, check_answer
from twin.agent.intents import FALLBACK_ASK_LABEL, HELP, Intent, compose, parse_intent
from twin.agent.schema import CitedMetric
from twin.agent.tools import ToolBox, ToolError
from twin.db.pool import Pool
from twin.sim.engine import Simulation

logger = logging.getLogger(__name__)
MAX_QUESTION = 400


class ToolRun(BaseModel):
    name: str
    args: dict[str, Any]


class AskResponse(BaseModel):
    answer_text: str
    entity_ids: list[str]
    cited_metrics: list[CitedMetric]
    source: Literal["gemini", "fallback"]
    label: str | None
    tools: list[ToolRun]


class AskRefusedError(Exception):
    """The question cannot be answered at all (empty, too long, unknown hospital)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class AskService:
    sim: Simulation
    pool: Pool
    llm: AskLLM | None

    async def ask(self, question: str, hospital_id: str) -> AskResponse:
        question = question.strip()
        if not question:
            raise AskRefusedError("Ask a question")
        if len(question) > MAX_QUESTION:
            raise AskRefusedError(f"Questions are limited to {MAX_QUESTION} characters")
        if hospital_id not in self.sim.world.hospitals:
            raise AskRefusedError(f"Unknown hospital {hospital_id}", 404)
        box = ToolBox(self.sim, self.pool)
        if self.llm is not None:
            answered = await self.ask_gemini(question, hospital_id, box)
            if answered is not None:
                return answered
        return await self.ask_fallback(question, hospital_id, box)

    async def ask_gemini(self, question: str, hospital_id: str, box: ToolBox) -> AskResponse | None:
        assert self.llm is not None  # noqa: S101 - the caller checks
        errors: list[str] | None = None
        for attempt in (1, 2):
            runs: list[ToolRun] = []
            results: list[dict[str, Any]] = []

            async def call(name: str, args: dict[str, Any], runs: list[ToolRun] = runs, results: list[dict[str, Any]] = results) -> dict[str, Any]:
                runs.append(ToolRun(name=name, args=args))
                try:
                    result = await box.call(name, args)
                except ToolError as error:
                    result = {"error": str(error)}
                results.append(result)
                return result

            try:
                output = await self.llm.ask(question, hospital_id, call, errors)
            except (APIError, TimeoutError, OSError, AskError, ValueError, ValidationError):
                logger.exception("Gemini could not answer %r (attempt %d)", question, attempt)
                return None
            errors = check_answer(output, results) if results else ["the answer used no tool results"]
            if not errors:
                return AskResponse(
                    answer_text=output.answer_text,
                    entity_ids=output.entity_ids,
                    cited_metrics=output.cited_metrics,
                    source="gemini",
                    label=None,
                    tools=runs,
                )
            logger.warning("Gemini's answer was not grounded (attempt %d): %s", attempt, errors[:5])
        return None

    async def ask_fallback(self, question: str, hospital_id: str, box: ToolBox) -> AskResponse:
        intent: Intent | None = parse_intent(question, hospital_id)
        if intent is None:
            return AskResponse(answer_text=HELP, entity_ids=[], cited_metrics=[], source="fallback", label=FALLBACK_ASK_LABEL, tools=[])
        try:
            result = await box.call(intent.tool, intent.args)
        except ToolError as error:
            return AskResponse(
                answer_text=str(error),
                entity_ids=[],
                cited_metrics=[],
                source="fallback",
                label=FALLBACK_ASK_LABEL,
                tools=[ToolRun(name=intent.tool, args=intent.args)],
            )
        name = (
            self.sim.world.hospitals[result.get("hospital", hospital_id)].name
            if result.get("hospital")
            else self.sim.world.hospitals[hospital_id].name
        )
        output: AskOutput = compose(intent, result, name)
        problems = check_answer(output, [result])
        if problems:  # the templates are meant to be grounded by construction; if not, say so instead of answering
            logger.error("The fallback answer for %s is not grounded: %s", intent.tool, problems)
            raise AskRefusedError(f"The fallback answer could not be verified: {problems[0]}", 500)
        return AskResponse(
            answer_text=output.answer_text,
            entity_ids=output.entity_ids,
            cited_metrics=output.cited_metrics,
            source="fallback",
            label=FALLBACK_ASK_LABEL,
            tools=[ToolRun(name=intent.tool, args=intent.args)],
        )
