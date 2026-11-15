"""`make verify-live`: one real Gemini call on a live simulation summary, checked like any production answer.

Not part of `make verify` (it needs a key, a network and costs a call). Without GEMINI_API_KEY and GEMINI_MODEL it
says so and exits 0, so it is safe to run anywhere. With them it exits 1 unless Gemini returned a parseable,
grounded recommendation set.
"""

import asyncio
import logging
import sys
from datetime import timedelta

from google.genai.errors import APIError
from pydantic import ValidationError

from twin.agent.llm import build_prompt, make_client
from twin.agent.schema import AgentOutput
from twin.agent.summary import build_summary
from twin.agent.validator import validate
from twin.common.config import get_settings
from twin.common.logging import configure_logging
from twin.ml.cli import load_profiles
from twin.sim.engine import Simulation
from twin.sim.layout_model import load_layout

logger = logging.getLogger(__name__)


async def check() -> int:
    settings = get_settings()
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    client = make_client(key, settings.gemini_model)
    if client is None:
        print("verify-live: skipped (set GEMINI_API_KEY and GEMINI_MODEL in .env to make a real call)")
        return 0
    profiles = await load_profiles(settings.database_url.get_secret_value())
    if not profiles:
        print("verify-live: no patients in the database; run `make seed` first", file=sys.stderr)
        return 1
    sim = Simulation(load_layout(), profiles, settings.sim_seed, timedelta(hours=24))
    sim.run_until(sim.visible_start + timedelta(hours=2))
    sim.start_scenario("flu_surge", "mercy")
    for _ in range(120):
        sim.tick()
    summary = build_summary(sim.world, sim.ml, "mercy")
    try:
        text = await client.generate(build_prompt(summary))
        output = AgentOutput.model_validate_json(text)
    except (APIError, TimeoutError, OSError, ValueError, ValidationError) as error:
        logger.exception("The live Gemini call failed")
        print(f"verify-live: FAILED, the call or its parsing raised {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    errors = validate(output, summary)
    for rec in output.recommendations:
        print(f"  {rec.action} -> {', '.join(rec.targets)}: {rec.rationale}")
    if errors:
        print("verify-live: FAILED, the answer is not grounded:", *errors, sep="\n  ", file=sys.stderr)
        return 1
    print(f"verify-live: OK, {len(output.recommendations)} grounded recommendation(s) from {settings.gemini_model}")
    return 0


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    return asyncio.run(check())


if __name__ == "__main__":
    raise SystemExit(main())
