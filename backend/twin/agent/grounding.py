"""Grounding for answers to spoken or typed questions (PROMPT.md §9.1): every number and id in an answer must come
from a tool result of this question. Anything else is treated as invented and the answer is rejected."""

import re
from typing import Any

from pydantic import BaseModel, Field

from twin.agent.schema import CitedMetric

ID_PATTERN = re.compile(r"\b[A-Z]{1,5}-\d+\b")
NUMBER_PATTERN = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
TOLERANCE = 0.051


class AskOutput(BaseModel):
    """What the model (or the fallback) returns for one question."""

    answer_text: str = Field(min_length=1, max_length=1200)
    entity_ids: list[str] = Field(default_factory=list, max_length=20)
    cited_metrics: list[CitedMetric] = Field(default_factory=list, max_length=20)


class Facts:
    """Every number and every string that appears in the tool results, plus the length of every list."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.numbers: list[float] = []
        self.strings: set[str] = set()
        for result in results:
            self._walk(result)

    def _walk(self, value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float):
            self.numbers.append(float(value))
        elif isinstance(value, str):
            self.strings.add(value.upper())
            self.numbers.extend(float(m) for m in NUMBER_PATTERN.findall(value))
        elif isinstance(value, dict):
            for v in value.values():
                self._walk(v)
        elif isinstance(value, list | tuple):
            self.numbers.append(float(len(value)))
            for v in value:
                self._walk(v)

    def has_number(self, x: float) -> bool:
        return any(abs(x - n) <= TOLERANCE for n in self.numbers)


def check_answer(output: AskOutput, results: list[dict[str, Any]]) -> list[str]:
    """Errors for every number, id, entity or cited metric that no tool result contains."""
    facts = Facts(results)
    errors: list[str] = []
    text = output.answer_text
    for found in sorted(set(ID_PATTERN.findall(text.upper()))):
        if found not in facts.strings:
            errors.append(f"id {found} in the answer is not in any tool result")
    without_ids = ID_PATTERN.sub(" ", text.upper())
    for token in NUMBER_PATTERN.findall(without_ids):
        if not facts.has_number(float(token)):
            errors.append(f"number {token} in the answer is not in any tool result")
    for entity in output.entity_ids:
        if entity.upper() not in facts.strings:
            errors.append(f"entity {entity} is not in any tool result")
        elif not entity.upper().startswith("P-"):
            errors.append(f"entity {entity} is not a patient id")
    for cited in output.cited_metrics:
        if not facts.has_number(cited.value):
            errors.append(f"cited metric {cited.name}={cited.value} is not in any tool result")
    return errors
