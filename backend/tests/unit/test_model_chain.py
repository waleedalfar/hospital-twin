"""Falling back across several Gemini models (GEMINI_MODEL=a,b,c)."""

import asyncio
import types as pytypes
from typing import Any

import pytest
from google.genai.errors import ClientError, ServerError

from tests.agent_helpers import busy_summary, fixture
from twin.agent import ask_llm, llm
from twin.agent.ask_llm import AskError, GeminiAsk, make_ask_llm
from twin.agent.llm import GeminiClient, make_client
from twin.agent.model_chain import DEFAULT_COOLDOWN_S, MISSING_COOLDOWN_S, QUOTA_COOLDOWN_S, ModelChain, cooldown_for

RETRY = (ClientError, ServerError, TimeoutError)


def test_the_list_is_parsed_in_order_without_blanks_duplicates_or_prefixes() -> None:
    assert ModelChain.parse(" a, models/b ,,a, c ").models == ["a", "b", "c"]
    assert ModelChain.parse("single").models == ["single"]
    assert ModelChain.parse("").models == [] and ModelChain.parse(None).models == []


def test_cooldowns_depend_on_why_the_model_failed() -> None:
    assert cooldown_for(ClientError(429, {"error": {"message": "quota"}})) == QUOTA_COOLDOWN_S
    assert cooldown_for(ClientError(404, {"error": {"message": "no such model"}})) == MISSING_COOLDOWN_S
    assert cooldown_for(ServerError(503, {"error": {"message": "overloaded"}})) == DEFAULT_COOLDOWN_S
    assert cooldown_for(TimeoutError()) == DEFAULT_COOLDOWN_S


async def test_the_first_working_model_is_used_and_failing_ones_are_skipped_next_time() -> None:
    now = [0.0]
    chain = ModelChain(["a", "b", "c"], clock=lambda: now[0])
    tried: list[str] = []

    async def call(model: str) -> str:
        tried.append(model)
        if model == "a":
            raise ClientError(429, {"error": {"message": "quota"}})
        return f"answer from {model}"

    assert await chain.run(call, RETRY) == "answer from b"
    assert tried == ["a", "b"] and chain.last_used == "b"
    tried.clear()
    assert await chain.run(call, RETRY) == "answer from b"
    assert tried == ["b"]  # a is cooling down, so it is not asked again
    now[0] = QUOTA_COOLDOWN_S + 1
    tried.clear()
    await chain.run(call, RETRY)
    assert tried == ["a", "b"]  # after the cooldown it gets another chance


async def test_cooling_models_are_still_tried_last_when_nothing_else_is_left() -> None:
    chain = ModelChain(["a", "b"], clock=lambda: 0.0)
    chain.failed_until = {"a": 100.0, "b": 100.0}
    assert chain.order() == ["a", "b"]
    chain.failed_until = {"a": 100.0}
    assert chain.order() == ["b", "a"]

    async def works(model: str) -> str:
        return model

    assert await chain.run(works, RETRY) == "b"


async def test_when_every_model_fails_the_last_error_is_raised() -> None:
    chain = ModelChain(["a", "b"], clock=lambda: 0.0)

    async def call(model: str) -> str:
        raise ServerError(503, {"error": {"message": f"{model} overloaded"}})

    with pytest.raises(ServerError, match="b overloaded"):
        await chain.run(call, RETRY)
    with pytest.raises(ValueError, match="No Gemini model"):
        await ModelChain([]).run(call, RETRY)


async def test_errors_that_are_not_about_the_model_are_not_swallowed() -> None:
    chain = ModelChain(["a", "b"])

    async def call(model: str) -> str:
        raise KeyError(model)

    with pytest.raises(KeyError):
        await chain.run(call, RETRY)
    assert chain.failed_until == {}


async def test_the_number_of_models_tried_is_limited() -> None:
    chain = ModelChain(["a", "b", "c", "d"], clock=lambda: 0.0)
    tried: list[str] = []

    async def call(model: str) -> str:
        tried.append(model)
        raise TimeoutError

    with pytest.raises(TimeoutError):
        await chain.run(call, RETRY, max_tries=2)
    assert tried == ["a", "b"]


# ---- the clients -------------------------------------------------------------------------------------------


class FakeModels:
    def __init__(self, behaviour: dict[str, Any]) -> None:
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append(model)
        result = self.behaviour[model]
        if isinstance(result, Exception):
            raise result
        if result == "hang":
            await asyncio.sleep(60)
        return pytypes.SimpleNamespace(text=result, function_calls=[], candidates=[])


def patch_genai(monkeypatch: pytest.MonkeyPatch, behaviour: dict[str, Any]) -> FakeModels:
    models = FakeModels(behaviour)

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.aio = pytypes.SimpleNamespace(models=models)

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", FakeClient)
    return models


async def test_the_agent_client_moves_to_the_next_model_on_quota_overload_and_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    models = patch_genai(
        monkeypatch,
        {
            "m1": ClientError(429, {"error": {"message": "quota"}}),
            "m2": ServerError(503, {"error": {"message": "overloaded"}}),
            "m3": "hang",
            "m4": fixture("valid_divert.json"),
        },
    )
    monkeypatch.setattr(llm, "TIMEOUT_S", 0.05)
    client = make_client("key", "m1,m2,m3,m4")
    assert isinstance(client, GeminiClient)
    text = await client.generate(llm.build_prompt(busy_summary()))
    assert "divert_ambulances" in text and models.calls == ["m1", "m2", "m3", "m4"]
    await client.generate("again")
    assert models.calls[4:] == ["m4"]  # the failing models are skipped while they cool down


async def test_empty_replies_count_as_a_failed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    models = patch_genai(monkeypatch, {"m1": "", "m2": '{"recommendations": []}'})
    client = make_client("key", "m1,m2")
    assert client is not None and await client.generate("x") == '{"recommendations": []}'
    assert models.calls == ["m1", "m2"]


async def test_if_every_model_fails_the_error_reaches_the_service_which_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_genai(monkeypatch, {"m1": ClientError(429, {"error": {"message": "quota"}}), "m2": ClientError(429, {"error": {"message": "quota"}})})
    client = make_client("key", "m1,m2")
    assert client is not None
    with pytest.raises(ClientError):
        await client.generate("x")


async def test_the_ask_client_falls_back_too_and_limits_the_tries(monkeypatch: pytest.MonkeyPatch) -> None:
    good = '{"answer_text": "The wait is 5 minutes.", "entity_ids": [], "cited_metrics": []}'
    models = patch_genai(
        monkeypatch,
        {"m1": ServerError(500, {"error": {"message": "boom"}}), "m2": "not json", "m3": good, "m4": good},
    )

    async def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {}

    asker = make_ask_llm("key", "m1,m2,m3,m4")
    assert isinstance(asker, GeminiAsk)
    out = await asker.ask("wait?", "mercy", call)
    assert out.answer_text == "The wait is 5 minutes." and models.calls == ["m1", "m2", "m3"]
    models.behaviour.update({"m3": ServerError(500, {"error": {"message": "boom"}}), "m4": good})
    asker.chain.failed_until.clear()
    models.calls.clear()
    with pytest.raises(ServerError):
        await asker.ask("wait?", "mercy", call)  # three tries, then it gives up and the caller falls back
    assert models.calls == ["m1", "m2", "m3"]
    assert ask_llm.MAX_ASK_TRIES == 3 and AskError is not None


def test_one_shared_chain_serves_both_features_and_no_models_means_no_client() -> None:
    chain = ModelChain.parse("a,b")
    one, two = make_client("key", None, chain), make_ask_llm("key", None, chain)
    assert isinstance(one, GeminiClient) and isinstance(two, GeminiAsk) and one.chain is chain and two.chain is chain
    assert make_client("key", " , ") is None and make_ask_llm("key", "") is None and make_ask_llm(None, "a") is None
