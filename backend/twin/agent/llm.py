"""Gemini client (PROMPT.md §9). The model name and key come from the environment (`GEMINI_MODEL`,
`GEMINI_API_KEY`); no model name is hardcoded. Output is requested as JSON that follows the `AgentOutput`
schema, with a 10 second timeout."""

import asyncio
import json
import logging
from typing import Protocol

from google.genai.errors import APIError

from twin.agent.model_chain import ModelChain
from twin.agent.schema import AgentOutput
from twin.agent.summary import Summary, flat_metrics

logger = logging.getLogger(__name__)
TIMEOUT_S = 10.0

SYSTEM = (
    "You are the operations agent for a hospital network. From the JSON summary of one hospital, recommend at most "
    "four actions that a human operations manager can approve. Allowed actions: divert_ambulances (hospital_id is the "
    "hospital that diverts, targets are other OPEN hospitals, params.duration_min 15-480), expedite_discharge "
    "(targets are patient ids from expedite_candidates only, at most 5), move_patient (one patient id from the input, "
    "params.bed_id an open bed from open_beds), call_in_staff (target one unit of ER, WARD, ICU, REC; params.count 1-4), "
    "hold_bed (target one open bed from open_beds; params.minutes 15-240). Cite 2-5 metrics per recommendation in "
    "cited_metrics using ONLY names from the list 'metrics' and their exact values. Do not invent ids or numbers. "
    "If nothing needs doing, return an empty list."
)


class LLMClient(Protocol):
    async def generate(self, prompt: str) -> str:
        """Return the model's JSON text for `prompt`."""
        ...


def build_prompt(s: Summary, errors: list[str] | None = None) -> str:
    body = {"summary": json.loads(s.model_dump_json()), "metrics": flat_metrics(s)}
    text = f"{SYSTEM}\n\nINPUT:\n{json.dumps(body, indent=1)}"
    if errors:
        text += "\n\nYour previous answer was rejected for these reasons. Fix them and answer again:\n- " + "\n- ".join(errors)
    return text


class GeminiClient:
    def __init__(self, api_key: str, chain: ModelChain) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.chain = chain

    async def generate(self, prompt: str) -> str:
        from google.genai import types

        async def one(model: str) -> str:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=AgentOutput, temperature=0.2),
                ),
                timeout=TIMEOUT_S,
            )
            if not response.text:
                raise ValueError("Gemini returned no text")
            return response.text

        return await self.chain.run(one, (APIError, TimeoutError, OSError, ValueError))


def make_client(api_key: str | None, models: str | None, chain: ModelChain | None = None) -> LLMClient | None:
    """A Gemini client if the key and at least one model are configured, else None (rules engine only). `models` is
    one name or a comma-separated list, tried in order."""
    chain = chain or ModelChain.parse(models)
    if not api_key or not chain.models:
        if api_key and not chain.models:
            logger.warning("GEMINI_API_KEY is set but GEMINI_MODEL is not; using the rules engine")
        return None
    return GeminiClient(api_key, chain)
