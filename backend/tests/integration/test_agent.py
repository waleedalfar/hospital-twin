"""The operations agent and governance endpoints through the real database and API (PROMPT.md §6.2, §8, §9)."""

import json

import asyncpg
import pytest

from tests.agent_helpers import busy_summary, fixture
from tests.integration.test_ml_api import app_client
from tests.integration.test_sim_db import seed_patients
from twin.agent.llm import LLMClient
from twin.agent.schema import FALLBACK_LABEL, Recommendation
from twin.agent.service import AgentService
from twin.common.ws import AgentRecModel


class FakeLLM:
    """Replays recorded Gemini responses (or raises) in order. Tests only."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def agent_of(rt: object) -> AgentService:
    agent = rt.agent  # type: ignore[attr-defined]
    assert isinstance(agent, AgentService)
    return agent


async def audit_actions(dsn: str) -> list[str]:
    conn = await asyncpg.connect(dsn)
    try:
        return [r["action"] for r in await conn.fetch("SELECT action FROM audit_log ORDER BY time, action")]
    finally:
        await conn.close()


async def test_gemini_output_that_is_grounded_is_used_and_labelled_as_gemini(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        llm = FakeLLM(fixture("valid_divert.json"))
        agent.llm = llm
        output, source = await agent.produce(busy_summary(), "test")
        assert source == "gemini" and output.recommendations[0].action == "divert_ambulances"
        assert len(llm.prompts) == 1 and '"hospital_id": "mercy"' in llm.prompts[0]


async def test_an_ungrounded_answer_is_retried_once_with_the_errors_then_used_if_fixed(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        llm = FakeLLM(fixture("ungrounded_value.json"), fixture("valid_divert.json"))
        agent.llm = llm
        _, source = await agent.produce(busy_summary(), "test")
        assert source == "gemini" and len(llm.prompts) == 2
        assert "rejected for these reasons" in llm.prompts[1] and "er_wait_min" in llm.prompts[1]
        assert "agent_validation_failed" in await audit_actions(migrated_db_url)


@pytest.mark.parametrize("reply", ["ungrounded_value.json", "bad_target.json", "unknown_metric.json", "wrong_action.json"])
async def test_two_bad_answers_fall_back_to_the_rules_engine(migrated_db_url: str, reply: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        llm = FakeLLM(fixture(reply), fixture(reply))
        agent.llm = llm
        output, source = await agent.produce(busy_summary(), "test")
        assert source == "rules" and len(llm.prompts) == 2  # an unreadable answer is retried once too
        assert output.recommendations and {r.hospital_id for r in output.recommendations} == {"mercy"}


@pytest.mark.parametrize("failure", [TimeoutError("slow"), OSError("network down")])
async def test_gemini_errors_and_timeouts_fall_back_and_are_audited(migrated_db_url: str, failure: str | Exception) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        agent.llm = FakeLLM(failure)
        output, source = await agent.produce(busy_summary(), "test")
        assert source == "rules" and output.recommendations
        assert "agent_llm_error" in await audit_actions(migrated_db_url)


async def test_gemini_is_not_called_more_often_than_the_minimum_interval(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        llm = FakeLLM(fixture("valid_divert.json"), fixture("valid_divert.json"))
        agent.llm = llm
        agent.clock = lambda: 1000.0
        assert (await agent.produce(busy_summary(), "a"))[1] == "gemini"
        assert (await agent.produce(busy_summary(), "b"))[1] == "rules"  # within 20 s: no second call
        agent.clock = lambda: 1021.0
        assert (await agent.produce(busy_summary(), "c"))[1] == "gemini"
        assert len(llm.prompts) == 2


async def test_without_a_client_the_rules_engine_is_used_and_labelled(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        assert agent.llm is None  # no GEMINI_API_KEY in the test settings
        output, source = await agent.produce(busy_summary(), "test")
        assert source == "rules"
        stored = await agent.store(output.recommendations[0], source)
        assert stored.label == FALLBACK_LABEL and stored.status == "pending" and stored.id.startswith("REC-")
        listed = (await client.get("/agent/recs?hospital=mercy")).json()
        assert [r["id"] for r in listed] == [stored.id] and listed[0]["label"] == FALLBACK_LABEL
        assert listed[0]["cited_metrics"] and listed[0]["source"] == "rules"


async def test_a_gemini_recommendation_has_no_fallback_label(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        rec = Recommendation.model_validate_json(json.dumps(json.loads(fixture("valid_divert.json"))["recommendations"][0]))
        await agent.store(rec, "gemini")
        body = (await client.get("/agent/recs")).json()
        assert body[0]["source"] == "gemini" and body[0]["label"] is None


async def test_approving_a_diversion_changes_the_simulation_and_writes_the_audit_log(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        output, source = await agent.produce(busy_summary(), "test")
        divert = next(r for r in output.recommendations if r.action == "divert_ambulances")
        stored = await agent.store(divert, source)
        assert str(rt.sim.world.hospitals["mercy"].status) == "open"
        response = await client.post(f"/agent/recs/{stored.id}/approve")
        assert response.status_code == 200
        body = response.json()
        assert body["rec"]["status"] == "approved" and "divert" in body["result"].lower()
        assert str(rt.sim.world.hospitals["mercy"].status) == "diverting"
        actions = await audit_actions(migrated_db_url)
        assert "agent_rec" in actions and "action_applied" in actions and "agent_rec_approved" in actions
        again = await client.post(f"/agent/recs/{stored.id}/approve")
        assert again.status_code == 409 and "already approved" in again.json()["detail"]
        assert (await client.get("/agent/recs?status=approved")).json()[0]["id"] == stored.id
        assert (await client.get("/agent/recs?status=pending")).json() == []


async def test_dismissing_leaves_the_simulation_alone_and_is_audited(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        output, source = await agent.produce(busy_summary(), "test")
        stored = await agent.store(output.recommendations[0], source)
        body = (await client.post(f"/agent/recs/{stored.id}/dismiss")).json()
        assert body["status"] == "dismissed"
        assert str(rt.sim.world.hospitals["mercy"].status) == "open"
        assert "agent_rec_dismissed" in await audit_actions(migrated_db_url)
        assert (await client.post(f"/agent/recs/{stored.id}/dismiss")).status_code == 409


async def test_unknown_recommendations_and_bad_filters_are_errors(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, _, _app):
        assert (await client.post("/agent/recs/REC-999/approve")).status_code == 404
        assert (await client.post("/agent/recs/REC-999/dismiss")).status_code == 404
        assert (await client.get("/agent/recs?status=bogus")).status_code == 422


async def test_an_action_that_no_longer_applies_is_a_conflict_and_stays_pending(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        output, source = await agent.produce(busy_summary(), "test")
        discharge = next(r for r in output.recommendations if r.action == "expedite_discharge")
        stored = await agent.store(discharge, source)  # P-0100 does not exist in the simulation
        response = await client.post(f"/agent/recs/{stored.id}/approve")
        assert response.status_code == 409 and "Cannot apply" in response.json()["detail"]
        assert (await client.get("/agent/recs?status=pending")).json()[0]["id"] == stored.id


async def test_the_same_pending_recommendation_is_not_stored_twice_and_old_ones_expire(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        for _ in range(2):
            await agent.run("mercy", "test")
        pending = (await client.get("/agent/recs?status=pending&hospital=mercy")).json()
        keys = [(r["action"], tuple(sorted(r["targets"]))) for r in pending]
        assert len(keys) == len(set(keys))
        n = len(pending)
        for _ in range(130):
            await rt.step()
        await agent.expire_old()
        expired = (await client.get("/agent/recs?status=expired")).json()
        assert len(expired) >= min(n, 1) if n else True


async def test_the_agent_runs_when_a_scenario_starts_and_every_15_sim_minutes(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        agent = agent_of(rt)
        calls: list[tuple[str, str]] = []

        async def fake_run(hospital_id: str, reason: str) -> list[AgentRecModel]:
            calls.append((hospital_id, reason))
            return []

        monkeypatch.setattr(agent, "run", fake_run)
        response = await client.post("/scenario", json={"name": "flu_surge", "hospital_id": "mercy"})
        assert response.status_code in (200, 201)
        await agent_idle(agent)
        assert ("mercy", "scenario") in calls
        calls.clear()
        agent.tick(14)
        await agent_idle(agent)
        assert calls == []
        agent.tick(15)
        await agent_idle(agent)
        assert {h for h, _ in calls} == {"mercy", "stlukes", "desert"}


async def agent_idle(agent: AgentService) -> None:
    import asyncio

    while agent.tasks:
        await asyncio.gather(*list(agent.tasks))


async def test_a_failure_inside_a_background_run_is_logged_and_does_not_stop_the_agent(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)

        async def broken(hospital_id: str, reason: str) -> list[AgentRecModel]:
            raise RuntimeError("db exploded")

        logged: list[str] = []
        monkeypatch.setattr("twin.agent.service.logger.exception", lambda message, *args: logged.append(message % args))
        monkeypatch.setattr(agent, "run", broken)
        agent.schedule(["mercy"], "test")
        await agent_idle(agent)
        assert logged == ["The agent failed for mercy (test)"] and agent.running == set()


async def test_the_agent_can_be_turned_off(migrated_db_url: str) -> None:
    import httpx
    from pydantic import SecretStr

    from twin.api.app import create_app
    from twin.common.config import Settings

    settings = Settings(_env_file=None, database_url=SecretStr(migrated_db_url), sim_warmup_hours=2, sim_autostart=False, agent_enabled=False)
    app = create_app(settings)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/agent/recs")).status_code == 503


# ---- governance endpoints -----------------------------------------------------------------------------------------


async def test_drift_fairness_audit_and_model_card_endpoints(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (client, rt, _app):
        for _ in range(125):
            await rt.step()
        drift = (await client.get("/governance/drift")).json()
        assert drift["threshold"] == 0.2 and "spo2" in drift["respiratory_features"]
        assert {c["hospital_id"] for c in drift["cells"]} <= {"mercy", "stlukes", "desert"}
        assert all(c["alert"] == (c["psi"] > 0.2) for c in drift["cells"])
        fairness = (await client.get("/governance/fairness")).json()
        assert fairness["available"] is True and "groups" in fairness and "max_auroc_gap" in fairness
        audit = (await client.get("/governance/audit?limit=500")).json()
        assert any(a["action"] == "fairness_report" and a["actor"] == "system" for a in audit)
        only = (await client.get("/governance/audit?action=fairness_report")).json()
        assert only and {a["action"] for a in only} == {"fairness_report"}
        left_out = (await client.get("/governance/audit?exclude=fairness_report,risk_alert&limit=500")).json()
        assert "fairness_report" not in {a["action"] for a in left_out}
        assert (await client.get("/governance/audit?actor=nobody")).json() == []
        card = await client.get("/governance/model-card")
        assert card.status_code == 200 and "lgbm-v1" in card.text


async def test_governance_without_models_says_why(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url, ml=False) as (client, rt, _app):
        await rt.step()
        body = (await client.get("/governance/fairness")).json()
        assert body["available"] is False and "No model" in body["reason"]


def test_the_agent_protocol_is_satisfied_by_the_fake_client() -> None:
    client: LLMClient = FakeLLM("{}")
    assert client is not None


async def test_a_gemini_api_error_such_as_a_bad_key_falls_back_to_the_rules_engine(migrated_db_url: str) -> None:
    from google.genai.errors import ClientError

    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        agent.llm = FakeLLM(ClientError(400, {"error": {"message": "API key not valid"}}))
        output, source = await agent.produce(busy_summary(), "test")
        assert source == "rules" and output.recommendations
        assert "agent_llm_error" in await audit_actions(migrated_db_url)


async def test_malformed_json_is_retried_once_with_the_error_and_then_used(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        llm = FakeLLM(fixture("malformed.json"), fixture("valid_divert.json"))
        agent.llm = llm
        _, source = await agent.produce(busy_summary(), "test")
        assert source == "gemini" and len(llm.prompts) == 2
        assert "rejected for these reasons" in llm.prompts[1] and "not valid JSON" in llm.prompts[1]


async def test_malformed_json_twice_falls_back_and_is_audited(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    async with app_client(migrated_db_url) as (_, rt, _app):
        agent = agent_of(rt)
        agent.llm = FakeLLM(fixture("malformed.json"), fixture("malformed.json"))
        output, source = await agent.produce(busy_summary(), "test")
        assert source == "rules" and output.recommendations
        assert "agent_validation_failed" in await audit_actions(migrated_db_url)
