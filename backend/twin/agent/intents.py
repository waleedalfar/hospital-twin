"""Deterministic fallback for "Ask Hospital Twin" when Gemini is unavailable (PROMPT.md §9.1).

`parse_intent` maps a question to one of the six tools; `compose` writes the answer from the tool result alone, so
every number and id in it is grounded by construction (and checked by the same grounding check as Gemini's)."""

import re
from dataclasses import dataclass, field
from typing import Any

from twin.agent.grounding import AskOutput
from twin.agent.schema import CitedMetric

FALLBACK_ASK_LABEL = "Fallback intent parser — Gemini unavailable"
HELP = "I can answer questions about high-risk patients, bed occupancy, forecasts, where a patient is, the ER wait and nurse staffing."

HOSPITAL_WORDS = {"mercy": "mercy", "luke": "stlukes", "desert": "desert", "valley": "desert"}
UNIT_WORDS = (("icu", "ICU"), ("intensive", "ICU"), ("recovery", "REC"), ("pacu", "REC"), ("ward", "WARD"), ("er", "ER"), ("emergency", "ER"))
UNIT_NAMES = {"ER": "ER", "WARD": "Ward", "ICU": "ICU", "REC": "Recovery"}
PATIENT_ID = re.compile(r"\bp[-\s]?(\d{1,5})\b", re.IGNORECASE)
LIMIT = re.compile(r"\b(?:top|first|worst)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:patients|people)\b")
RISK = re.compile(r"crash|deteriorat|risk|critical|sickest|worst|danger|unstable|alert|worried|dying|coding|decline")
STAFF = re.compile(r"nurse|staff|ratio|understaffed|short.?staffed|shift")
WAIT = re.compile(r"\bwait|how long.*(er|emergency)|waiting (time|room)|queue|triage")
FORECAST = re.compile(
    r"when|forecast|predict|expect|projected|arrival|will .*(full|fill|run out)|hours? until|next (few )?hours|going to be full|tonight|later"
)
OCCUPANCY = re.compile(r"full|occupan|beds?\b|capacity|how many (patients|people)|census|crowd|busy|free|available|space|open")


@dataclass
class Intent:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


def _words(question: str) -> set[str]:
    return set(re.findall(r"[a-z]+", question.lower()))


def detect_unit(question: str) -> str | None:
    words = _words(question)
    for word, unit in UNIT_WORDS:
        if word in words:
            return unit
    return None


def detect_hospital(question: str, default: str) -> str:
    low = question.lower()
    for word, hospital in HOSPITAL_WORDS.items():
        if word in low:
            return hospital
    return default


def parse_intent(question: str, hospital: str) -> Intent | None:
    """The tool call that answers `question`, or None if it is not about anything the tools cover."""
    low = question.lower().strip()
    if not low:
        return None
    where = detect_hospital(low, hospital)
    unit = detect_unit(low)
    unit_args: dict[str, Any] = {"hospital": where, **({"unit": unit} if unit else {})}
    patient = PATIENT_ID.search(low)
    if patient:
        return Intent("find_patient", {"patient_id": f"P-{int(patient.group(1)):04d}"})
    if STAFF.search(low):
        return Intent("get_staffing", unit_args)
    if WAIT.search(low) and not re.search(r"when|will", low):
        return Intent("get_er_wait", {"hospital": where})
    if FORECAST.search(low) and not RISK.search(low):
        return Intent("get_forecast", unit_args)
    if RISK.search(low):
        limit = LIMIT.search(low)
        return Intent("list_high_risk_patients", {**unit_args, "limit": int(limit.group(1) or limit.group(2)) if limit else 3})
    if OCCUPANCY.search(low):
        return Intent("get_occupancy", unit_args)
    if WAIT.search(low):
        return Intent("get_er_wait", {"hospital": where})
    return None


def _metric(name: str, value: float) -> CitedMetric:
    return CitedMetric(name=name, value=value)


def fill_text(hours: float | None) -> str:
    if hours is None:
        return "not projected to fill any time soon"
    return "full now" if hours == 0 else f"projected to fill in {hours} hours"


def compose(intent: Intent, result: dict[str, Any], hospital_name: str) -> AskOutput:
    """The answer, its highlighted patients and its cited numbers, built only from `result`."""
    tool = intent.tool
    if tool == "list_high_risk_patients":
        patients = result["patients"]
        where = f" in the {UNIT_NAMES[result['unit']]}" if result["unit"] else ""
        if not patients:
            return AskOutput(answer_text=f"No scored patients{where} at {hospital_name} right now.")
        top = patients[0]
        spot = top["bed"] or top["unit"]
        parts = [
            f"At {hospital_name}{where}, the patient most likely to deteriorate is {top['patient_id']} in {spot} "
            f"(risk {top['score']:.2f}, {top['level']})."
        ]
        if top["top_factors"]:
            parts.append(f"Main reasons: {', '.join(top['top_factors'])}.")
        if len(patients) > 1:
            parts.append("Next: " + "; ".join(f"{p['patient_id']} ({p['score']:.2f})" for p in patients[1:]) + ".")
        return AskOutput(
            answer_text=" ".join(parts),
            entity_ids=[p["patient_id"] for p in patients],
            cited_metrics=[_metric(f"patient.{p['patient_id']}.score", p["score"]) for p in patients],
        )
    if tool == "get_occupancy":
        units = result["units"]
        text = "; ".join(f"{UNIT_NAMES[u['unit']]} {u['occupied']} of {u['capacity']} beds ({u['occupancy_pct']}%)" for u in units)
        return AskOutput(
            answer_text=f"{hospital_name} occupancy: {text}.",
            cited_metrics=[_metric(f"{u['unit']}.occupied", u["occupied"]) for u in units]
            + [_metric(f"{u['unit']}.capacity", u["capacity"]) for u in units],
        )
    if tool == "get_forecast":
        if not result["forecast_available"]:
            return AskOutput(answer_text=f"There is no forecast for {hospital_name} yet.")
        full = result["hours_until_full"]
        parts = [f"{hospital_name} expects about {result['expected_arrivals_total']} arrivals in the next {result['horizon_h']} hours."]
        for unit, hours in full.items():
            parts.append(f"The {UNIT_NAMES[unit]} is {fill_text(hours)}.")
        return AskOutput(
            answer_text=" ".join(parts),
            cited_metrics=[
                _metric("forecast_arrivals", result["expected_arrivals_total"]),
                *[_metric(f"{u}.hours_until_full", h) for u, h in full.items() if h is not None],
            ],
        )
    if tool == "find_patient":
        if not result["found"]:
            return AskOutput(answer_text=f"{result['patient_id']} is not in any hospital right now.")
        place = f"in {result['bed']}" if result["bed"] else f"({result['phase'].replace('_', ' ')})"
        risk = f" Risk {result['score']:.2f} ({result['level']})." if result["score"] is not None else ""
        stay = f" Expected to go home in about {result['expected_discharge_h']} hours." if result["expected_discharge_h"] is not None else ""
        metrics = [_metric(f"patient.{result['patient_id']}.score", result["score"])] if result["score"] is not None else []
        return AskOutput(
            answer_text=f"{result['patient_id']} is {place} on floor {result['floor']}, {result['unit']}, at {hospital_name}.{risk}{stay}".replace(
                "floor None, ", ""
            ),
            entity_ids=[result["patient_id"]],
            cited_metrics=metrics,
        )
    if tool == "get_er_wait":
        return AskOutput(
            answer_text=f"The ER wait at {hospital_name} is about {result['er_wait_min']} minutes, with {result['waiting']} patients waiting.",
            cited_metrics=[_metric("er_wait_min", result["er_wait_min"]), _metric("waiting", result["waiting"])],
        )
    units = result["units"]
    text = "; ".join(f"{UNIT_NAMES[u['unit']]} {u['nurses']} nurses, {u['required']} needed" for u in units)
    return AskOutput(
        answer_text=f"{hospital_name} staffing: {text}.",
        cited_metrics=[_metric(f"staff.{u['unit']}.nurses", u["nurses"]) for u in units]
        + [_metric(f"staff.{u['unit']}.required", u["required"]) for u in units],
    )
