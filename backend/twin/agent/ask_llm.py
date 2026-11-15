"""Gemini function calling for "Ask Hospital Twin" (PROMPT.md §9.1). The model may call only the six read-only tools."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from google.genai.errors import APIError

from twin.agent.grounding import AskOutput
from twin.agent.model_chain import ModelChain
from twin.agent.tools import TOOL_SPECS

logger = logging.getLogger(__name__)
TIMEOUT_S = 12.0  # per model; the chain tries at most MAX_ASK_TRIES of them
MAX_ASK_TRIES = 3
MAX_TURNS = 5

SYSTEM = (
    "You answer questions from a hospital operations manager about one hospital network. Use ONLY the provided tools to "
    "get facts; never guess. When you have what you need, reply with ONLY a JSON object: "
    '{"answer_text": string, "entity_ids": [patient ids like P-0412 that the answer is about], '
    '"cited_metrics": [{"name": string, "value": number}]}. Every number and id in answer_text, entity_ids and '
    "cited_metrics must appear in a tool result. Keep the answer under 60 words, in plain spoken language."
)

ToolCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class AskLLM(Protocol):
    async def ask(self, question: str, hospital_id: str, call: ToolCall, errors: list[str] | None = None) -> AskOutput: ...


class AskError(Exception):
    """The model's reply could not be turned into an answer."""


def parse_answer(text: str) -> AskOutput:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        return AskOutput.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValueError) as error:
        raise AskError(f"The model's reply is not a valid answer: {error}") from error


class GeminiAsk:
    def __init__(self, api_key: str, chain: ModelChain) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.chain = chain

    async def ask(self, question: str, hospital_id: str, call: ToolCall, errors: list[str] | None = None) -> AskOutput:
        async def one(model: str) -> AskOutput:
            return await asyncio.wait_for(self._run(model, question, hospital_id, call, errors), timeout=TIMEOUT_S)

        return await self.chain.run(one, (APIError, TimeoutError, OSError, AskError), max_tries=MAX_ASK_TRIES)

    async def _run(self, model: str, question: str, hospital_id: str, call: ToolCall, errors: list[str] | None) -> AskOutput:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**spec) for spec in TOOL_SPECS])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )
        prompt = f"Current hospital: {hospital_id}\nQuestion: {question}"
        if errors:
            prompt += "\nYour previous answer was rejected for these reasons; fix them:\n- " + "\n- ".join(errors)
        contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        for _ in range(MAX_TURNS):
            response = await self._client.aio.models.generate_content(model=model, contents=contents, config=config)
            calls = response.function_calls or []
            if not calls:
                if not response.text:
                    raise AskError("Gemini returned no text")
                return parse_answer(response.text)
            if response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)
            parts = []
            for fc in calls:
                result = await call(str(fc.name), dict(fc.args or {}))
                parts.append(types.Part.from_function_response(name=str(fc.name), response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        raise AskError("Gemini kept calling tools without answering")


def make_ask_llm(api_key: str | None, models: str | None, chain: ModelChain | None = None) -> AskLLM | None:
    chain = chain or ModelChain.parse(models)
    if not api_key or not chain.models:
        return None
    return GeminiAsk(api_key, chain)
