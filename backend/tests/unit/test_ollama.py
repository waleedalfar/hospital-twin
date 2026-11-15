"""The local model (Ollama) behind Gemini: no key, used when Gemini fails or hangs."""

import asyncio
import json

import httpx
import pytest
from google.genai.errors import ClientError

from tests.agent_helpers import busy_summary, fixture
from twin.agent import llm
from twin.agent.llm import GeminiClient, build_prompt
from twin.agent.model_chain import ModelChain
from twin.agent.ollama import FallbackLLM, OllamaClient, combine, make_ollama
from twin.agent.schema import parse_agent_output
from twin.agent.validator import validate


def transport(reply: dict[str, object] | None = None, status: int = 200, seen: list[dict[str, object]] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(status, json=reply or {})

    return httpx.MockTransport(handler)


async def test_the_request_asks_for_json_without_a_key_and_returns_the_message() -> None:
    seen: list[dict[str, object]] = []
    client = OllamaClient(
        "http://ollama:11434/",
        "qwen2.5:1.5b",
        transport(seen=seen, reply={"message": {"role": "assistant", "content": fixture("valid_divert.json")}}),
    )
    text = await client.generate(build_prompt(busy_summary()))
    request = seen[0]
    assert request["url"] == "http://ollama:11434/api/chat"
    body = request["body"]
    assert isinstance(body, dict) and body["model"] == "qwen2.5:1.5b" and body["format"] == "json" and body["stream"] is False
    assert not validate(parse_agent_output(text), busy_summary())  # its answer goes through the same checks as Gemini's


async def test_empty_replies_and_http_errors_are_errors() -> None:
    with pytest.raises(ValueError, match="no text"):
        await OllamaClient("http://x", "m", transport({"message": {"content": "  "}})).generate("p")
    with pytest.raises(httpx.HTTPStatusError):
        await OllamaClient("http://x", "m", transport(status=500)).generate("p")


class Down:
    async def generate(self, prompt: str) -> str:
        raise ClientError(429, {"error": {"message": "quota"}})


class Slow:
    async def generate(self, prompt: str) -> str:
        await asyncio.sleep(60)
        return "never"


class Works:
    def __init__(self, text: str = "ok") -> None:
        self.text, self.calls = text, 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.text


async def test_the_local_model_answers_when_the_first_one_fails() -> None:
    local = Works("from the local model")
    assert await FallbackLLM(Down(), local).generate("p") == "from the local model" and local.calls == 1
    first = Works("from gemini")
    local2 = Works()
    assert await FallbackLLM(first, local2).generate("p") == "from gemini" and local2.calls == 0


async def test_the_local_model_error_reaches_the_caller_so_the_rules_engine_can_take_over() -> None:
    with pytest.raises(ClientError):
        await FallbackLLM(Works(), Down()).secondary.generate("p")
    with pytest.raises(ClientError):
        await FallbackLLM(Down(), Down()).generate("p")


async def test_a_hanging_gemini_is_cut_off_and_the_local_model_takes_over(monkeypatch: pytest.MonkeyPatch) -> None:
    import types as pytypes

    import google.genai as genai

    class Hangs:
        async def generate_content(self, **_: object) -> object:
            await asyncio.sleep(60)
            return pytypes.SimpleNamespace(text="never")

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.aio = pytypes.SimpleNamespace(models=Hangs())

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(llm, "TIMEOUT_S", 5.0)
    monkeypatch.setattr(llm, "TOTAL_TIMEOUT_S", 0.1)
    gemini = GeminiClient("key", ModelChain(["a", "b", "c"]))
    local = Works("local answer")
    assert await FallbackLLM(gemini, local).generate("p") == "local answer"


def test_the_pieces_combine_in_the_right_order_and_need_both_settings() -> None:
    gemini, local = Works("g"), Works("l")
    assert combine(gemini, local) == FallbackLLM(gemini, local)
    assert combine(gemini, None) is gemini and combine(None, local) is local and combine(None, None) is None
    assert make_ollama(None, "m") is None and make_ollama("http://x", None) is None and make_ollama("", "m") is None
    made = make_ollama("http://x", "m")
    assert isinstance(made, OllamaClient) and made.model == "m"
