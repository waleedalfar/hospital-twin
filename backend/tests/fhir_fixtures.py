"""Hand-built FHIR bundles shaped like Synthea output. Test data only."""

import json
from pathlib import Path
from typing import Any

Json = dict[str, Any]


def condition(name: str, status: str = "active", *, use_text: bool = False) -> Json:
    code: Json = {"coding": [{"system": "http://snomed.info/sct", "code": "1", "display": name}]}
    if use_text:
        code = {"text": name}
    return {
        "resourceType": "Condition",
        "id": f"cond-{name}-{status}",
        "clinicalStatus": {"coding": [{"code": status}]},
        "code": code,
    }


def patient_bundle(
    synthea_id: str,
    *,
    gender: str = "female",
    birth_date: str = "1960-05-01",
    conditions: list[Json] | None = None,
    deceased: bool = False,
) -> Json:
    patient: Json = {"resourceType": "Patient", "id": synthea_id, "gender": gender, "birthDate": birth_date}
    if deceased:
        patient["deceasedDateTime"] = "2020-01-01T00:00:00Z"
    resources: list[Json] = [
        patient,
        {"resourceType": "Encounter", "id": "enc-1"},
        *(conditions if conditions is not None else [condition("Essential hypertension (disorder)")]),
        {"resourceType": "Observation", "id": "obs-1"},
    ]
    return {"resourceType": "Bundle", "type": "transaction", "entry": [{"resource": r} for r in resources]}


def write_bundles(directory: Path, bundles: list[Json]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        patient = bundle["entry"][0]["resource"]
        (directory / f"Test_{patient['id']}.json").write_text(json.dumps(bundle), encoding="utf-8")
    return directory
