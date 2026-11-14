"""Actions the simulation accepts when a human approves an agent recommendation (PROMPT.md §5.7). Each one
changes the simulation visibly and emits an `action` event; the caller writes the audit entry."""

from twin.common.ws import ActionEvent, ActionName
from twin.sim.entities import Patient
from twin.sim.patients import set_bed
from twin.sim.world import SimGen, World

UNITS_FOR_STAFF = ("ER", "TRIAGE", "WARD", "ICU", "REC")
MAX_DIVERT_MIN = 24 * 60
MAX_HOLD_MIN = 8 * 60
MAX_CALL_IN = 10


class ActionError(Exception):
    """The action cannot be applied as asked (unknown ids, wrong state, out-of-range values)."""


def _hospital(world: World, hospital_id: str) -> None:
    if hospital_id not in world.hospitals:
        raise ActionError(f"Unknown hospital {hospital_id}")


def divert_ambulances(world: World, hospital_id: str, duration_min: float) -> str:
    from twin.sim.vehicles import set_hospital_status

    _hospital(world, hospital_id)
    if not 0 < duration_min <= MAX_DIVERT_MIN:
        raise ActionError(f"duration_min must be in (0, {MAX_DIVERT_MIN}]")
    hospital = world.hospitals[hospital_id]
    if hospital.status == "offline":
        raise ActionError(f"{hospital_id} is offline; it already takes no ambulances")
    set_hospital_status(world, hospital, "diverting", world.now + duration_min, "diversion approved")
    return f"{hospital_id} diverting ambulances for {duration_min:g} min"


def expedite_discharge(world: World, patient_ids: list[str]) -> str:
    if not patient_ids:
        raise ActionError("No patients given")
    found: list[Patient] = []
    for patient_id in patient_ids:
        located = world.patient(patient_id)
        if located is None:
            raise ActionError(f"Patient {patient_id} is not in any hospital")
        patient = located[1]
        if patient.phase != "inpatient" or patient.unit not in ("WARD", "REC"):
            raise ActionError(f"Patient {patient_id} is not a ward or recovery inpatient")
        found.append(patient)
    for patient in found:
        if not world.kick(patient, "discharge"):
            raise ActionError(f"Patient {patient.id} is moving; try again in a minute")
    return f"discharging {', '.join(p.id for p in found)}"


def move_patient(world: World, patient_id: str, bed_id: str) -> str:
    located = world.patient(patient_id)
    if located is None:
        raise ActionError(f"Patient {patient_id} is not in any hospital")
    hospital, patient = located
    if bed_id not in hospital.beds:
        raise ActionError(f"Unknown bed {bed_id}")
    if patient.place.bed == bed_id:
        raise ActionError(f"Patient {patient_id} is already in {bed_id}")
    bed = hospital.beds[bed_id]
    if bed.state != "open" or hospital.pools[bed.unit].try_take(bed_id) is None:
        raise ActionError(f"Bed {bed_id} is not free (state {bed.state})")
    patient.reserved_bed = bed_id
    if not world.kick(patient, "move", bed_id):
        patient.reserved_bed = None
        hospital.pools[bed.unit].release(bed_id)
        raise ActionError(f"Patient {patient_id} cannot be moved right now")
    return f"moving {patient_id} to {bed_id}"


def call_in_staff(world: World, hospital_id: str, unit: str, count: int) -> str:
    from twin.sim.staff import call_in

    _hospital(world, hospital_id)
    if unit not in UNITS_FOR_STAFF:
        raise ActionError(f"Unit must be one of {UNITS_FOR_STAFF}")
    if not 1 <= count <= MAX_CALL_IN:
        raise ActionError(f"count must be 1..{MAX_CALL_IN}")
    added = call_in(world, world.hospitals[hospital_id], unit, count, "called in")
    return f"called in {', '.join(added)} to {hospital_id} {unit}"


def hold_bed(world: World, hospital_id: str, bed_id: str, minutes: float) -> str:
    _hospital(world, hospital_id)
    hospital = world.hospitals[hospital_id]
    if bed_id not in hospital.beds:
        raise ActionError(f"Unknown bed {bed_id}")
    if not 0 < minutes <= MAX_HOLD_MIN:
        raise ActionError(f"minutes must be in (0, {MAX_HOLD_MIN}]")
    bed = hospital.beds[bed_id]
    if bed.state != "open" or hospital.pools[bed.unit].try_take(bed_id) is None:
        raise ActionError(f"Bed {bed_id} is not free (state {bed.state})")
    set_bed(world, hospital, bed_id, None, "blocked")
    world.env.process(unhold_later(world, hospital_id, bed_id, world.now + minutes))
    return f"holding {bed_id} at {hospital_id} for {minutes:g} min"


def unhold_later(world: World, hospital_id: str, bed_id: str, until: float) -> SimGen:
    yield world.env.timeout(until - world.now)
    hospital = world.hospitals[hospital_id]
    set_bed(world, hospital, bed_id, None, "open")
    hospital.pools[hospital.beds[bed_id].unit].release(bed_id)


def apply(world: World, action: ActionName, params: dict[str, str | float | int | list[str]]) -> str:
    """Apply one action and emit its event. Raises ActionError (and changes nothing) if it is invalid."""

    def text(name: str) -> str:
        value = params.get(name)
        if not isinstance(value, str):
            raise ActionError(f"Parameter {name} must be a string")
        return value

    def number(name: str) -> float:
        value = params.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ActionError(f"Parameter {name} must be a number")
        return float(value)

    if action == "divert_ambulances":
        result = divert_ambulances(world, text("hospital_id"), number("duration_min"))
    elif action == "expedite_discharge":
        ids = params.get("patient_ids")
        if not isinstance(ids, list):
            raise ActionError("Parameter patient_ids must be a list")
        result = expedite_discharge(world, [str(i) for i in ids])
    elif action == "move_patient":
        result = move_patient(world, text("patient_id"), text("bed_id"))
    elif action == "call_in_staff":
        result = call_in_staff(world, text("hospital_id"), text("unit"), int(number("count")))
    elif action == "hold_bed":
        result = hold_bed(world, text("hospital_id"), text("bed_id"), number("minutes"))
    else:
        raise ActionError(f"Unknown action {action}")
    hospital_id = params.get("hospital_id")
    world.emit(
        hospital_id if isinstance(hospital_id, str) else None,
        ActionEvent(time=world.time(), action=action, params=params, result=result),
    )
    return result
