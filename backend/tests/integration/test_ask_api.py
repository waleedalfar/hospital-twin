"""The six tools and `POST /agent/ask` through the real database and API (PROMPT.md §9.1)."""

from typing import Any

import pytest

from tests.integration.test_ml_api import app_client
from tests.integration.test_sim_db import seed_patients
from twin.agent.ask import AskService
from twin.agent.ask_llm import AskError, ToolCall
from twin.agent.grounding import AskOutput
from twin.agent.tools import TOOL_NAMES, ToolBox, ToolError


class ScriptedAsk:
    """Stands in for Gemini function calling: calls the given tools, then returns the given answers in order."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]], *answers: AskOutput | Exception) -> None:
        self.calls, self.answers = calls, list(answers)
        self.errors_seen: list[list[str] | None] = []

    async def ask(self, question: str, hospital_id: str, call: ToolCall, errors: list[str] | None = None) -> AskOutput:
        self.errors_seen.append(errors)
        for name, args in self.calls:
            await call(name, args)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


async def warmed(client: Any, rt: Any, steps: int = 40) -> None:
    for _ in range(steps):
        await rt.step()


def ask_service(app: Any) -> AskService:
    service = app.state.ask
    assert isinstance(service, AskService)
    return service


async def test_every_tool_answers_from_the_live_state(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt)
        box = ToolBox(rt.sim, app.state.pool)
        state = (await client.get("/hospitals/mercy/state")).json()
        scored = sorted((e for e in state["entities"] if e["kind"] == "patient" and e["risk"]), key=lambda e: -e["risk"]["score"])

        risky = await box.call("list_high_risk_patients", {"hospital": "mercy", "limit": 3})
        assert [p["patient_id"] for p in risky["patients"]] == [e["id"] for e in scored[:3]]
        assert risky["patients"][0]["score"] == round(scored[0]["risk"]["score"], 2)
        icu = await box.call("list_high_risk_patients", {"hospital": "mercy", "unit": "icu", "limit": 50})
        assert len(icu["patients"]) <= 20 and all(p["unit"] == "ICU" for p in icu["patients"]) and icu["unit"] == "ICU"

        occupancy = await box.call("get_occupancy", {"hospital": "mercy"})
        beds = {b["id"]: b for b in state["beds"]}
        for row in occupancy["units"]:
            mine = [b for b in beds.values() if b["id"].startswith(row["unit"] + "-")]
            assert row["occupied"] == sum(1 for b in mine if b["state"] == "occupied") and row["capacity"] == len(mine)
        assert [r["unit"] for r in (await box.call("get_occupancy", {"hospital": "mercy", "unit": "WARD"}))["units"]] == ["WARD"]

        forecast = await box.call("get_forecast", {"hospital": "mercy"})
        stored = (await client.get("/forecast/mercy")).json()
        assert forecast["forecast_available"] and forecast["horizon_h"] == 6
        assert [a["expected"] for a in forecast["arrivals"]] == [round(a["expected"], 1) for a in stored["arrivals"]]
        assert set(forecast["hours_until_full"]) == {"ER", "WARD", "ICU", "REC"}
        assert set((await box.call("get_forecast", {"hospital": "mercy", "unit": "ICU"}))["hours_until_full"]) == {"ICU"}

        wait = await box.call("get_er_wait", {"hospital": "mercy"})
        assert wait["er_wait_min"] == round(state["kpis"]["er_wait_min"], 1) and wait["waiting"] == state["kpis"]["waiting"]

        staffing = await box.call("get_staffing", {"hospital": "mercy", "unit": "ICU"})
        assert staffing["units"][0]["unit"] == "ICU" and staffing["units"][0]["nurses"] >= 0 and staffing["units"][0]["required"] >= 0
        assert len((await box.call("get_staffing", {"hospital": "mercy"}))["units"]) == 4

        found = await box.call("find_patient", {"patient_id": scored[0]["id"].lower()})
        assert found["found"] and found["hospital"] == "mercy" and found["score"] == round(scored[0]["risk"]["score"], 2)
        assert (await box.call("find_patient", {"patient_id": "P-9999"})) == {"found": False, "patient_id": "P-9999"}
        assert len(TOOL_NAMES) == 6


async def test_tools_refuse_unknown_names_hospitals_units_and_arguments(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, app):
        box = ToolBox(rt.sim, app.state.pool)
        for name, args, message in [
            ("delete_everything", {}, "Unknown tool"),
            ("get_er_wait", {"hospital": "atlantis"}, "Unknown hospital"),
            ("get_occupancy", {"hospital": "mercy", "unit": "SPA"}, "Unknown unit"),
            ("get_er_wait", {"hospital": "mercy", "colour": "red"}, "Bad arguments"),
            ("find_patient", {}, "Bad arguments"),
        ]:
            with pytest.raises(ToolError, match=message):
                await box.call(name, args)


async def test_the_tools_do_not_change_the_simulation(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt, 20)
        before = (await client.get("/hospitals/mercy/state")).json()
        box = ToolBox(rt.sim, app.state.pool)
        for name in TOOL_NAMES:
            await box.call(name, {"patient_id": "P-0001"} if name == "find_patient" else {"hospital": "mercy"})
        assert (await client.get("/hospitals/mercy/state")).json() == before


async def test_the_endpoint_answers_with_the_fallback_when_gemini_is_not_configured(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        await warmed(client, rt)
        state = (await client.get("/hospitals/mercy/state")).json()
        icu = sorted(
            (e for e in state["entities"] if e["kind"] == "patient" and e["risk"] and (e["location"]["bed"] or "").startswith("ICU")),
            key=lambda e: -e["risk"]["score"],
        )
        response = await client.post("/agent/ask", json={"question": "who is most likely to crash in the ICU", "hospital_id": "mercy"})
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "fallback" and body["label"] == "Fallback intent parser — Gemini unavailable"
        assert body["tools"] == [{"name": "list_high_risk_patients", "args": {"hospital": "mercy", "unit": "ICU", "limit": 3}}]
        if icu:
            assert body["entity_ids"][0] == icu[0]["id"] and icu[0]["id"] in body["answer_text"]
        else:
            assert "No scored patients" in body["answer_text"]
        unknown = (await client.post("/agent/ask", json={"question": "tell me a joke", "hospital_id": "mercy"})).json()
        assert unknown["entity_ids"] == [] and "I can answer questions" in unknown["answer_text"] and unknown["tools"] == []
        bad_unit = (await client.post("/agent/ask", json={"question": "where is P-9999", "hospital_id": "mercy"})).json()
        assert "not in any hospital" in bad_unit["answer_text"]


async def test_the_endpoint_validates_the_request(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, _app):
        assert (await client.post("/agent/ask", json={"question": "   ", "hospital_id": "mercy"})).status_code == 422
        assert (await client.post("/agent/ask", json={"question": "x" * 401, "hospital_id": "mercy"})).status_code == 422
        assert (await client.post("/agent/ask", json={"question": "how full", "hospital_id": "atlantis"})).status_code == 404
        assert (await client.post("/agent/ask", json={"hospital_id": "mercy"})).status_code == 422


async def test_a_grounded_gemini_answer_is_used(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt)
        top = await ToolBox(rt.sim, app.state.pool).call("get_er_wait", {"hospital": "mercy"})
        answer = AskOutput(
            answer_text=f"The ER wait is {top['er_wait_min']} minutes.", cited_metrics=[{"name": "er_wait_min", "value": top["er_wait_min"]}]
        )
        llm = ScriptedAsk([("get_er_wait", {"hospital": "mercy"})], answer)
        ask_service(app).llm = llm
        body = (await client.post("/agent/ask", json={"question": "how long is the wait?", "hospital_id": "mercy"})).json()
        assert body["source"] == "gemini" and body["label"] is None and body["tools"][0]["name"] == "get_er_wait"
        assert str(top["er_wait_min"]) in body["answer_text"]


async def test_an_ungrounded_answer_is_retried_once_with_the_errors_then_replaced_by_the_fallback(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt)
        bad = AskOutput(answer_text="The wait is 9999 minutes.")
        llm = ScriptedAsk([("get_er_wait", {"hospital": "mercy"})], bad, bad)
        ask_service(app).llm = llm
        body = (await client.post("/agent/ask", json={"question": "what is the ER wait", "hospital_id": "mercy"})).json()
        assert body["source"] == "fallback" and "9999" not in body["answer_text"]
        assert llm.errors_seen[0] is None and llm.errors_seen[1] and "9999" in llm.errors_seen[1][0]

        good_second = ScriptedAsk(
            [("get_er_wait", {"hospital": "mercy"})],
            bad,
            AskOutput(answer_text="There are people waiting."),
        )
        ask_service(app).llm = good_second
        body = (await client.post("/agent/ask", json={"question": "what is the ER wait", "hospital_id": "mercy"})).json()
        assert body["source"] == "gemini" and len(good_second.errors_seen) == 2


@pytest.mark.parametrize("failure", [TimeoutError("slow"), OSError("down"), AskError("bad reply"), ValueError("x")])
async def test_gemini_failures_fall_back(migrated_db_url: str, failure: Exception) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt, 10)
        ask_service(app).llm = ScriptedAsk([], failure)
        body = (await client.post("/agent/ask", json={"question": "how many nurses are on duty", "hospital_id": "mercy"})).json()
        assert body["source"] == "fallback" and "staffing" in body["answer_text"]


async def test_an_answer_that_used_no_tools_is_not_trusted(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt, 10)
        ask_service(app).llm = ScriptedAsk([], AskOutput(answer_text="Everything is fine."), AskOutput(answer_text="Everything is fine."))
        body = (await client.post("/agent/ask", json={"question": "how full is the ICU", "hospital_id": "mercy"})).json()
        assert body["source"] == "fallback" and "ICU" in body["answer_text"]


async def test_a_tool_error_is_given_to_the_model_not_raised(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt, 10)
        llm = ScriptedAsk(
            [("get_er_wait", {"hospital": "atlantis"})],
            AskOutput(answer_text="The wait is 42 minutes."),
            AskOutput(answer_text="The wait is 42 minutes."),
        )
        ask_service(app).llm = llm
        body = (await client.post("/agent/ask", json={"question": "what is the ER wait", "hospital_id": "mercy"})).json()
        assert body["source"] == "fallback"


async def test_asking_without_the_simulation_running_is_unavailable(migrated_db_url: str) -> None:
    import httpx
    from pydantic import SecretStr

    from twin.api.app import create_app
    from twin.common.config import Settings

    app = create_app(Settings(_env_file=None, database_url=SecretStr(migrated_db_url)), simulate=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/agent/ask", json={"question": "how full", "hospital_id": "mercy"})).status_code == 503


async def test_a_gemini_api_error_such_as_a_bad_key_gives_the_fallback_answer_not_a_server_error(migrated_db_url: str) -> None:
    from google.genai.errors import ClientError, ServerError

    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, app):
        await warmed(client, rt, 10)
        for failure in (ClientError(400, {"error": {"message": "API key not valid"}}), ServerError(503, {"error": {"message": "overloaded"}})):
            ask_service(app).llm = ScriptedAsk([], failure)
            response = await client.post("/agent/ask", json={"question": "how many nurses are on duty", "hospital_id": "mercy"})
            assert response.status_code == 200 and response.json()["source"] == "fallback"
