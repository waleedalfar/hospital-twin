"""A local model as the agent's second choice (OLLAMA_URL, OLLAMA_MODEL). Ollama runs on the same machine or network,
needs no API key and no quota, so it answers when Gemini hangs or is unavailable. The rules engine remains the last
resort. Replies go through the same parser and grounding check as Gemini's."""

import logging
from dataclasses import dataclass

import httpx
from google.genai.errors import APIError

from twin.agent.llm import LLMClient

logger = logging.getLogger(__name__)
TIMEOUT_S = 45.0  # a small model on a CPU is slow


@dataclass
class OllamaClient:
    base_url: str
    model: str
    transport: httpx.AsyncBaseTransport | None = None

    async def generate(self, prompt: str) -> str:
        """The model's JSON text for `prompt`. Raises ValueError on an empty reply and httpx errors on network problems."""
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self.transport) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                },
            )
            response.raise_for_status()
            text = str(response.json().get("message", {}).get("content", "")).strip()
        if not text:
            raise ValueError("Ollama returned no text")
        return text


@dataclass
class FallbackLLM:
    """Tries the first client, then the second if the first raises. Used as one `LLMClient` by the agent service."""

    primary: LLMClient
    secondary: LLMClient

    async def generate(self, prompt: str) -> str:
        try:
            return await self.primary.generate(prompt)
        except (APIError, httpx.HTTPError, TimeoutError, OSError, ValueError) as error:
            logger.warning("The first model failed (%s: %s); trying the local model", type(error).__name__, str(error)[:200])
        return await self.secondary.generate(prompt)


def make_ollama(url: str | None, model: str | None) -> OllamaClient | None:
    if not url or not model:
        return None
    return OllamaClient(url, model)


def combine(gemini: LLMClient | None, ollama: LLMClient | None) -> LLMClient | None:
    """Gemini first, the local model behind it; whichever exists alone; None if neither."""
    if gemini is not None and ollama is not None:
        return FallbackLLM(gemini, ollama)
    return gemini or ollama
