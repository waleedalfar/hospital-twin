"""Extracts what the twin needs from a Synthea FHIR bundle: the Patient and Condition resources, plus
age, sex, active conditions and a comorbidity count (PROMPT.md §4.3)."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

JsonObject = dict[str, Any]

# Chronic disease groups counted as comorbidities. A patient scores one per group that matches any of
# their active conditions, so two diabetes complications still count once.
COMORBIDITY_GROUPS: dict[str, tuple[str, ...]] = {
    "diabetes": ("diabetes", "diabetic"),
    "hypertension": ("hypertension",),
    "ischemic_heart_disease": ("ischemic heart", "coronary", "myocardial infarction"),
    "heart_failure": ("heart failure",),
    "atrial_fibrillation": ("atrial fibrillation",),
    "copd": ("pulmonary emphysema", "chronic obstructive", "chronic bronchitis"),
    "asthma": ("asthma",),
    "chronic_kidney_disease": ("chronic kidney disease", "end-stage renal", "renal transplant"),
    "cancer": ("neoplasm", "carcinoma", "cancer", "leukemia", "lymphoma", "malignant"),
    "stroke": ("stroke", "cerebrovascular"),
    "dementia": ("dementia", "alzheimer"),
    "obesity": ("obesity",),
    "anemia": ("anemia",),
    "hyperlipidemia": ("hyperlipidemia", "hypertriglyceridemia", "metabolic syndrome"),
}

# Synthea records social circumstances as Conditions. They are not medical conditions and are left out.
_SOCIAL = re.compile(
    r"employment|unemployed|labor force|education|school|social|stress|criminal|violence|abuse|housing|"
    r"refugee|medication review|risk activity|transport|armed forces|homeless|lack of access|"
    r"intimate partner|reports of|unhealthy alcohol",
    re.IGNORECASE,
)


class FhirError(Exception):
    """A bundle does not have the structure of a Synthea patient bundle."""


@dataclass(frozen=True)
class PatientRecord:
    synthea_id: str
    fhir: JsonObject
    age: int
    sex: str
    conditions: list[str]
    comorbidity_count: int


def _resources(bundle: JsonObject, resource_type: str) -> list[JsonObject]:
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        raise FhirError("Bundle has no entry list")
    found: list[JsonObject] = []
    for entry in entries:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if isinstance(resource, dict) and resource.get("resourceType") == resource_type:
            found.append(resource)
    return found


def age_on(birth_date: str, as_of: date) -> int:
    """Whole years between a FHIR birthDate (YYYY-MM-DD) and `as_of`."""
    try:
        born = date.fromisoformat(birth_date)
    except ValueError as error:
        raise FhirError(f"Bad birthDate {birth_date!r}") from error
    if born > as_of:
        raise FhirError(f"birthDate {birth_date} is after {as_of}")
    return as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))


def condition_name(condition: JsonObject) -> str | None:
    code = condition.get("code")
    if not isinstance(code, dict):
        return None
    text = code.get("text")
    if isinstance(text, str) and text:
        return text
    codings = code.get("coding")
    if isinstance(codings, list) and codings and isinstance(codings[0], dict):
        display = codings[0].get("display")
        return display if isinstance(display, str) and display else None
    return None


def is_active(condition: JsonObject) -> bool:
    status = condition.get("clinicalStatus")
    codings = status.get("coding") if isinstance(status, dict) else None
    if not isinstance(codings, list):
        return False
    return any(isinstance(coding, dict) and coding.get("code") == "active" for coding in codings)


_GROUP_PATTERNS: dict[str, re.Pattern[str]] = {
    # Keywords match at the start of a word, so "prediabetes" is not counted as diabetes.
    group: re.compile("|".join(rf"\b{re.escape(keyword)}" for keyword in keywords), re.IGNORECASE)
    for group, keywords in COMORBIDITY_GROUPS.items()
}


def comorbidity_groups(conditions: list[str]) -> set[str]:
    """The comorbidity groups present in a list of condition names."""
    return {
        group
        for group, pattern in _GROUP_PATTERNS.items()
        if any(pattern.search(name) for name in conditions)
    }


def parse_bundle(bundle: JsonObject, as_of: date) -> PatientRecord | None:
    """Build a patient record from one Synthea bundle. Returns None for a patient who has died."""
    patients = _resources(bundle, "Patient")
    if len(patients) != 1:
        raise FhirError(f"Expected exactly one Patient resource, found {len(patients)}")
    patient = patients[0]
    if "deceasedDateTime" in patient or patient.get("deceasedBoolean") is True:
        return None
    synthea_id, sex, birth_date = patient.get("id"), patient.get("gender"), patient.get("birthDate")
    if not isinstance(synthea_id, str) or not synthea_id:
        raise FhirError("Patient has no id")
    if sex not in ("male", "female"):
        raise FhirError(f"Patient {synthea_id} has unsupported gender {sex!r}")
    if not isinstance(birth_date, str):
        raise FhirError(f"Patient {synthea_id} has no birthDate")

    all_conditions = _resources(bundle, "Condition")
    names = {name for c in all_conditions if is_active(c) and (name := condition_name(c)) is not None}
    conditions = sorted(name for name in names if not _SOCIAL.search(name))
    trimmed: JsonObject = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": patient}, *({"resource": condition} for condition in all_conditions)],
    }
    return PatientRecord(
        synthea_id=synthea_id,
        fhir=trimmed,
        age=age_on(birth_date, as_of),
        sex=sex,
        conditions=conditions,
        comorbidity_count=len(comorbidity_groups(conditions)),
    )
