"""The agent's input summary, grounding check, rules engine and prompt (PROMPT.md §9)."""

import json

import pytest

from tests.agent_helpers import busy_summary, fixture, patient
from twin.agent import rules
from twin.agent.llm import SYSTEM, build_prompt, make_client
from twin.agent.schema import FALLBACK_LABEL, AgentOutput, CitedMetric, Recommendation
from twin.agent.summary import flat_metrics
from twin.agent.validator import apply_params, check_metrics, validate


def rec(**kw: object) -> Recommendation:
    base: dict[str, object] = {
        "id": "r1",
        "hospital_id": "mercy",
        "action": "divert_ambulances",
        "targets": ["desert"],
        "params": {"duration_min": 90},
        "rationale": "x",
        "cited_metrics": [CitedMetric(name="waiting", value=10)],
    }
    base.update(kw)
    return Recommendation.model_validate(base)


def out(*recs: Recommendation) -> AgentOutput:
    return AgentOutput(recommendations=list(recs))


def test_flat_metrics_name_every_number_in_the_summary() -> None:
    m = flat_metrics(busy_summary())
    assert m["ER.occupied"] == 6 and m["ER.capacity"] == 6 and m["er_wait_min"] == 77.2
    assert m["ER.hours_until_full"] == 0.0 and "ICU.hours_until_full" not in m  # None is not a number
    assert m["staff.WARD.required"] == 3 and m["other.desert.occupancy_pct"] == 48.3
    assert m["patient.P-0042.score"] == 0.81 and m["patient.P-0100.hours_in_hospital"] == 55.0
    assert m["forecast_arrivals_6h"] == 9.4 and m["high_risk_patients"] == 1


def test_a_grounded_recommendation_passes() -> None:
    parsed = AgentOutput.model_validate_json(fixture("valid_divert.json"))
    assert validate(parsed, busy_summary()) == []


def test_grounding_rejects_a_value_that_is_not_in_the_input() -> None:
    errors = validate(AgentOutput.model_validate_json(fixture("ungrounded_value.json")), busy_summary())
    assert len(errors) == 1 and "er_wait_min" in errors[0] and "77.2" in errors[0]


def test_grounding_rejects_a_metric_name_that_is_not_in_the_input() -> None:
    errors = validate(AgentOutput.model_validate_json(fixture("unknown_metric.json")), busy_summary())
    assert any("icu.magic" in e and "not in the input" in e for e in errors)


def test_grounding_accepts_rounding_but_not_a_different_number() -> None:
    m = flat_metrics(busy_summary())
    ok = rec(
        cited_metrics=[
            CitedMetric(name="er_wait_min", value=77.24),
            CitedMetric(name="patient.P-0042.score", value=0.81),
        ]
    )
    assert check_metrics(ok, m) == []
    off = rec(cited_metrics=[CitedMetric(name="er_wait_min", value=77.4)])
    assert check_metrics(off, m)
    assert any("cites no metrics" in e for e in check_metrics(rec(cited_metrics=[]), m))


def test_unknown_targets_are_rejected() -> None:
    errors = validate(AgentOutput.model_validate_json(fixture("bad_target.json")), busy_summary())
    assert any("atlantis" in e and "not another hospital" in e for e in errors)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"targets": ["mercy"]}, "not another hospital"),
        ({"targets": []}, "no targets"),
        ({"targets": ["desert", "desert"]}, "duplicate"),
        ({"params": {"duration_min": 5}}, "duration_min"),
        ({"params": {"duration_min": 9999}}, "duration_min"),
        ({"params": {}}, "duration_min"),
        ({"params": {"duration_min": True}}, "duration_min"),
        ({"hospital_id": "desert"}, "is not mercy"),
    ],
)
def test_divert_checks(kwargs: dict[str, object], message: str) -> None:
    assert any(message in e for e in validate(out(rec(**kwargs)), busy_summary()))


def test_divert_to_a_hospital_that_is_not_open_is_rejected() -> None:
    s = busy_summary()
    s = s.model_copy(update={"other_hospitals": [o.model_copy(update={"status": "offline"}) for o in s.other_hospitals]})
    assert any("offline" in e for e in validate(out(rec()), s))
    assert any("already diverting" in e for e in validate(out(rec()), busy_summary(status="diverting")))


def test_expedite_discharge_is_only_for_low_risk_ward_patients() -> None:
    ok = rec(action="expedite_discharge", targets=["P-0100", "P-0101"], params={})
    assert validate(out(ok), busy_summary()) == []
    high = rec(action="expedite_discharge", targets=["P-0042"], params={})
    assert any("not low risk" in e for e in validate(out(high), busy_summary()))
    ghost = rec(action="expedite_discharge", targets=["P-9999"], params={})
    assert any("not a known patient" in e for e in validate(out(ghost), busy_summary()))
    many = rec(action="expedite_discharge", targets=[f"P-{i}" for i in range(6)], params={})
    assert any("at most 5" in e for e in validate(out(many), busy_summary()))


def test_move_call_in_and_hold_checks() -> None:
    s = busy_summary()
    assert validate(out(rec(action="move_patient", targets=["P-0042"], params={"bed_id": "ICU-6"})), s) == []
    assert any("open bed" in e for e in validate(out(rec(action="move_patient", targets=["P-0042"], params={"bed_id": "ICU-1"})), s))
    assert any("one patient" in e for e in validate(out(rec(action="move_patient", targets=["P-0000"], params={"bed_id": "ICU-6"})), s))
    assert validate(out(rec(action="call_in_staff", targets=["WARD"], params={"count": 1})), s) == []
    assert any("one unit" in e for e in validate(out(rec(action="call_in_staff", targets=["OR"], params={"count": 1})), s))
    assert any("count" in e for e in validate(out(rec(action="call_in_staff", targets=["WARD"], params={"count": 9})), s))
    assert any("count" in e for e in validate(out(rec(action="call_in_staff", targets=["WARD"], params={"count": 1.5})), s))
    assert validate(out(rec(action="hold_bed", targets=["ICU-6"], params={"minutes": 60})), s) == []
    assert any("open bed" in e for e in validate(out(rec(action="hold_bed", targets=["ICU-1"], params={"minutes": 60})), s))
    assert any("minutes" in e for e in validate(out(rec(action="hold_bed", targets=["ICU-6"], params={"minutes": 1})), s))


def test_duplicate_recommendation_ids_are_rejected() -> None:
    assert any("not unique" in e for e in validate(out(rec(), rec()), busy_summary()))


def test_the_schema_rejects_unknown_actions_and_bad_json() -> None:
    with pytest.raises(ValueError, match="launch_missiles"):
        AgentOutput.model_validate_json(fixture("wrong_action.json"))
    with pytest.raises(ValueError, match=r"EOF|Invalid JSON|json"):
        AgentOutput.model_validate_json(fixture("malformed.json"))
    assert AgentOutput.model_validate_json(fixture("empty.json")).recommendations == []


def test_approved_recommendations_become_the_simulations_action_parameters() -> None:
    assert apply_params(rec()) == {"hospital_id": "mercy", "duration_min": 90.0}
    assert apply_params(rec(action="expedite_discharge", targets=["P-1"], params={})) == {
        "hospital_id": "mercy",
        "patient_ids": ["P-1"],
    }
    assert apply_params(rec(action="move_patient", targets=["P-1"], params={"bed_id": "ICU-6"})) == {
        "hospital_id": "mercy",
        "patient_id": "P-1",
        "bed_id": "ICU-6",
    }
    assert apply_params(rec(action="call_in_staff", targets=["ICU"], params={"count": 2})) == {
        "hospital_id": "mercy",
        "unit": "ICU",
        "count": 2,
    }
    assert apply_params(rec(action="hold_bed", targets=["ICU-6"], params={"minutes": 45})) == {
        "hospital_id": "mercy",
        "bed_id": "ICU-6",
        "minutes": 45.0,
    }


# ---- rules engine --------------------------------------------------------------------------------------------


def test_rules_divert_when_the_er_is_full_and_busy_to_the_emptiest_open_hospital() -> None:
    s = busy_summary()
    output = rules.recommend(s)
    divert = next(r for r in output.recommendations if r.action == "divert_ambulances")
    assert divert.targets == ["desert"]  # St. Luke's is at 90%
    assert validate(output, s) == []  # the rules engine obeys the same grounding check
    assert {m.name for m in divert.cited_metrics} >= {
        "ER.occupied",
        "waiting",
        "er_wait_min",
        "other.desert.occupancy_pct",
    }
    assert "77" in divert.rationale and "Desert Valley" in divert.rationale


def test_rules_output_is_valid_for_every_action_it_produces() -> None:
    s = busy_summary()
    output = rules.recommend(s)
    actions = {r.action for r in output.recommendations}
    assert {"divert_ambulances", "expedite_discharge", "call_in_staff", "hold_bed"} == actions
    assert validate(output, s) == []
    discharge = next(r for r in output.recommendations if r.action == "expedite_discharge")
    assert discharge.targets == ["P-0100", "P-0101"]
    staff = next(r for r in output.recommendations if r.action == "call_in_staff")
    assert staff.targets == ["WARD"] and staff.params == {"count": 1}
    assert FALLBACK_LABEL == "Rules engine — Gemini unavailable"


def test_rules_stay_quiet_when_nothing_is_wrong() -> None:
    from twin.agent.summary import StaffSummary, UnitSummary

    calm = busy_summary(
        waiting=0,
        er_wait_min=2.0,
        units=[UnitSummary(unit=u, occupied=1, capacity=c, hours_until_full=None) for u, c in (("ER", 6), ("WARD", 14), ("ICU", 6), ("REC", 3))],
        high_risk=[],
        expedite_candidates=[],
        staffing=[StaffSummary(unit=u, nurses=3, required=1) for u in ("ER", "WARD", "ICU", "REC")],
    )
    assert rules.recommend(calm).recommendations == []


def test_rules_do_not_divert_when_already_diverting_or_when_nowhere_has_room() -> None:
    assert not any(r.action == "divert_ambulances" for r in rules.recommend(busy_summary(status="diverting")).recommendations)
    s = busy_summary()
    full = s.model_copy(update={"other_hospitals": [o.model_copy(update={"occupancy_pct": 95.0}) for o in s.other_hospitals]})
    assert not any(r.action == "divert_ambulances" for r in rules.recommend(full).recommendations)


def test_rules_only_hold_an_icu_bed_when_there_are_high_risk_patients() -> None:
    s = busy_summary(high_risk=[])
    assert not any(r.action == "hold_bed" for r in rules.recommend(s).recommendations)
    assert patient("P-1").level == "low"


# ---- prompt and client ---------------------------------------------------------------------------------------


def test_prompt_contains_the_summary_the_metric_names_and_any_validation_errors() -> None:
    s = busy_summary()
    prompt = build_prompt(s)
    body = json.loads(prompt.split("INPUT:\n", 1)[1])
    assert body["summary"]["hospital_id"] == "mercy"
    assert body["metrics"]["ER.occupied"] == 6
    assert "cited_metrics" in SYSTEM and "ONLY names" in SYSTEM
    retry = build_prompt(s, ["r1: metric 'x' is not in the input"])
    assert "rejected for these reasons" in retry and "metric 'x' is not in the input" in retry
    assert "rejected" not in prompt


def test_no_client_without_a_key_and_a_model_name_and_none_is_hardcoded() -> None:
    assert make_client(None, None) is None
    assert make_client("key", None) is None
    assert make_client(None, "some-model") is None
    import inspect

    import twin.agent.llm as llm

    assert "gemini-" not in inspect.getsource(llm).replace("GEMINI_", "").lower().replace("gemini client", "")


def test_replies_with_code_fences_or_trailing_commas_are_still_read() -> None:
    from twin.agent.schema import parse_agent_output

    good = fixture("valid_divert.json")
    assert parse_agent_output(f"```json\n{good}\n```").recommendations[0].action == "divert_ambulances"
    assert parse_agent_output('{"recommendations": [],}').recommendations == []
    assert parse_agent_output('{"recommendations": [], "metrics": {}}').recommendations == []  # extra keys are ignored
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_agent_output(fixture("malformed.json"))
    with pytest.raises(ValueError, match="does not match"):
        parse_agent_output('{"recommendations": [{"action": "launch_missiles"}]}')
