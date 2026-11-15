"""The operations agent's structured output (PROMPT.md §9). Gemini fills this schema; the rules engine produces
the same shape, so the rest of the system does not care which one answered."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
