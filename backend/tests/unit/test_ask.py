"""Intent parser, grounding and answer composition for "Ask Hospital Twin" (PROMPT.md §9.1)."""

from typing import Any

import pytest

from twin.agent.ask_llm import AskError, parse_answer
from twin.agent.grounding import AskOutput, Facts, check_answer
from twin.agent.intents import FALLBACK_ASK_LABEL, Intent, compose, detect_hospital, detect_unit, parse_intent
from twin.agent.schema import CitedMetric
from twin.agent.tools import TOOL_NAMES, TOOL_SPECS

PHRASINGS: list[tuple[str, str, dict[str, object]]] = [
    ("who is most likely to crash", "list_high_risk_patients", {"hospital": "mercy", "limit": 3}),
    ("Who is most likely to crash in the ICU?", "list_high_risk_patients", {"hospital": "mercy", "unit": "ICU", "limit": 3}),
    ("who is at highest risk", "list_high_risk_patients", {"hospital": "mercy", "limit": 3}),
    ("show me the sickest patients", "list_high_risk_patients", {"hospital": "mercy", "limit": 3}),
    ("which patients are deteriorating in the ward", "list_high_risk_patients", {"hospital": "mercy", "unit": "WARD", "limit": 3}),
    ("any critical patients at St. Luke's", "list_high_risk_patients", {"hospital": "stlukes", "limit": 3}),
    ("top 5 patients at risk in the ER", "list_high_risk_patients", {"hospital": "mercy", "unit": "ER", "limit": 5}),
    ("who should I be worried about at Desert Valley", "list_high_risk_patients", {"hospital": "desert", "limit": 3}),
    ("how full is the ICU", "get_occupancy", {"hospital": "mercy", "unit": "ICU"}),
    ("how full is the hospital", "get_occupancy", {"hospital": "mercy"}),
    ("what is the occupancy at Mercy", "get_occupancy", {"hospital": "mercy"}),
    ("are there any free beds in the ward", "get_occupancy", {"hospital": "mercy", "unit": "WARD"}),
    ("how many patients do we have", "get_occupancy", {"hospital": "mercy"}),
    ("is the recovery unit crowded", "get_occupancy", {"hospital": "mercy", "unit": "REC"}),
    ("bed capacity at desert valley", "get_occupancy", {"hospital": "desert"}),
    ("when will the ER be full", "get_forecast", {"hospital": "mercy", "unit": "ER"}),
    ("when will the ICU fill up", "get_forecast", {"hospital": "mercy", "unit": "ICU"}),
    ("forecast for the next hours", "get_forecast", {"hospital": "mercy"}),
    ("how many arrivals are we expecting", "get_forecast", {"hospital": "mercy"}),
    ("will the ward run out of beds", "get_forecast", {"hospital": "mercy", "unit": "WARD"}),
    ("what is the projected load at St Luke's", "get_forecast", {"hospital": "stlukes"}),
    ("where is P-0412", "find_patient", {"patient_id": "P-0412"}),
    ("find patient p0042", "find_patient", {"patient_id": "P-0042"}),
    ("locate patient P 17", "find_patient", {"patient_id": "P-0017"}),
    ("what is the status of p-0099?", "find_patient", {"patient_id": "P-0099"}),
    ("how is P-0007 doing", "find_patient", {"patient_id": "P-0007"}),
    ("what is the ER wait", "get_er_wait", {"hospital": "mercy"}),
    ("how long is the wait at Mercy", "get_er_wait", {"hospital": "mercy"}),
    ("how long is the wait in the emergency room", "get_er_wait", {"hospital": "mercy"}),
    ("how many people are in the waiting room", "get_er_wait", {"hospital": "mercy"}),
    ("how many nurses are on duty", "get_staffing", {"hospital": "mercy"}),
    ("how many nurses in the ICU", "get_staffing", {"hospital": "mercy", "unit": "ICU"}),
    ("are we understaffed", "get_staffing", {"hospital": "mercy"}),
    ("staffing at Desert Valley", "get_staffing", {"hospital": "desert"}),
    ("what is the nurse to patient ratio in the ward", "get_staffing", {"hospital": "mercy", "unit": "WARD"}),
]


@pytest.mark.parametrize(("question", "tool", "args"), PHRASINGS)
def test_phrasings_map_to_the_right_tool(question: str, tool: str, args: dict[str, object]) -> None:
    intent = parse_intent(question, "mercy")
    assert intent == Intent(tool, args)


def test_there_are_at_least_thirty_phrasings_covering_all_six_tools() -> None:
    assert len(PHRASINGS) >= 30
    assert {tool for _, tool, _ in PHRASINGS} == set(TOOL_NAMES)
    assert {spec["name"] for spec in TOOL_SPECS} == set(TOOL_NAMES)


@pytest.mark.parametrize("question", ["", "   ", "tell me a joke", "what is the weather", "asdf"])
def test_questions_outside_the_tools_are_not_guessed(question: str) -> None:
    assert parse_intent(question, "mercy") is None


def test_hospital_and_unit_detection() -> None:
    assert detect_hospital("what about desert valley", "mercy") == "desert"
    assert detect_hospital("at St. Luke's", "mercy") == "stlukes"
    assert detect_hospital("anything", "stlukes") == "stlukes"
    assert detect_unit("in the intensive care") == "ICU" and detect_unit("the emergency department") == "ER"
    assert detect_unit("how are things") is None


# ---- grounding ---------------------------------------------------------------------------------------------


RISK_RESULT: dict[str, Any] = {
    "hospital": "mercy",
    "unit": "ICU",
    "patients": [
        {"patient_id": "P-0042", "unit": "ICU", "bed": "ICU-3", "score": 0.81, "level": "high", "top_factors": ["SpO2 drop, 2h", "HR trend"]},
        {"patient_id": "P-0007", "unit": "ICU", "bed": "ICU-1", "score": 0.52, "level": "medium", "top_factors": []},
    ],
}


def test_facts_collect_numbers_strings_and_list_lengths() -> None:
    facts = Facts([RISK_RESULT])
    assert "P-0042" in facts.strings and "ICU-3" in facts.strings
    assert facts.has_number(0.81) and facts.has_number(2) and not facts.has_number(0.9)


def test_a_grounded_answer_passes() -> None:
    out = AskOutput(
        answer_text="P-0042 in ICU-3 has risk 0.81, then P-0007 at 0.52.",
        entity_ids=["P-0042"],
        cited_metrics=[CitedMetric(name="patient.P-0042.score", value=0.81)],
    )
    assert check_answer(out, [RISK_RESULT]) == []


def test_invented_ids_numbers_entities_and_metrics_are_rejected() -> None:
    out = AskOutput(
        answer_text="P-0999 is at 0.93 in ICU-3.",
        entity_ids=["P-0999", "ICU-3"],
        cited_metrics=[CitedMetric(name="x", value=7.5)],
    )
    errors = check_answer(out, [RISK_RESULT])
    assert "id P-0999 in the answer is not in any tool result" in errors
    assert "number 0.93 in the answer is not in any tool result" in errors
    assert "entity P-0999 is not in any tool result" in errors
    assert "entity ICU-3 is not a patient id" in errors
    assert any("x=7.5" in e for e in errors)


def test_numbers_inside_ids_are_not_checked_as_numbers() -> None:
    out = AskOutput(answer_text="ICU-3 and P-0042.")
    assert check_answer(out, [RISK_RESULT]) == []


def test_rounding_is_tolerated_but_not_a_different_number() -> None:
    result = {"er_wait_min": 77.24}
    assert check_answer(AskOutput(answer_text="About 77.2 minutes."), [result]) == []
    assert check_answer(AskOutput(answer_text="About 77.4 minutes."), [result])


def test_model_replies_are_parsed_strictly() -> None:
    assert parse_answer('{"answer_text": "x", "entity_ids": ["P-1"], "cited_metrics": []}').entity_ids == ["P-1"]
    assert parse_answer('```json\n{"answer_text": "x"}\n```').answer_text == "x"
    with pytest.raises(AskError):
        parse_answer("not json")
    with pytest.raises(AskError):
        parse_answer('{"answer_text": ""}')


# ---- composing fallback answers: grounded by construction -------------------------------------------------


COMPOSE: list[tuple[Intent, dict[str, Any]]] = [
    (Intent("list_high_risk_patients", {}), RISK_RESULT),
    (Intent("list_high_risk_patients", {}), {"hospital": "mercy", "unit": None, "patients": []}),
    (
        Intent("get_occupancy", {}),
        {
            "hospital": "mercy",
            "units": [
                {"unit": "ICU", "occupied": 5, "capacity": 6, "occupancy_pct": 83.3},
                {"unit": "WARD", "occupied": 9, "capacity": 14, "occupancy_pct": 64.3},
            ],
        },
    ),
    (
        Intent("get_forecast", {}),
        {
            "hospital": "mercy",
            "horizon_h": 6,
            "expected_arrivals_total": 11.4,
            "arrivals": [{"hours_ahead": 1, "expected": 1.9}],
            "hours_until_full": {"ER": 0.0, "ICU": 3.5, "WARD": None},
            "forecast_available": True,
        },
    ),
    (
        Intent("get_forecast", {}),
        {"hospital": "mercy", "horizon_h": 6, "expected_arrivals_total": 0, "arrivals": [], "hours_until_full": {}, "forecast_available": False},
    ),
    (
        Intent("find_patient", {}),
        {
            "found": True,
            "patient_id": "P-0042",
            "hospital": "mercy",
            "unit": "ICU",
            "bed": "ICU-3",
            "floor": 2,
            "room": "ICU_A",
            "phase": "inpatient",
            "score": 0.81,
            "level": "high",
            "expected_discharge_h": 14.2,
        },
    ),
    (
        Intent("find_patient", {}),
        {
            "found": True,
            "patient_id": "P-0042",
            "hospital": "mercy",
            "unit": "WAITING",
            "bed": None,
            "floor": None,
            "room": None,
            "phase": "waiting_er",
            "score": None,
            "level": None,
            "expected_discharge_h": None,
        },
    ),
    (Intent("find_patient", {}), {"found": False, "patient_id": "P-9999"}),
    (Intent("get_er_wait", {}), {"hospital": "mercy", "er_wait_min": 77.2, "waiting": 10}),
    (
        Intent("get_staffing", {}),
        {"hospital": "mercy", "units": [{"unit": "ER", "nurses": 2, "required": 3}, {"unit": "ICU", "nurses": 3, "required": 3}]},
    ),
]


@pytest.mark.parametrize(("intent", "result"), COMPOSE)
def test_every_composed_answer_passes_the_grounding_check(intent: Intent, result: dict[str, Any]) -> None:
    out = compose(intent, result, "Mercy General")
    assert out.answer_text and check_answer(out, [result]) == [], out.answer_text


def test_composed_answers_name_the_patients_to_highlight_and_say_what_they_found() -> None:
    top = compose(Intent("list_high_risk_patients", {}), RISK_RESULT, "Mercy General")
    assert top.entity_ids == ["P-0042", "P-0007"] and "P-0042 in ICU-3" in top.answer_text and "risk 0.81" in top.answer_text
    assert "SpO2 drop, 2h" in top.answer_text and "in the ICU" in top.answer_text
    where = compose(Intent("find_patient", {}), COMPOSE[5][1], "Mercy General")
    assert where.entity_ids == ["P-0042"] and "ICU-3" in where.answer_text and "14.2 hours" in where.answer_text
    full = compose(Intent("get_forecast", {}), COMPOSE[3][1], "Mercy General")
    assert "full now" in full.answer_text and "fill in 3.5 hours" in full.answer_text and "any time soon" in full.answer_text
    assert FALLBACK_ASK_LABEL == "Fallback intent parser — Gemini unavailable"
