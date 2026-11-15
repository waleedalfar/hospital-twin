"""Simulation invariants (PROMPT.md §5.8), checked every tick in tests and in debug mode."""

from twin.sim.entities import Patient, Staff
from twin.sim.hospital import BED_UNITS
from twin.sim.world import World


class InvariantError(AssertionError):
    """The simulation reached an impossible state."""


def check(world: World) -> None:
    problems = find_problems(world)
    if problems:
        raise InvariantError(f"t={world.now:.0f} min: " + "; ".join(problems[:10]))


def find_problems(world: World) -> list[str]:
    problems: list[str] = []
    layout = world.layout
    seen: dict[str, str] = {}
    for hospital in world.hospitals.values():
        for person in hospital.people.values():
            if person.id in seen:
                problems.append(f"{person.id} is in {seen[person.id]} and {hospital.id}")
            seen[person.id] = hospital.id
            if person.hospital_id != hospital.id:
                problems.append(f"{person.id} listed in {hospital.id} but says {person.hospital_id}")
            place = person.place
            held = [x for x in (place.bed, place.spot, place.vehicle) if x is not None]
            if len(held) != 1:
                problems.append(f"{person.id} has {len(held)} locations: {place}")
            if place.spot is not None and place.spot not in layout.spots_by_id and place.spot not in layout.seats_by_id:
                problems.append(f"{person.id} is at unknown spot {place.spot}")
            if place.bed is not None and not isinstance(person, Patient):
                problems.append(f"{person.id} is not a patient but holds bed {place.bed}")
            if isinstance(person, Staff) and place.vehicle is not None and person.kind != "emt":
                problems.append(f"{person.id} is a {person.kind} in a vehicle")

        # Beds: one patient per bed, both sides agree, states consistent.
        in_beds: dict[str, list[str]] = {}
        for patient in hospital.patients():
            if patient.place.bed is not None:
                in_beds.setdefault(patient.place.bed, []).append(patient.id)
        for bed in hospital.beds.values():
            holders = in_beds.get(bed.id, [])
            if len(holders) > 1:
                problems.append(f"{hospital.id} {bed.id} holds {holders}")
            if bed.state == "occupied" and holders != [bed.patient_id]:
                problems.append(f"{hospital.id} {bed.id} occupied by {bed.patient_id} but patients there: {holders}")
            if bed.state != "occupied" and (holders or bed.patient_id is not None):
                problems.append(f"{hospital.id} {bed.id} is {bed.state} but has {holders or bed.patient_id}")
        for unit in BED_UNITS:
            capacity = layout.capacity[unit]
            occupied = sum(1 for b in hospital.beds.values() if b.unit == unit and b.state == "occupied")
            free = len(hospital.pools[unit].free)
            if occupied > capacity or free > capacity:
                problems.append(f"{hospital.id} {unit}: {occupied} occupied, {free} free, capacity {capacity}")
            open_beds = {b.id for b in hospital.beds.values() if b.unit == unit and b.state == "open"}
            reserved = {p.reserved_bed for p in hospital.patients() if p.reserved_bed is not None}
            lost = open_beds - set(hospital.pools[unit].free) - reserved
            if lost:
                problems.append(f"{hospital.id} {unit}: open beds {sorted(lost)} are neither free nor reserved")
            if not set(hospital.pools[unit].free) <= open_beds:
                problems.append(f"{hospital.id} {unit}: beds queued as free are not open")

        # Seats and spots held by exactly the person standing there.
        for spot, holder_id in hospital.holders.items():
            holder = hospital.people.get(holder_id)
            if holder is None:
                problems.append(f"{hospital.id} {spot} held by absent {holder_id}")
            elif holder.place.spot != spot:
                problems.append(f"{hospital.id} {spot} held by {holder_id} who is at {holder.place.spot}")

        # Conservation (§5.8): arrived = present + discharged + transferred out.
        counters = hospital.counters
        present = len(hospital.patients())
        if counters.arrived != present + counters.discharged + counters.transferred_out:
            problems.append(
                f"{hospital.id} conservation: arrived {counters.arrived} != present {present} + "
                f"discharged {counters.discharged} + transferred {counters.transferred_out}"
            )
    return problems
