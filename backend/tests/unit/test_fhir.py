from datetime import date

import pytest

from tests.fhir_fixtures import condition, patient_bundle
from twin.db.fhir import FhirError, age_on, comorbidity_groups, condition_name, is_active, parse_bundle

AS_OF = date(2026, 11, 14)


def test_parse_extracts_age_sex_conditions_and_comorbidities() -> None:
    bundle = patient_bundle(
        "abc-1",
        gender="male",
        birth_date="1950-11-15",
        conditions=[
            condition("Essential hypertension (disorder)"),
            condition("Diabetes mellitus type 2 (disorder)"),
            condition("Disorder of kidney due to diabetes mellitus (disorder)"),
            condition("Chronic kidney disease stage 2 (disorder)", use_text=True),
            condition("Viral sinusitis (disorder)", status="resolved"),
            condition("Full-time employment (finding)"),
            condition("Stress (finding)"),
            condition("Essential hypertension (disorder)"),
        ],
    )
    record = parse_bundle(bundle, AS_OF)
    assert record is not None
    assert record.synthea_id == "abc-1"
    assert record.sex == "male"
    assert record.age == 75  # birthday is the day after the reference date
    assert record.conditions == [
        "Chronic kidney disease stage 2 (disorder)",
        "Diabetes mellitus type 2 (disorder)",
        "Disorder of kidney due to diabetes mellitus (disorder)",
        "Essential hypertension (disorder)",
    ]
    assert record.comorbidity_count == 3  # hypertension, diabetes (counted once), chronic kidney disease


def test_stored_bundle_keeps_only_patient_and_condition_resources() -> None:
    record = parse_bundle(patient_bundle("abc-2"), AS_OF)
    assert record is not None
    types = [entry["resource"]["resourceType"] for entry in record.fhir["entry"]]
    assert types == ["Patient", "Condition"]
    assert record.fhir["resourceType"] == "Bundle"
    assert record.fhir["entry"][0]["resource"]["id"] == "abc-2"


def test_resolved_conditions_are_stored_but_not_listed() -> None:
    bundle = patient_bundle("abc-3", conditions=[condition("Asthma", status="resolved")])
    record = parse_bundle(bundle, AS_OF)
    assert record is not None
    assert record.conditions == []
    assert record.comorbidity_count == 0
    assert len(record.fhir["entry"]) == 2


def test_deceased_patients_are_left_out() -> None:
    assert parse_bundle(patient_bundle("dead-1", deceased=True), AS_OF) is None
    boolean_form = patient_bundle("dead-2")
    boolean_form["entry"][0]["resource"]["deceasedBoolean"] = True
    assert parse_bundle(boolean_form, AS_OF) is None


@pytest.mark.parametrize(
    ("birth", "expected"),
    [("2000-11-14", 26), ("2000-11-15", 25), ("2000-01-01", 26), ("2026-11-14", 0), ("1936-12-31", 89)],
)
def test_age_on(birth: str, expected: int) -> None:
    assert age_on(birth, AS_OF) == expected


def test_age_on_rejects_bad_dates() -> None:
    with pytest.raises(FhirError, match="Bad birthDate"):
        age_on("1990", AS_OF)
    with pytest.raises(FhirError, match="is after"):
        age_on("2030-01-01", AS_OF)


def test_comorbidity_groups_match_whole_word_starts() -> None:
    assert comorbidity_groups(["Prediabetes"]) == set()
    assert comorbidity_groups(["Diabetes mellitus type 2 (disorder)"]) == {"diabetes"}
    assert comorbidity_groups(["Body mass index 30+ - obesity (finding)", "Anemia (disorder)"]) == {
        "obesity",
        "anemia",
    }
    assert comorbidity_groups(["Malignant neoplasm of breast (disorder)"]) == {"cancer"}
    assert comorbidity_groups(["Chronic congestive heart failure (disorder)", "Ischemic heart disease (disorder)"]) == {
        "heart_failure",
        "ischemic_heart_disease",
    }
    assert comorbidity_groups([]) == set()


def test_condition_name_and_status_handle_missing_parts() -> None:
    assert condition_name({"code": {"text": "A"}}) == "A"
    assert condition_name({"code": {"coding": [{"display": "B"}]}}) == "B"
    assert condition_name({"code": {"coding": [{}]}}) is None
    assert condition_name({"code": {"coding": []}}) is None
    assert condition_name({"code": "x"}) is None
    assert condition_name({}) is None
    assert is_active({"clinicalStatus": {"coding": [{"code": "active"}]}})
    assert not is_active({"clinicalStatus": {"coding": [{"code": "resolved"}]}})
    assert not is_active({"clinicalStatus": {}})
    assert not is_active({})


def test_condition_without_a_name_is_ignored() -> None:
    nameless = {"resourceType": "Condition", "clinicalStatus": {"coding": [{"code": "active"}]}, "code": {}}
    record = parse_bundle(patient_bundle("abc-4", conditions=[nameless]), AS_OF)
    assert record is not None
    assert record.conditions == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: b.pop("entry"), "no entry list"),
        (lambda b: b["entry"].pop(0), "exactly one Patient"),
        (lambda b: b["entry"].append(b["entry"][0]), "exactly one Patient"),
        (lambda b: b["entry"][0]["resource"].pop("id"), "no id"),
        (lambda b: b["entry"][0]["resource"].update(gender="other"), "unsupported gender"),
        (lambda b: b["entry"][0]["resource"].pop("birthDate"), "no birthDate"),
    ],
)
def test_malformed_bundles_are_rejected(mutate: object, message: str) -> None:
    bundle = patient_bundle("bad-1")
    assert callable(mutate)
    mutate(bundle)
    with pytest.raises(FhirError, match=message):
        parse_bundle(bundle, AS_OF)


def test_non_dict_entries_are_skipped() -> None:
    bundle = patient_bundle("abc-5")
    bundle["entry"].append("not an entry")
    bundle["entry"].append({"resource": "not a resource"})
    assert parse_bundle(bundle, AS_OF) is not None
