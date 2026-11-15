"""The grounding check (PROMPT.md §9): every cited metric must equal a value in the input summary (after
rounding), and every target id must exist and be valid for its action. Output that fails is retried once with
the errors in the prompt, then dropped."""

from twin.agent.schema import AgentOutput, Recommendation
from twin.agent.summary import STAFF_UNITS, Summary, flat_metrics

DIVERT_MINUTES = (15, 480)
HOLD_MINUTES = (15, 240)
CALL_IN_COUNT = (1, 4)
MAX_EXPEDITE = 5
TOLERANCE = 0.05  # values are rounded to one decimal in the input


def _number(params: dict[str, object], key: str) -> float | None:
    value = params.get(key)
    return None if isinstance(value, bool) or not isinstance(value, int | float) else float(value)


def check_metrics(rec: Recommendation, metrics: dict[str, float]) -> list[str]:
    errors: list[str] = []
    if not rec.cited_metrics:
        errors.append(f"{rec.id}: cites no metrics")
    for cited in rec.cited_metrics:
        actual = metrics.get(cited.name)
        if actual is None:
            errors.append(f"{rec.id}: metric '{cited.name}' is not in the input")
        elif abs(round(cited.value, 1) - actual) > TOLERANCE + 1e-9 and abs(round(cited.value, 2) - actual) > 1e-9:
            errors.append(f"{rec.id}: metric '{cited.name}' is {actual} in the input, not {cited.value}")
    return errors


def check_targets(rec: Recommendation, s: Summary) -> list[str]:
    """Targets and parameters must exist and make sense for the action."""
    errors: list[str] = []
    p: dict[str, object] = dict(rec.params)
    known = {x.id: x for x in [*s.high_risk, *s.expedite_candidates]}
    open_beds = {b for beds in s.open_beds.values() for b in beds}
    if rec.hospital_id != s.hospital_id:
        errors.append(f"{rec.id}: hospital_id {rec.hospital_id} is not {s.hospital_id}")
    if not rec.targets:
        errors.append(f"{rec.id}: no targets")
    if len(set(rec.targets)) != len(rec.targets):
        errors.append(f"{rec.id}: duplicate targets")
    if rec.action == "divert_ambulances":
        others = {o.id: o for o in s.other_hospitals}
        for t in rec.targets:
            if t not in others:
                errors.append(f"{rec.id}: '{t}' is not another hospital in the network")
            elif others[t].status != "open":
                errors.append(f"{rec.id}: {t} is {others[t].status} and cannot take diverted ambulances")
        minutes = _number(p, "duration_min")
        if minutes is None or not DIVERT_MINUTES[0] <= minutes <= DIVERT_MINUTES[1]:
            errors.append(f"{rec.id}: params.duration_min must be a number from {DIVERT_MINUTES[0]} to {DIVERT_MINUTES[1]}")
        if s.status != "open":
            errors.append(f"{rec.id}: {s.hospital_id} is already {s.status}")
    elif rec.action == "expedite_discharge":
        allowed = {x.id for x in s.expedite_candidates}
        if len(rec.targets) > MAX_EXPEDITE:
            errors.append(f"{rec.id}: at most {MAX_EXPEDITE} patients")
        for t in rec.targets:
            if t not in allowed:
                reason = "is not low risk or not a ward patient" if t in known else "is not a known patient"
                errors.append(f"{rec.id}: '{t}' {reason}; expedite_discharge is only for low-risk ward patients")
    elif rec.action == "move_patient":
        if len(rec.targets) != 1 or rec.targets[0] not in known:
            errors.append(f"{rec.id}: target must be one patient from the input")
        bed = p.get("bed_id")
        if not isinstance(bed, str) or bed not in open_beds:
            errors.append(f"{rec.id}: params.bed_id must be an open bed from the input")
    elif rec.action == "call_in_staff":
        if len(rec.targets) != 1 or rec.targets[0] not in STAFF_UNITS:
            errors.append(f"{rec.id}: target must be one unit of {STAFF_UNITS}")
        count = _number(p, "count")
        if count is None or int(count) != count or not CALL_IN_COUNT[0] <= count <= CALL_IN_COUNT[1]:
            errors.append(f"{rec.id}: params.count must be a whole number from {CALL_IN_COUNT[0]} to {CALL_IN_COUNT[1]}")
    elif rec.action == "hold_bed":
        if len(rec.targets) != 1 or rec.targets[0] not in open_beds:
            errors.append(f"{rec.id}: target must be one open bed from the input")
        minutes = _number(p, "minutes")
        if minutes is None or not HOLD_MINUTES[0] <= minutes <= HOLD_MINUTES[1]:
            errors.append(f"{rec.id}: params.minutes must be a number from {HOLD_MINUTES[0]} to {HOLD_MINUTES[1]}")
    return errors


def validate(output: AgentOutput, s: Summary) -> list[str]:
    """All problems with `output` against the input `s`. Empty means the output is grounded and valid."""
    metrics = flat_metrics(s)
    errors: list[str] = []
    ids = [r.id for r in output.recommendations]
    if len(set(ids)) != len(ids):
        errors.append("recommendation ids are not unique")
    for rec in output.recommendations:
        errors += check_metrics(rec, metrics)
        errors += check_targets(rec, s)
    return errors


def apply_params(rec: Recommendation) -> dict[str, str | float | int | list[str]]:
    """The parameters the simulation's action takes for an approved recommendation (PROMPT.md §5.7)."""
    p = rec.params
    if rec.action == "divert_ambulances":
        return {"hospital_id": rec.hospital_id, "duration_min": float(p.get("duration_min", 60))}  # type: ignore[arg-type]
    if rec.action == "expedite_discharge":
        return {"hospital_id": rec.hospital_id, "patient_ids": list(rec.targets)}
    if rec.action == "move_patient":
        return {"hospital_id": rec.hospital_id, "patient_id": rec.targets[0], "bed_id": str(p.get("bed_id"))}
    if rec.action == "call_in_staff":
        return {"hospital_id": rec.hospital_id, "unit": rec.targets[0], "count": int(p.get("count", 1))}  # type: ignore[arg-type]
    return {"hospital_id": rec.hospital_id, "bed_id": rec.targets[0], "minutes": float(p.get("minutes", 60))}  # type: ignore[arg-type]
