"""The operations agent's structured output (PROMPT.md §9). Gemini fills this schema; the rules engine produces
the same shape, so the rest of the system does not care which one answered."""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from twin.common.ws import ActionName

Param = str | float | int | list[str]


class CitedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="A metric name exactly as it appears in the input, e.g. 'ICU.occupied'")
    value: float = Field(description="Its value exactly as it appears in the input")


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="A short unique id for this recommendation")
    hospital_id: str
    action: ActionName
    targets: list[str] = Field(description="Hospital ids, patient ids, unit names or bed ids the action applies to")
    params: dict[str, Param] = Field(default_factory=dict)
    rationale: str = Field(description="One or two sentences for the operations manager, citing exact numbers")
    cited_metrics: list[CitedMetric]


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[Recommendation]


Source = Literal["gemini", "rules"]
FALLBACK_LABEL = "Rules engine — Gemini unavailable"


TRAILING_COMMA = re.compile(r",\s*([}\]])")


def parse_agent_output(text: str) -> AgentOutput:
    """Read a model reply as `AgentOutput`. Small slips that models make are forgiven (a code fence around the JSON,
    a trailing comma, extra keys); anything else raises ValueError saying what is wrong, so the model can be told."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    cleaned = TRAILING_COMMA.sub(r"\1", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f"the reply is not valid JSON ({error.msg} at line {error.lineno} column {error.colno})") from error
    if isinstance(data, dict):
        data = {"recommendations": data.get("recommendations", [])}  # models sometimes add keys of their own at the top
    try:
        return AgentOutput.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        raise ValueError(f"the reply does not match the required shape ({'.'.join(str(p) for p in first['loc'])}: {first['msg']})") from error
